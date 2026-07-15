"""Tests for `git feature coverage`."""

import json

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.conftest import AnnotatedRepo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_counts_over_all_history(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    # 4 commits on the default branch: base, model.cfr, auth (annotated), ui (annotated)
    result = runner.invoke(app, ["coverage"])
    assert result.exit_code == 0, result.output
    assert "2/4 commits annotated (50%)" in result.output


def test_range_limits_commits(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["coverage", f"{annotated_repo.base_sha}..HEAD"])
    assert result.exit_code == 0, result.output
    assert "2/2 commits annotated (100%)" in result.output


def test_verbose_lists_each_commit(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["coverage", "--verbose"])
    assert result.exit_code == 0, result.output
    assert f"+ {annotated_repo.auth_sha[:12]}" in result.output
    assert f"- {annotated_repo.base_sha[:12]}" in result.output


def test_json_lists_unannotated_shas(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["--json", "coverage"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 4
    assert payload["annotated"] == 2
    assert annotated_repo.base_sha in payload["unannotated"]
    assert annotated_repo.auth_sha not in payload["unannotated"]
