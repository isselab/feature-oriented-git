"""Tests for bulk/scripted `git feature annotate`."""

import json
from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
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
    builder.commit("base", files={"src/core.py": "def core():\n    pass\n"})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    builder.commit("add model.cfr")
    return builder


def _annotations(builder: RepoBuilder, sha: str) -> list:
    store = GitRefStore(builder.repo)
    record = ChangeIdMap(store).get(sha)
    assert record is not None, "commit should have been lazily minted"
    return store.read_annotations(record.change_id)


def test_annotate_head_with_one_feature(runner: CliRunner, builder: RepoBuilder) -> None:
    sha = builder.commit("auth work", files={"src/auth.py": "def login():\n    pass\n"})
    result = runner.invoke(app, ["annotate", "--feature", "auth"])
    assert result.exit_code == 0, result.output
    annotations = _annotations(builder, sha)
    assert len(annotations) == 1
    assert annotations[0].presence == "auth"
    assert annotations[0].anchor.path == "src/auth.py"


def test_annotate_mints_change_id_lazily(runner: CliRunner, builder: RepoBuilder) -> None:
    # a pre-existing commit with no change-id gets one the moment it is annotated
    old_sha = builder.commit("old work", files={"src/old.py": "x = 1\n"})
    builder.commit("newer", files={"src/newer.py": "y = 2\n"})
    assert ChangeIdMap(GitRefStore(builder.repo)).get(old_sha) is None

    result = runner.invoke(app, ["annotate", old_sha, "--feature", "legacy"])
    assert result.exit_code == 0, result.output
    assert "minted 1 change-id(s)" in result.output
    record = ChangeIdMap(GitRefStore(builder.repo)).get(old_sha)
    assert record is not None
    assert record.patch_id is not None
    assert len(_annotations(builder, old_sha)) == 1


def test_multiple_features_write_one_annotation_each(
    runner: CliRunner, builder: RepoBuilder
) -> None:
    sha = builder.commit("shared work", files={"src/shared.py": "z = 3\n"})
    result = runner.invoke(app, ["annotate", "--feature", "auth", "--feature", "ui"])
    assert result.exit_code == 0, result.output
    presences = sorted(a.presence for a in _annotations(builder, sha))
    assert presences == ["auth", "ui"]


def test_presence_expression_is_stored_raw(runner: CliRunner, builder: RepoBuilder) -> None:
    sha = builder.commit("gated work", files={"src/gated.py": "g = 4\n"})
    result = runner.invoke(app, ["annotate", "--presence", "auth & premium"])
    assert result.exit_code == 0, result.output
    (annotation,) = _annotations(builder, sha)
    assert annotation.presence == "auth & premium"


def test_path_glob_restricts_hunks(runner: CliRunner, builder: RepoBuilder) -> None:
    sha = builder.commit(
        "mixed work",
        files={"src/auth.py": "a = 1\n", "docs/notes.md": "note\n"},
    )
    result = runner.invoke(app, ["annotate", "--feature", "auth", "--path", "src/*"])
    assert result.exit_code == 0, result.output
    paths = [a.anchor.path for a in _annotations(builder, sha)]
    assert paths == ["src/auth.py"]


def test_range_annotates_every_commit(runner: CliRunner, builder: RepoBuilder) -> None:
    start = str(builder.repo.head.target)
    sha_one = builder.commit("one", files={"src/a.py": "a = 1\n"})
    sha_two = builder.commit("two", files={"src/b.py": "b = 2\n"})
    result = runner.invoke(app, ["annotate", "--feature", "auth", "--range", f"{start}..HEAD"])
    assert result.exit_code == 0, result.output
    assert len(_annotations(builder, sha_one)) == 1
    assert len(_annotations(builder, sha_two)) == 1


def test_rerun_does_not_duplicate(runner: CliRunner, builder: RepoBuilder) -> None:
    sha = builder.commit("auth work", files={"src/auth.py": "def login():\n    pass\n"})
    runner.invoke(app, ["annotate", "--feature", "auth"])
    result = runner.invoke(app, ["--json", "annotate", "--feature", "auth"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["written"] == 0
    assert report["duplicates"] == 1
    assert len(_annotations(builder, sha)) == 1


def test_unknown_feature_is_auto_created(runner: CliRunner, builder: RepoBuilder) -> None:
    builder.commit("new area", files={"src/new.py": "n = 5\n"})
    result = runner.invoke(app, ["annotate", "--feature", "brand-new"])
    assert result.exit_code == 0, result.output
    assert "created feature 'brand-new' (auto)" in result.output
    feature = GitRefStore(builder.repo).read_feature("brand-new")
    assert feature is not None
    assert feature.auto_created


def test_feature_and_presence_conflict(runner: CliRunner, builder: RepoBuilder) -> None:
    result = runner.invoke(app, ["annotate", "--feature", "a", "--presence", "a & b"])
    assert result.exit_code == 2
