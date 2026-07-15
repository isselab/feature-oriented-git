"""Tests for `git feature doctor`."""

import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.store import Annotation, GitRefStore, RegionAnchor
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
    builder.commit("base", files={"a.txt": "a\n"})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init", "--backfill"]).exit_code == 0
    builder.commit("add model.cfr")
    return builder


def test_healthy_repo_passes(runner: CliRunner, builder: RepoBuilder) -> None:
    runner.invoke(app, ["hook-run", "post-commit"])  # map the model.cfr commit
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "healthy" in result.output


def test_uninitialized_repo_fails(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    builder = repo_builder("bare")
    builder.commit("base", files={"a.txt": "a\n"})
    monkeypatch.chdir(builder.path)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "refs/feature/store missing" in result.output
    assert "git feature init" in result.output


def test_deleted_hook_is_detected(runner: CliRunner, builder: RepoBuilder) -> None:
    (builder.path / ".git" / "hooks" / "post-rewrite").unlink()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "post-rewrite" in result.output
    assert "reinstall hooks" in result.output


def test_unmapped_commits_are_informational(runner: CliRunner, builder: RepoBuilder) -> None:
    builder.commit("no hook ran", files={"a.txt": "a\nb\n"})
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output  # lazy minting: info, not a problem
    assert "without change-ids" in result.output
    assert "reconcile" in result.output


def test_dangling_annotation_is_detected(runner: CliRunner, builder: RepoBuilder) -> None:
    store = GitRefStore(builder.repo)
    anchor = RegionAnchor(
        change_id="01JUNKNOWNCHANGE0000000000",
        path="a.txt",
        old_span=(0, 0),
        new_span=(1, 1),
        fingerprint="f",
    )
    annotation = Annotation(anchor=anchor, presence="ghost", author="test", ts=datetime.now(tz=UTC))
    store.write_annotations(anchor.change_id, [annotation])
    store.commit("plant dangling annotation")

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "unknown change-ids" in result.output


def test_json_output(runner: CliRunner, builder: RepoBuilder) -> None:
    runner.invoke(app, ["hook-run", "post-commit"])
    result = runner.invoke(app, ["--json", "doctor"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["healthy"] is True
    assert any(c["name"] == "store" for c in report["checks"])
