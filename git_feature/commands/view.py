"""`git feature view` — check out a variant as an editable view."""

import json
from datetime import UTC, datetime

import pygit2
import typer

from ..domain.derivation.pipeline import DerivationError, configure, project
from ..domain.derivation.service import (
    ProjectionConflicts,
    VerificationFailed,
    materialize_variant,
    variant_ref,
)
from ..gitio import read_ref, worktree_diff
from ..store import GitRefStore
from ..store.types import ViewSession
from .common import json_mode, require_repo, require_store, switch_branch


def run(ctx: typer.Context, *, instance: str) -> None:
    repo = require_repo()
    store = require_store(repo)
    source_branch, base_rev, refreshing = _source(repo, store, instance)

    try:
        assignment, base_sha = configure(repo, instance, base_rev)
    except DerivationError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    projection = project(repo, store, instance, assignment, base_sha)

    try:
        derivation = materialize_variant(repo, store, projection, refresh=True)
    except ProjectionConflicts as exc:
        for conflict in exc.projection.conflicts:
            typer.echo(f"!! {conflict.kind}: {conflict.detail}", err=True)
        typer.echo(f"error: view of {instance} cannot be opened — resolve the conflicts", err=True)
        raise typer.Exit(1) from None
    except VerificationFailed as exc:
        for conflict in exc.conflicts:
            typer.echo(f"!! {conflict.kind}: {conflict.detail}", err=True)
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    session = ViewSession(
        instance=instance,
        source_branch=source_branch,
        base_commit=base_sha,
        variant_commit=derivation.sha,
        manifest=derivation.manifest,
        created_at=datetime.now(UTC),
    )
    store.write_view(session)
    store.commit(f"open view of variant {instance}")

    if json_mode(ctx):
        typer.echo(json.dumps(session.model_dump(mode="json", exclude={"manifest"})))
    else:
        typer.echo(
            f"view of {instance}: editing {derivation.sha[:12]}"
            f" (from {source_branch} @ {base_sha[:12]}) — put edits back with"
            " 'git feature putback'"
        )
    switch_branch(repo, variant_ref(instance), force=refreshing)


def _source(repo: pygit2.Repository, store: GitRefStore, instance: str) -> tuple[str, str, bool]:
    """The branch putback will target, the revision to derive from, and whether refreshing."""
    if repo.head_is_unborn:
        typer.echo("error: no commits yet", err=True)
        raise typer.Exit(1)
    if repo.head_is_detached:
        typer.echo("error: detached HEAD — check out the source branch first", err=True)
        raise typer.Exit(1)
    branch = repo.head.shorthand
    if not branch.startswith("variant/"):
        return branch, "HEAD", False

    # re-opening a view from its own branch refreshes it from the source's tip
    session = store.read_view(branch.removeprefix("variant/"))
    if branch != f"variant/{instance}" or session is None:
        typer.echo(f"error: on {branch} — switch to the source branch to open a view", err=True)
        raise typer.Exit(1)
    if worktree_diff(repo):
        typer.echo(
            "error: the view has uncommitted edits — put them back or discard them"
            " before refreshing",
            err=True,
        )
        raise typer.Exit(1)
    source_tip = read_ref(repo, f"refs/heads/{session.source_branch}")
    if source_tip is None:
        typer.echo(f"error: source branch {session.source_branch} no longer exists", err=True)
        raise typer.Exit(1)
    return session.source_branch, source_tip, True
