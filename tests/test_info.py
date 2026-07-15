"""Tests for `git feature info`."""

import json

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.conftest import AnnotatedRepo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_default_summary_shows_all_sections(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    result = runner.invoke(app, ["info", "auth"])
    assert result.exit_code == 0, result.output
    for section in ("files:", "commits:", "authors:", "branches:"):
        assert section in result.output
    assert "src/auth/login.py" in result.output
    assert "add login" in result.output


def test_files_flag_limits_output(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["info", "auth", "--files"])
    assert result.exit_code == 0, result.output
    assert "src/auth/login.py" in result.output
    assert "commits:" not in result.output


def test_branches_show_cross_branch_presence(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    # auth commit is on both branches; ui commit only on the default branch
    result = runner.invoke(app, ["--json", "info", "ui"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    branches = {row["name"]: row for row in payload["branches"]}
    default = annotated_repo.builder.default_branch
    assert branches[default]["present"] == 1
    assert branches["release"]["present"] == 0

    result = runner.invoke(app, ["--json", "info", "auth"])
    payload = json.loads(result.output)
    branches = {row["name"]: row for row in payload["branches"]}
    assert branches["release"]["present"] == 1


def test_missing_marker_in_text_output(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["info", "ui", "--branches"])
    assert result.exit_code == 0, result.output
    assert "[missing 1]" in result.output


def test_json_commits_carry_change_ids(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["--json", "info", "auth", "--commits"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    (commit,) = payload["commits"]
    assert commit["sha"] == annotated_repo.auth_sha
    assert commit["change_id"] == annotated_repo.auth_cid


def test_unknown_feature_fails(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["info", "nope"])
    assert result.exit_code == 1
