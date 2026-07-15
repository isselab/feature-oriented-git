"""Tests for `git feature variant list`."""

import json
from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.fixtures import RepoBuilder
from tests.test_checkout_dryrun import BASE, MODEL, WITH_AUTH, WITH_BOTH


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def builder(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> RepoBuilder:
    builder = repo_builder("repo")
    builder.commit("base", files={"model.cfr": MODEL, "shared.py": BASE})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    auth_sha = builder.commit("auth block", files={"shared.py": WITH_AUTH})
    ui_sha = builder.commit("ui block", files={"shared.py": WITH_BOTH})
    assert runner.invoke(app, ["annotate", auth_sha, "--feature", "auth"]).exit_code == 0
    assert runner.invoke(app, ["annotate", ui_sha, "--feature", "ui"]).exit_code == 0
    return builder


def test_empty_when_nothing_derived(runner: CliRunner, builder: RepoBuilder) -> None:
    result = runner.invoke(app, ["variant", "list"])
    assert result.exit_code == 0, result.output
    assert "no variants derived yet" in result.output


def test_lists_variants_with_base_and_disabled(runner: CliRunner, builder: RepoBuilder) -> None:
    assert runner.invoke(app, ["checkout", "Minimal", "--no-switch"]).exit_code == 0
    assert runner.invoke(app, ["checkout", "AuthOnly", "--no-switch"]).exit_code == 0
    result = runner.invoke(app, ["--json", "variant", "list"])
    assert result.exit_code == 0, result.output
    rows = {row["name"]: row for row in json.loads(result.output)}
    assert rows["Minimal"]["disabled"] == ["auth", "ui"]
    assert rows["AuthOnly"]["disabled"] == ["ui"]
    assert rows["Minimal"]["branch"] == "variant/Minimal"
    assert rows["Minimal"]["base_commit"] == str(builder.repo.head.target)
    assert rows["Minimal"]["stale"] is False


def test_staleness_flips_when_source_advances(runner: CliRunner, builder: RepoBuilder) -> None:
    assert runner.invoke(app, ["checkout", "Minimal", "--no-switch"]).exit_code == 0
    builder.commit("moved on", files={"new.txt": "n\n"})
    result = runner.invoke(app, ["variant", "list"])
    assert result.exit_code == 0, result.output
    assert "[stale]" in result.output
