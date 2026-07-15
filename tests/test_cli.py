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
    "view",
    "putback",
    "sync",
    "reconcile",
    "doctor",
]

STUB_INVOCATIONS = [
    ["annotate"],
    ["list"],
    ["info", "auth"],
    ["status"],
    ["blame", "somefile.py"],
    ["whatfeature", "HEAD"],
    ["coverage"],
    ["model", "validate"],
    ["checkout", "minimal", "--dry-run"],
    ["variant", "list"],
    ["view", "minimal"],
    ["putback"],
    ["sync", "develop"],
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


@pytest.mark.parametrize("argv", STUB_INVOCATIONS, ids=lambda argv: " ".join(argv))
def test_stub_runs(runner: CliRunner, argv: list[str]) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert "not implemented yet" in result.output
