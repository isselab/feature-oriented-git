"""`git feature putback` — transplant edits from a variant view back to the source branch."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pygit2
import typer

from ..domain.derivation.pipeline import DerivationError, configure, project
from ..domain.derivation.putback import PutbackPlan, plan_putback
from ..domain.derivation.service import (
    ProjectionConflicts,
    VerificationFailed,
    materialize_variant,
    variant_ref,
)
from ..gitio import (
    blob_data,
    checkout_branch,
    compare_and_swap_ref,
    create_commit,
    diff_to_workdir,
    patch_id,
    read_ref,
    rewrite_tree,
)
from ..identity import ChangeIdMap
from ..store import GitRefStore
from ..store.types import ViewSession
from .common import json_mode, require_repo, require_store


def run(ctx: typer.Context, *, dry_run: bool, message: str | None) -> None:
    repo = require_repo()
    store = require_store(repo)
    session = _require_session(repo, store)

    source_ref = f"refs/heads/{session.source_branch}"
    source_tip = read_ref(repo, source_ref)
    if source_tip is None:
        typer.echo(f"error: source branch {session.source_branch} no longer exists", err=True)
        raise typer.Exit(1)
    if source_tip != session.base_commit:
        typer.echo(
            f"error: {session.source_branch} has moved since the view was opened —"
            f" re-open it with 'git feature view {session.instance}'",
            err=True,
        )
        raise typer.Exit(1)

    file_diffs = diff_to_workdir(repo, session.variant_commit)
    workdir = Path(repo.workdir) if repo.workdir else None
    if workdir is None:
        typer.echo("error: bare repository has no view to put back", err=True)
        raise typer.Exit(1)

    paths = [d.new_path or d.old_path for d in file_diffs]
    base_content = {p: blob_data(repo, session.base_commit, p) for p in paths if p}
    workdir_content = {
        p: (workdir / p).read_bytes() for p in paths if p and (workdir / p).is_file()
    }
    plan = plan_putback(session.manifest, file_diffs, base_content, workdir_content)

    if plan.conflicts:
        for conflict in plan.conflicts:
            typer.echo(f"!! {conflict.kind}: {conflict.detail}", err=True)
        typer.echo(f"error: {len(plan.conflicts)} conflict(s) — nothing was put back", err=True)
        raise typer.Exit(1)
    if not plan.replacements:
        typer.echo("view is unedited; nothing to put back")
        return
    if dry_run:
        _report(ctx, session, plan, dry_run=True)
        return

    tree = rewrite_tree(repo, session.base_commit, plan.replacements)
    text = message or f"apply edits from the {session.instance} view"
    sha = create_commit(repo, tree, text, [session.base_commit])
    compare_and_swap_ref(repo, source_ref, sha, expected_old=session.base_commit)
    ChangeIdMap(store).get_or_mint(sha, patch_id=patch_id(repo, sha))

    refreshed = _refresh_view(repo, store, session, sha)
    store.commit(f"put back edits from the {session.instance} view")

    if json_mode(ctx):
        typer.echo(
            json.dumps(
                {
                    "instance": session.instance,
                    "source_branch": session.source_branch,
                    "commit": sha,
                    "files": sorted(plan.replacements),
                    "view_refreshed": refreshed,
                }
            )
        )
        return
    typer.echo(
        f"{session.source_branch} -> {sha[:12]} ({len(plan.replacements)} file(s) transplanted)"
    )
    if refreshed:
        typer.echo(f"view of {session.instance} refreshed onto the new source commit")


def _require_session(repo: pygit2.Repository, store: GitRefStore) -> ViewSession:
    """The view session for the checked-out variant branch, or exit."""
    if repo.head_is_unborn or repo.head_is_detached:
        typer.echo("error: not on a view branch (open one with 'git feature view')", err=True)
        raise typer.Exit(1)
    branch = repo.head.shorthand
    if not branch.startswith("variant/"):
        typer.echo("error: not on a view branch (open one with 'git feature view')", err=True)
        raise typer.Exit(1)
    instance = branch.removeprefix("variant/")
    session = store.read_view(instance)
    if session is None:
        typer.echo(
            f"error: no view session for {instance} — open one with 'git feature view {instance}'",
            err=True,
        )
        raise typer.Exit(1)
    tip = read_ref(repo, variant_ref(instance))
    if tip != session.variant_commit and not _descends(repo, tip, session.variant_commit):
        typer.echo(
            f"error: variant/{instance} no longer matches the view session —"
            f" re-open it with 'git feature view {instance}'",
            err=True,
        )
        raise typer.Exit(1)
    return session


def _descends(repo: pygit2.Repository, tip: str | None, ancestor: str) -> bool:
    if tip is None:
        return False
    try:
        return repo.descendant_of(tip, ancestor)
    except (KeyError, pygit2.GitError):
        return False


def _refresh_view(
    repo: pygit2.Repository, store: GitRefStore, session: ViewSession, new_base: str
) -> bool:
    """Re-derive the view from the just-created source commit; never fails the putback."""
    instance = session.instance
    try:
        assignment, base_sha = configure(repo, instance, new_base)
        projection = project(repo, store, instance, assignment, base_sha)
        derivation = materialize_variant(repo, store, projection, refresh=True)
    except (DerivationError, ProjectionConflicts, VerificationFailed) as exc:
        typer.echo(
            f"warning: view not refreshed ({exc}) — re-open it with 'git feature view {instance}'",
            err=True,
        )
        return False
    store.write_view(
        session.model_copy(
            update={
                "base_commit": base_sha,
                "variant_commit": derivation.sha,
                "manifest": derivation.manifest,
                "created_at": datetime.now(UTC),
            }
        )
    )
    try:
        checkout_branch(repo, variant_ref(instance), force=True)
    except pygit2.GitError as exc:
        typer.echo(f"warning: could not sync the view worktree ({exc})", err=True)
    return True


def _report(ctx: typer.Context, session: ViewSession, plan: PutbackPlan, *, dry_run: bool) -> None:
    if json_mode(ctx):
        typer.echo(
            json.dumps(
                {
                    "instance": session.instance,
                    "source_branch": session.source_branch,
                    "dry_run": dry_run,
                    "files": sorted(plan.replacements),
                    "edits": [
                        {
                            "path": e.path,
                            "view_span": list(e.view_span),
                            "source_span": list(e.source_span),
                        }
                        for e in plan.edits
                    ],
                }
            )
        )
        return
    typer.echo(f"would apply to {session.source_branch} @ {session.base_commit[:12]}:")
    for edit in plan.edits:
        typer.echo(
            f"  {edit.path}: view lines {_span_text(edit.view_span)}"
            f" -> source lines {_span_text(edit.source_span)}"
        )
    for path in plan.additions:
        typer.echo(f"  {path}: new file")


def _span_text(span: tuple[int, int]) -> str:
    start, count = span
    if count == 0:
        return f"{start} (insertion)"
    return f"{start}-{start + count - 1}" if count > 1 else str(start)
