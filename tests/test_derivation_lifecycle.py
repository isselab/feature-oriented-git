"""One journey end to end: init → annotate → model → checkout → verify → idempotent redo."""

from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.fixtures import RepoBuilder
from tests.test_checkout_dryrun import BASE, MODEL, WITH_AUTH, WITH_BOTH


def test_derivation_lifecycle(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    builder = repo_builder("repo")
    builder.commit("base", files={"model.cfr": MODEL, "shared.py": BASE})
    source_branch = builder.default_branch
    monkeypatch.chdir(builder.path)

    assert runner.invoke(app, ["init"]).exit_code == 0
    auth_sha = builder.commit("auth block", files={"shared.py": WITH_AUTH})
    ui_sha = builder.commit("ui block", files={"shared.py": WITH_BOTH})
    assert runner.invoke(app, ["annotate", auth_sha, "--feature", "auth"]).exit_code == 0
    assert runner.invoke(app, ["annotate", ui_sha, "--feature", "ui"]).exit_code == 0
    assert runner.invoke(app, ["model", "validate"]).exit_code == 0

    # derive and switch: the working tree becomes the reduced product
    result = runner.invoke(app, ["checkout", "AuthOnly"])
    assert result.exit_code == 0, result.output
    assert builder.repo.head.shorthand == "variant/AuthOnly"
    assert (builder.path / "shared.py").read_text() == WITH_AUTH

    # the derivation is verified and re-verifiable
    result = runner.invoke(app, ["checkout", "AuthOnly", "--verify-only"])
    assert result.exit_code == 0, result.output

    # re-deriving at the same base changes nothing
    result = runner.invoke(app, ["checkout", "AuthOnly", "--no-switch"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output

    # back on the source branch everything is still intact
    builder.switch(source_branch)
    assert (builder.path / "shared.py").read_text() == WITH_BOTH
    result = runner.invoke(app, ["variant", "list"])
    assert result.exit_code == 0, result.output
    assert "AuthOnly" in result.output and "[current]" in result.output
