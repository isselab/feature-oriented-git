"""Tests for `git feature list`."""

import json

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.conftest import AnnotatedRepo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_catalog_with_counts(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0, result.output
    assert "auth" in result.output
    assert "ui" in result.output
    assert "(auto)" in result.output  # both were auto-created by annotate


def test_json_output(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["--json", "list"])
    assert result.exit_code == 0, result.output
    rows = {row["name"]: row for row in json.loads(result.output)}
    assert rows["auth"]["annotations"] == 1
    assert rows["auth"]["changes"] == 1
    assert rows["auth"]["auto_created"] is True
    assert rows["ui"]["annotations"] == 1


def test_empty_catalog(
    runner: CliRunner,
    repo_builder,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = repo_builder("empty")
    builder.commit("base", files={"a.txt": "a\n"})
    monkeypatch.chdir(builder.path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0, result.output
    assert "no features defined yet" in result.output
