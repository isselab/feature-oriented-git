"""Tests for `git feature status`."""

import json

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.conftest import AnnotatedRepo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_clean_tree(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "working tree clean" in result.output


def test_edit_inside_annotated_region_shows_feature(
    runner: CliRunner, annotated_repo: AnnotatedRepo
) -> None:
    annotated_repo.builder.write("src/auth/login.py", "def login():\n    return check_twice()\n")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "auth:" in result.output
    assert "src/auth/login.py" in result.output


def test_edit_elsewhere_is_unassigned(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    annotated_repo.builder.write("src/core.py", "def core():\n    return 'changed'\n")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "unassigned:" in result.output
    assert "src/core.py" in result.output
    assert "auth:" not in result.output


def test_staged_changes_are_included(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    builder = annotated_repo.builder
    builder.write("src/ui/render.py", "def render():\n    return draw_fast()\n")
    index = builder.repo.index
    index.add("src/ui/render.py")
    index.write()
    result = runner.invoke(app, ["--json", "status"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any("src/ui/render.py" in loc for loc in payload["features"].get("ui", []))
