"""Tests for `git feature sync`: feature-based commit propagation between branches."""

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.gitio import read_ref
from git_feature.identity import ChangeIdMap
from git_feature.store import GitRefStore
from tests.conftest import AnnotatedRepo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_dry_run_lists_the_missing_commit_without_moving_the_branch(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    builder.switch("release")
    before = read_ref(builder.repo, "refs/heads/release")

    result = runner.invoke(app, ["sync", source, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "add render" in result.output
    assert "[ui]" in result.output
    assert read_ref(builder.repo, "refs/heads/release") == before


def test_sync_propagates_the_commit_and_its_change_id(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    builder.switch("release")

    result = runner.invoke(app, ["sync", source])
    assert result.exit_code == 0, result.output
    assert "synced" in result.output

    new_tip = read_ref(builder.repo, "refs/heads/release")
    assert new_tip is not None and new_tip != annotated_repo.auth_sha
    record = ChangeIdMap(GitRefStore(builder.repo)).get(new_tip)
    assert record is not None
    assert record.change_id == annotated_repo.ui_cid
    # annotations follow the change-id: the copy reports the same feature
    result = runner.invoke(app, ["whatfeature", new_tip])
    assert result.exit_code == 0
    assert "ui" in result.output
    # and the worktree was updated, leaving index and workdir clean
    assert (builder.path / "src/ui/render.py").exists()
    assert builder.repo.status(untracked_files="no") == {}


def test_synced_commits_are_not_offered_again(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    builder.switch("release")
    assert runner.invoke(app, ["sync", source]).exit_code == 0

    result = runner.invoke(app, ["sync", source])
    assert result.exit_code == 0, result.output
    assert "nothing to sync" in result.output


def test_feature_filter_restricts_the_selection(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    extra_sha = builder.commit(
        "add search", files={"src/search/find.py": "def find():\n    return scan()\n"}
    )
    assert runner.invoke(app, ["annotate", extra_sha, "--feature", "search"]).exit_code == 0
    builder.switch("release")

    result = runner.invoke(app, ["sync", source, "-f", "search", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "add search" in result.output
    assert "add render" not in result.output

    result = runner.invoke(app, ["sync", source, "-f", "search"])
    assert result.exit_code == 0, result.output
    assert (builder.path / "src/search/find.py").exists()
    assert not (builder.path / "src/ui/render.py").exists()


def test_conflicting_cherry_pick_applies_nothing(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    builder.switch("release")
    builder.commit("competing render", files={"src/ui/render.py": "def render():\n    pass\n"})
    before = read_ref(builder.repo, "refs/heads/release")

    result = runner.invoke(app, ["sync", source])
    assert result.exit_code == 1
    assert "conflicts" in result.output
    assert "nothing was applied" in result.output
    assert read_ref(builder.repo, "refs/heads/release") == before


def test_sync_requires_a_clean_worktree(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    builder.switch("release")
    builder.write("src/core.py", "def core():\n    return 'dirty'\n")

    result = runner.invoke(app, ["sync", source])
    assert result.exit_code == 1
    assert "uncommitted changes" in result.output


def test_sync_refuses_a_variant_branch(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    builder = annotated_repo.builder
    builder.branch("variant/Fake")
    builder.switch("variant/Fake")
    result = runner.invoke(app, ["sync", builder.default_branch])
    assert result.exit_code == 1
    assert "variants are derived" in result.output
