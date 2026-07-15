"""`git feature annotate` — associate diff hunks with features."""

import json

import typer

from ..domain.annotate.capture import (
    CaptureResult,
    annotate_commit,
    ensure_features,
    signature_name,
)
from ..gitio import iter_range
from .common import json_mode, require_repo, require_store


def run(
    ctx: typer.Context,
    *,
    rev: str | None,
    features: tuple[str, ...],
    presence: str | None,
    paths: tuple[str, ...],
    rev_range: str | None,
) -> None:
    if features and presence:
        typer.echo("error: use either --feature or --presence, not both", err=True)
        raise typer.Exit(2)
    if rev and rev_range:
        typer.echo("error: use either a rev argument or --range, not both", err=True)
        raise typer.Exit(2)
    if not features and not presence:
        typer.echo("error: pass --feature or --presence", err=True)
        raise typer.Exit(2)

    repo = require_repo()
    store = require_store(repo)
    presences = [presence] if presence else list(features)
    result = CaptureResult()
    ensure_features(store, list(features), result)
    author = signature_name(repo)
    revs = list(iter_range(repo, rev_range)) if rev_range else [rev or "HEAD"]
    for commit in revs:
        annotate_commit(repo, store, commit, presences, paths, author, result)

    if result.written or result.created_features:
        store.commit(f"annotate {result.written} regions")
    _report(ctx, result)


def _report(ctx: typer.Context, result: CaptureResult) -> None:
    if json_mode(ctx):
        typer.echo(
            json.dumps(
                {
                    "written": result.written,
                    "duplicates": result.duplicates,
                    "annotated_commits": result.annotated_commits,
                    "minted_change_ids": result.minted_change_ids,
                    "created_features": result.created_features,
                }
            )
        )
        return
    typer.echo(
        f"annotated {result.written} region(s) across {result.annotated_commits} commit(s)"
        + (f", {result.duplicates} duplicate(s) skipped" if result.duplicates else "")
    )
    if result.minted_change_ids:
        typer.echo(f"minted {result.minted_change_ids} change-id(s) for older commits")
    for name in result.created_features:
        typer.echo(f"created feature '{name}' (auto)")
