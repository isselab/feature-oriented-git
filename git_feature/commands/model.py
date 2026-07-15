"""`git feature model validate` — validate the feature model and configurations."""

import json

import pygit2
import typer

from ..domain.query.catalog import iter_annotations
from ..domain.variability import (
    ConfigurationError,
    Evaluator,
    ModelError,
    ModelParseError,
    Module,
    model_text,
    parse_model,
)
from ..domain.variability.lint import lint_module, model_feature_names
from ..domain.variability.presence import lint_presence
from ..store import GitRefStore
from .common import json_mode, require_repo


def run(ctx: typer.Context, *, instance: str | None) -> None:
    repo = require_repo()
    text = model_text(repo)
    if text is None:
        typer.echo("error: no model.cfr found (run 'git feature init')", err=True)
        raise typer.Exit(1)
    try:
        module = parse_model(text)
    except ModelParseError as exc:
        typer.echo(f"error: model.cfr: {exc}", err=True)
        raise typer.Exit(1) from None

    if instance is not None:
        _validate_instance(ctx, module, instance)
        return

    problems = lint_module(module)
    problems.extend(_lint_annotations(repo, module))
    if json_mode(ctx):
        typer.echo(json.dumps({"valid": not problems, "problems": problems}))
    else:
        for problem in problems:
            typer.echo(f"!! {problem}")
        typer.echo("model ok" if not problems else f"{len(problems)} problem(s) found")
    if problems:
        raise typer.Exit(1)


def _validate_instance(ctx: typer.Context, module: Module, instance: str) -> None:
    evaluator = Evaluator(module)
    try:
        config = evaluator.resolve_instance(instance)
        assignment = evaluator.resolve_assignment(instance)
    except (ModelError, ConfigurationError) as exc:
        if json_mode(ctx):
            typer.echo(json.dumps({"instance": instance, "valid": False, "error": str(exc)}))
        else:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    if json_mode(ctx):
        typer.echo(
            json.dumps(
                {
                    "instance": instance,
                    "valid": True,
                    "included": sorted(config.included),
                    "excluded": sorted(config.excluded),
                    "assignment": assignment,
                }
            )
        )
        return
    typer.echo(f"instance {instance}: legal configuration")
    typer.echo(f"  included: {', '.join(sorted(config.included)) or '(none)'}")
    typer.echo(f"  excluded: {', '.join(sorted(config.excluded)) or '(none)'}")


def _lint_annotations(repo: pygit2.Repository, module: Module) -> list[str]:
    store = GitRefStore(repo)
    if store.read_meta() is None:
        return []  # store not initialized: nothing to cross-check
    known = model_feature_names(module)
    problems = []
    for change_id, annotation in iter_annotations(store):
        for problem in lint_presence(annotation.presence, known):
            problems.append(f"annotation on change {change_id[:8]}…: {problem}")
    return problems
