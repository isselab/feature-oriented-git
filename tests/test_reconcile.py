"""Tests for `git feature reconcile` and its matching tiers."""

import json
from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.gitio import patch_id
from git_feature.identity import ChangeIdMap
from git_feature.store import GitRefStore
from tests.fixtures import RepoBuilder


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def builder(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> RepoBuilder:
    builder = repo_builder("repo")
    builder.commit("base", files={"a.txt": "one\ntwo\nthree\n"})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    builder.commit("add model.cfr")  # sweep in the generated model so later diffs stay clean
    builder.branch("side")
    return builder


def _mint(builder: RepoBuilder, sha: str) -> str:
    store = GitRefStore(builder.repo)
    record = ChangeIdMap(store).insert(sha, patch_id=patch_id(builder.repo, sha))
    store.commit(f"mint {sha[:12]}")
    return record.change_id


def test_cherry_pick_links_by_patch_id(runner: CliRunner, builder: RepoBuilder) -> None:
    original = builder.commit("feature work", files={"a.txt": "one\nTWO\nthree\n"})
    change_id = _mint(builder, original)
    builder.switch("side")
    copy = builder.commit("feature work (picked)", files={"a.txt": "one\nTWO\nthree\n"})

    result = runner.invoke(app, ["reconcile"])
    assert result.exit_code == 0, result.output
    linked = ChangeIdMap(GitRefStore(builder.repo)).get(copy)
    assert linked is not None
    assert linked.change_id == change_id


def test_modified_cherry_pick_links_fuzzily(runner: CliRunner, builder: RepoBuilder) -> None:
    original = builder.commit(
        "feature work",
        files={"b.txt": "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\neta\ntheta\n"},
    )
    change_id = _mint(builder, original)
    builder.switch("side")
    copy = builder.commit(
        "feature work (tweaked)",
        files={"b.txt": "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\neta\nTHETA\n"},
    )

    result = runner.invoke(app, ["reconcile"])
    assert result.exit_code == 0, result.output
    assert "fuzzy" in result.output
    linked = ChangeIdMap(GitRefStore(builder.repo)).get(copy)
    assert linked is not None
    assert linked.change_id == change_id


def test_dry_run_writes_nothing(runner: CliRunner, builder: RepoBuilder) -> None:
    original = builder.commit("feature work", files={"a.txt": "one\nTWO\nthree\n"})
    _mint(builder, original)
    builder.switch("side")
    copy = builder.commit("feature work (picked)", files={"a.txt": "one\nTWO\nthree\n"})

    result = runner.invoke(app, ["reconcile", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "would link" in result.output
    assert ChangeIdMap(GitRefStore(builder.repo)).get(copy) is None


def test_ambiguous_match_needs_interactive(runner: CliRunner, builder: RepoBuilder) -> None:
    original = builder.commit("feature work", files={"a.txt": "one\nTWO\nthree\n"})
    cid_a = _mint(builder, original)
    # A second known change with the identical patch-id (e.g. imported twice).
    store = GitRefStore(builder.repo)
    ChangeIdMap(store).insert("ee" * 20, patch_id=patch_id(builder.repo, original))
    store.commit("plant duplicate patch-id")
    builder.switch("side")
    copy = builder.commit("feature work (picked)", files={"a.txt": "one\nTWO\nthree\n"})

    result = runner.invoke(app, ["reconcile"])
    assert result.exit_code == 0, result.output
    assert "ambiguous" in result.output
    assert ChangeIdMap(GitRefStore(builder.repo)).get(copy) is None

    result = runner.invoke(app, ["reconcile", "--interactive"], input="1\n")
    assert result.exit_code == 0, result.output
    linked = ChangeIdMap(GitRefStore(builder.repo)).get(copy)
    assert linked is not None
    assert linked.change_id in {
        cid_a,
        ChangeIdMap(GitRefStore(builder.repo)).get("ee" * 20).change_id,
    }  # type: ignore[union-attr]


def test_unrelated_commits_stay_unmapped(runner: CliRunner, builder: RepoBuilder) -> None:
    builder.commit("unrelated", files={"c.txt": "totally different\n"})
    result = runner.invoke(app, ["--json", "reconcile"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["links"] == []
    assert len(report["unmatched"]) >= 1
