"""Tests for `git feature whatfeature`."""

import json

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.conftest import AnnotatedRepo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_annotated_commit_lists_its_features(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    result = runner.invoke(app, ["whatfeature", annotated_repo.auth_sha])
    assert result.exit_code == 0, result.output
    assert "auth" in result.output
    assert "src/auth/login.py" in result.output


def test_head_works_as_rev(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["whatfeature", "HEAD"])  # HEAD is the ui commit
    assert result.exit_code == 0, result.output
    assert "ui" in result.output


def test_unannotated_commit(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["whatfeature", annotated_repo.base_sha])
    assert result.exit_code == 0, result.output
    assert "no features recorded" in result.output


def test_json_output(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["--json", "whatfeature", annotated_repo.auth_sha])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["sha"] == annotated_repo.auth_sha
    assert payload["change_id"] == annotated_repo.auth_cid
    (annotation,) = payload["annotations"]
    assert annotation["presence"] == "auth"
