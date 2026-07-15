"""`git feature checkout` — check out a product variant derived from the feature model."""

import json
from collections import defaultdict

import typer

from ..domain.derivation.pipeline import DerivationError, Projection, configure, project
from .common import json_mode, require_repo, require_store


def run(
    ctx: typer.Context,
    *,
    instance: str,
    dry_run: bool,
    refresh: bool,
    base: str | None,
    no_switch: bool,
    verify_only: bool,
) -> None:
    if not dry_run:
        typer.echo(
            "materialization is not implemented yet — use 'checkout --dry-run' to plan",
            err=True,
        )
        raise typer.Exit(1)

    repo = require_repo()
    store = require_store(repo)
    try:
        assignment, base_sha = configure(repo, instance, base or "HEAD")
    except DerivationError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    projection = project(repo, store, instance, assignment, base_sha)

    if json_mode(ctx):
        payload = projection.manifest().model_dump(mode="json")
        payload["conflicts"] = [
            {"kind": c.kind, "detail": c.detail, "path": c.path} for c in projection.conflicts
        ]
        typer.echo(json.dumps(payload))
    else:
        _print_report(projection)
    if projection.conflicts:
        raise typer.Exit(1)


def _print_report(projection: Projection) -> None:
    disabled = sorted(name for name, on in projection.assignment.items() if not on)
    typer.echo(f"variant {projection.instance} from {projection.base_sha[:12]} (dry run)")
    typer.echo(f"disabled features: {', '.join(disabled) or '(none)'}")

    removals = defaultdict(list)
    for decision in projection.removed:
        removals[decision.anchor.path].append(decision)
    if removals:
        typer.echo("would remove:")
        for path in sorted(removals):
            for decision in removals[path]:
                span = decision.resolved_span
                lines = f"lines {span[0]}-{span[0] + max(span[1], 1) - 1}" if span else "unlocated"
                typer.echo(f"  {path}: {lines}  [{decision.presence}] ({decision.confidence})")
    else:
        typer.echo("would remove: nothing")
    kept = len(projection.decisions) - len(projection.removed)
    typer.echo(f"kept regions: {kept}")

    for conflict in projection.conflicts:
        typer.echo(f"!! {conflict.kind}: {conflict.detail}")
    if projection.conflicts:
        typer.echo(f"{len(projection.conflicts)} conflict(s) — variant cannot be materialized")
    else:
        typer.echo("no conflicts")
