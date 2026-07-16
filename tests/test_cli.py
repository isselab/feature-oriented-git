"""Smoke tests for the CLI scaffolding: every command exists and runs its stub."""

import pytest
from typer.testing import CliRunner

from git_feature.cli import app

EXPECTED_COMMANDS = [
    "init",
    "annotate",
    "list",
    "info",
    "status",
    "blame",
    "whatfeature",
    "coverage",
    "model",
    "checkout",
    "variant",
    "store",
    "view",
    "putback",
    "sync",
    "reconcile",
    "doctor",
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_help_lists_all_commands(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in EXPECTED_COMMANDS:
        assert name in result.output, f"command {name!r} missing from --help"


def test_hook_run_is_hidden(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "hook-run" not in result.output
