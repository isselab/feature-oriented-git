"""Tests for `git feature checkout --dry-run` (configure + project stages)."""

import json
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.fixtures import RepoBuilder

MODEL = """\
abstract Product {
    core
    auth ?
    ui ?

    [ ui => auth ]
}

Minimal : Product {
    [ no auth ]
    [ no ui ]
}

AuthOnly : Product {
    [ auth ]
    [ no ui ]
}

Full : Product {
    [ auth ]
    [ ui ]
}
"""

BASE = "def core():\n    return 1\n"
WITH_AUTH = BASE + "\n\ndef auth():\n    return check()\n"
WITH_BOTH = WITH_AUTH + "\n\ndef ui():\n    return render()\n"


@dataclass
class DryRunRepo:
    builder: RepoBuilder
    base_sha: str
    auth_sha: str
    ui_sha: str


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fixture(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> DryRunRepo:
    builder = repo_builder("repo")
    base_sha = builder.commit("base", files={"model.cfr": MODEL, "shared.py": BASE})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    auth_sha = builder.commit("auth block", files={"shared.py": WITH_AUTH})
    ui_sha = builder.commit("ui block", files={"shared.py": WITH_BOTH})
    assert runner.invoke(app, ["annotate", auth_sha, "--feature", "auth"]).exit_code == 0
    assert runner.invoke(app, ["annotate", ui_sha, "--feature", "ui"]).exit_code == 0
    return DryRunRepo(builder, base_sha, auth_sha, ui_sha)


def _removed_spans(output: str) -> dict[str, list[tuple[list[int], str]]]:
    payload = json.loads(output)
    removed: dict[str, list[tuple[list[int], str]]] = {}
    for decision in payload["decisions"]:
        if not decision["included"]:
            removed.setdefault(decision["anchor"]["path"], []).append(
                (decision["resolved_span"], decision["presence"])
            )
    return removed


def test_minimal_removes_both_regions(runner: CliRunner, fixture: DryRunRepo) -> None:
    result = runner.invoke(app, ["--json", "checkout", "Minimal", "--dry-run"])
    assert result.exit_code == 0, result.output
    removed = _removed_spans(result.output)
    spans = sorted(removed["shared.py"])
    # each block is two blank separator lines + two code lines
    assert spans == [([3, 4], "auth"), ([7, 4], "ui")]


def test_authonly_removes_only_ui(runner: CliRunner, fixture: DryRunRepo) -> None:
    result = runner.invoke(app, ["--json", "checkout", "AuthOnly", "--dry-run"])
    assert result.exit_code == 0, result.output
    removed = _removed_spans(result.output)
    assert removed == {"shared.py": [([7, 4], "ui")]}


def test_full_removes_nothing(runner: CliRunner, fixture: DryRunRepo) -> None:
    result = runner.invoke(app, ["checkout", "Full", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "would remove: nothing" in result.output
    assert "no conflicts" in result.output


def test_illegal_instance_fails_before_touching_regions(
    runner: CliRunner, fixture: DryRunRepo
) -> None:
    broken = MODEL + "\nBroken : Product {\n    [ ui ]\n    [ no auth ]\n}\n"
    fixture.builder.commit("broken instance", files={"model.cfr": broken})
    result = runner.invoke(app, ["checkout", "Broken", "--dry-run"])
    assert result.exit_code == 1
    assert "illegal" in result.output


def test_base_uses_that_commits_model_and_history(runner: CliRunner, fixture: DryRunRepo) -> None:
    # at the auth commit, the ui change doesn't exist yet: nothing to remove for AuthOnly
    result = runner.invoke(
        app, ["--json", "checkout", "AuthOnly", "--dry-run", "--base", fixture.auth_sha]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["base_commit"] == fixture.auth_sha
    assert _removed_spans(result.output) == {}
    assert [d["presence"] for d in payload["decisions"]] == ["auth"]


def test_planted_overlap_is_a_conflict(runner: CliRunner, fixture: DryRunRepo) -> None:
    # a second annotation claims part of the ui block for 'core' (always on):
    # under AuthOnly the same lines would be both kept and removed
    result = runner.invoke(
        app, ["annotate", fixture.ui_sha, "--feature", "core", "--path", "shared.py"]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["checkout", "AuthOnly", "--dry-run"])
    assert result.exit_code == 1, result.output
    assert "overlap" in result.output
    assert "cannot be materialized" in result.output


def test_missing_model_at_base_fails(runner: CliRunner, fixture: DryRunRepo) -> None:
    # rewrite model.cfr away in a new commit; --base HEAD then has no model
    fixture.builder.commit("drop model", remove=["model.cfr"])
    result = runner.invoke(app, ["checkout", "Minimal", "--dry-run"])
    assert result.exit_code == 1
    assert "no model.cfr" in result.output


def test_conflicts_block_materialization_too(runner: CliRunner, fixture: DryRunRepo) -> None:
    result = runner.invoke(
        app, ["annotate", fixture.ui_sha, "--feature", "core", "--path", "shared.py"]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["checkout", "AuthOnly", "--no-switch"])
    assert result.exit_code == 1
    assert "cannot be materialized" in result.output
    assert "refs/heads/variant/AuthOnly" not in fixture.builder.repo.references
