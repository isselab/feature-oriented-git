"""Tests for `git feature blame`."""

import json

import pytest
from typer.testing import CliRunner

import git_feature.identity.region as region_module
from git_feature.cli import app
from tests.conftest import AnnotatedRepo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_per_line_conditions(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["--json", "blame", "src/auth/login.py"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [row["presence"] for row in rows] == ["auth", "auth"]
    assert rows[0]["content"] == "def login():"


def test_unannotated_lines_show_dash(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["blame", "src/core.py"])
    assert result.exit_code == 0, result.output
    for line in result.output.strip().splitlines():
        assert "  -  " in line


def test_line_filter(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["--json", "blame", "src/auth/login.py", "--line", "2"])
    assert result.exit_code == 0, result.output
    (row,) = json.loads(result.output)
    assert row["line"] == 2
    assert row["presence"] == "auth"


def test_missing_file_fails(runner: CliRunner, annotated_repo: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["blame", "nope.py"])
    assert result.exit_code == 1


def test_single_blame_pass_per_file(
    runner: CliRunner,
    annotated_repo: AnnotatedRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # two annotations on the same file must share one blame pass
    builder = annotated_repo.builder
    builder.write(
        "src/auth/login.py",
        "def login():\n    return check()\n\ndef logout():\n    return clear()\n",
    )
    builder.commit("extend auth")
    assert runner.invoke(app, ["annotate", "--feature", "auth-extra"]).exit_code == 0

    calls = {"n": 0}
    original = region_module.line_origins

    def counting(repo: object, rev: object, path: str) -> object:
        calls["n"] += 1
        return original(repo, rev, path)  # type: ignore[arg-type]

    monkeypatch.setattr(region_module, "line_origins", counting)
    result = runner.invoke(app, ["blame", "src/auth/login.py"])
    assert result.exit_code == 0, result.output
    assert calls["n"] == 1
