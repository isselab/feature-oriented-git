"""Tests for `git feature model validate`."""

import json

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from tests.conftest import AnnotatedRepo

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

Full : Product {
    [ auth ]
    [ ui ]
}
"""


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def with_model(annotated_repo: AnnotatedRepo) -> AnnotatedRepo:
    annotated_repo.builder.commit("real feature model", files={"model.cfr": MODEL})
    return annotated_repo


def test_valid_model_and_annotations_pass(runner: CliRunner, with_model: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["model", "validate"])
    assert result.exit_code == 0, result.output
    assert "model ok" in result.output


def test_syntax_error_points_at_location(runner: CliRunner, with_model: AnnotatedRepo) -> None:
    with_model.builder.write("model.cfr", "abstract Product {\n    [ a.b ]\n}\n")
    result = runner.invoke(app, ["model", "validate"])
    assert result.exit_code == 1
    assert "line 2" in result.output


def test_annotation_referencing_unknown_feature_is_flagged(
    runner: CliRunner, with_model: AnnotatedRepo
) -> None:
    # the stored annotations say auth/ui; shrink the model so 'ui' disappears
    with_model.builder.write("model.cfr", "abstract Product {\n    core\n    auth ?\n}\n")
    result = runner.invoke(app, ["model", "validate"])
    assert result.exit_code == 1
    assert "ui" in result.output
    assert "unknown feature" in result.output


def test_constraint_referencing_unknown_feature_is_flagged(
    runner: CliRunner, with_model: AnnotatedRepo
) -> None:
    with_model.builder.write(
        "model.cfr",
        "abstract Product {\n    auth ?\n    ui ?\n    [ ghost => auth ]\n}\n",
    )
    result = runner.invoke(app, ["model", "validate"])
    assert result.exit_code == 1
    assert "ghost" in result.output


def test_legal_instance_reports_included_and_excluded(
    runner: CliRunner, with_model: AnnotatedRepo
) -> None:
    result = runner.invoke(app, ["--json", "model", "validate", "Full"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["valid"] is True
    assert payload["included"] == ["auth", "core", "ui"]
    assert payload["excluded"] == []
    assert payload["assignment"]["ui"] is True

    result = runner.invoke(app, ["model", "validate", "Minimal"])
    assert result.exit_code == 0, result.output
    assert "legal configuration" in result.output
    assert "excluded: auth, ui" in result.output


def test_illegal_instance_names_the_violated_constraint(
    runner: CliRunner, with_model: AnnotatedRepo
) -> None:
    broken = MODEL + "\nBroken : Product {\n    [ ui ]\n    [ no auth ]\n}\n"
    with_model.builder.write("model.cfr", broken)
    result = runner.invoke(app, ["model", "validate", "Broken"])
    assert result.exit_code == 1
    assert "illegal" in result.output


def test_unknown_instance_fails(runner: CliRunner, with_model: AnnotatedRepo) -> None:
    result = runner.invoke(app, ["model", "validate", "NoSuchInstance"])
    assert result.exit_code == 1
    assert "not found" in result.output
