"""Tests for `git feature log-diff`: change-id-aware comparison between branches."""

import json

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.conftest import AnnotatedRepo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_lists_commits_on_target_missing_from_head(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    builder.switch("release")

    result = runner.invoke(app, ["log-diff", source])
    assert result.exit_code == 0, result.output
    assert "add render" in result.output
    assert "add login" not in result.output  # already on release (same sha)


def test_no_commits_missing_reports_nothing(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch

    result = runner.invoke(app, ["log-diff", source])
    assert result.exit_code == 0, result.output
    assert "no commits" in result.output


def test_cherry_picked_commit_is_matched_by_change_id_despite_new_hash(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    builder.switch("release")
    assert runner.invoke(app, ["sync", source]).exit_code == 0  # cherry-picks "add render"

    result = runner.invoke(app, ["log-diff", source])
    assert result.exit_code == 0, result.output
    assert "add render" not in result.output
    assert "no commits" in result.output


def test_unknown_revision_errors(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["log-diff", "not-a-real-branch"])
    assert result.exit_code == 1
    assert "unknown revision" in result.output


def test_json_output_includes_change_id(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    builder = annotated_repo.builder
    source = builder.default_branch
    builder.switch("release")

    result = runner.invoke(app, ["--json", "log-diff", source])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["target"] == source
    [entry] = payload["commits"]
    assert entry["sha"] == annotated_repo.ui_sha
    assert entry["change_id"] == annotated_repo.ui_cid
    assert entry["subject"] == "add render"
