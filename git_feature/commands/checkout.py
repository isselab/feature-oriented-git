"""`git feature checkout` — check out a product variant derived from the feature model."""

import json
from collections import defaultdict

import pygit2
import typer

from ..domain.derivation.materialize import verify_tree
from ..domain.derivation.pipeline import DerivationError, Projection, configure, project
from ..domain.derivation.service import (
    VariantExists,
    VerificationFailed,
    materialize_variant,
    variant_ref,
)
from ..gitio import read_ref, resolve_commit
from ..store import GitRefStore
from .common import json_mode, require_repo, require_store, switch_branch


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
    repo = require_repo()
    store = require_store(repo)

    if verify_only:
        _verify_only(ctx, repo, store, instance)
        return

    try:
        assignment, base_sha = configure(repo, instance, base or _default_base(repo, store))
    except DerivationError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    projection = project(repo, store, instance, assignment, base_sha)

    if dry_run:
        _report(ctx, projection, dry_run=True)
        if projection.conflicts:
            raise typer.Exit(1)
        return

    if projection.conflicts:
        _report(ctx, projection, dry_run=False)
        raise typer.Exit(1)

    refname = variant_ref(instance)
    try:
        derivation = materialize_variant(repo, store, projection, refresh=refresh)
    except VariantExists:
        typer.echo(
            f"error: variant {instance} already exists — use --refresh to rebuild it",
            err=True,
        )
        raise typer.Exit(1) from None
    except VerificationFailed as exc:
        for conflict in exc.conflicts:
            typer.echo(f"!! {conflict.kind}: {conflict.detail}", err=True)
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    if derivation.up_to_date:
        typer.echo(f"variant {instance} is up to date at {derivation.sha[:12]}")
        if not no_switch:
            switch_branch(repo, refname)
        return

    if json_mode(ctx):
        payload = derivation.manifest.model_dump(mode="json")
        payload["variant_commit"] = derivation.sha
        typer.echo(json.dumps(payload))
    else:
        removed = len(projection.removed)
        typer.echo(
            f"variant {instance}: {refname} -> {derivation.sha[:12]}"
            f" ({removed} region(s) removed, verified)"
        )
    if not no_switch:
        switch_branch(repo, refname)


def _default_base(repo: pygit2.Repository, store: GitRefStore) -> str:
    """HEAD — unless HEAD is a variant branch, whose recorded base is the real source."""
    if not repo.head_is_unborn and repo.head.shorthand.startswith("variant/"):
        current = repo.head.shorthand.removeprefix("variant/")
        manifest = store.read_manifest(current)
        if manifest is not None:
            typer.echo(f"on {repo.head.shorthand}: deriving from its base commit")
            return manifest.base_commit
    return "HEAD"


def _verify_only(
    ctx: typer.Context, repo: pygit2.Repository, store: GitRefStore, instance: str
) -> None:
    manifest = store.read_manifest(instance)
    refname = variant_ref(instance)
    tip = read_ref(repo, refname)
    if manifest is None or tip is None:
        typer.echo(f"error: variant {instance} has never been derived", err=True)
        raise typer.Exit(1)
    tip_commit = resolve_commit(repo, tip)
    conflicts = verify_tree(repo, store, tip_commit, manifest.base_commit, manifest.decisions)
    if json_mode(ctx):
        typer.echo(
            json.dumps(
                {
                    "instance": instance,
                    "verified": not conflicts,
                    "problems": [c.detail for c in conflicts],
                }
            )
        )
    else:
        for conflict in conflicts:
            typer.echo(f"!! {conflict.detail}")
        typer.echo(
            f"variant {instance}: " + ("verified ok" if not conflicts else "verification FAILED")
        )
    if conflicts:
        raise typer.Exit(1)


def _report(ctx: typer.Context, projection: Projection, *, dry_run: bool) -> None:
    if json_mode(ctx):
        payload = projection.manifest().model_dump(mode="json")
        payload["conflicts"] = [
            {"kind": c.kind, "detail": c.detail, "path": c.path} for c in projection.conflicts
        ]
        typer.echo(json.dumps(payload))
        return
    label = "dry run" if dry_run else "plan"
    typer.echo(f"variant {projection.instance} from {projection.base_sha[:12]} ({label})")
    disabled = sorted(name for name, on in projection.assignment.items() if not on)
    typer.echo(f"disabled features: {', '.join(disabled) or '(none)'}")

    removals = defaultdict(list)
    for decision in projection.removed:
        removals[decision.anchor.path].append(decision)
    if removals:
        typer.echo("would remove:")
        for path in sorted(removals):
            for decision in removals[path]:
                runs = decision.runs()
                lines = (
                    ", ".join(f"lines {start}-{start + max(count, 1) - 1}" for start, count in runs)
                    if runs
                    else "unlocated"
                )
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
