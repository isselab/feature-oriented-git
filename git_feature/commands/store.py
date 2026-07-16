"""`git feature store` — push, fetch, and merge the feature store with a remote."""

import json

import pygit2
import typer

from ..gitio import compare_and_swap_ref, read_ref, write_ref
from ..store import STORE_REF, GitRefStore, StoreMergeError, merge_stores, store_files_at
from .common import json_mode, require_repo, require_store


def incoming_ref(remote: str) -> str:
    """Where a remote's store commit is fetched to before merging."""
    return f"refs/feature/incoming/{remote}"


class _PushStatus(pygit2.RemoteCallbacks):
    """Collects per-ref rejection messages from a push."""

    def __init__(self) -> None:
        super().__init__()
        self.rejections: list[str] = []

    def push_update_reference(self, refname: str, message: str | None) -> None:
        if message is not None:
            self.rejections.append(f"{refname}: {message}")


def run_push(ctx: typer.Context, *, remote_name: str) -> None:
    repo = require_repo()
    require_store(repo)
    remote = _require_remote(repo, remote_name)

    status = _PushStatus()
    try:
        remote.push([f"{STORE_REF}:{STORE_REF}"], callbacks=status)
    except pygit2.GitError as exc:
        _push_rejected(remote_name, str(exc))
    if status.rejections:
        _push_rejected(remote_name, "; ".join(status.rejections))

    if json_mode(ctx):
        typer.echo(json.dumps({"remote": remote_name, "pushed": read_ref(repo, STORE_REF)}))
    else:
        typer.echo(f"pushed feature store to {remote_name}")


def run_fetch(ctx: typer.Context, *, remote_name: str) -> None:
    repo = require_repo()
    remote = _require_remote(repo, remote_name)

    try:
        remote.fetch([f"+{STORE_REF}:{incoming_ref(remote_name)}"])
    except pygit2.GitError as exc:
        typer.echo(f"error: fetch from {remote_name} failed ({exc})", err=True)
        raise typer.Exit(1) from None

    incoming = read_ref(repo, incoming_ref(remote_name))
    if incoming is None:
        typer.echo(f"error: {remote_name} has no feature store", err=True)
        raise typer.Exit(1)
    local = read_ref(repo, STORE_REF)

    if local is None:
        write_ref(repo, STORE_REF, incoming)
        _done(ctx, remote_name, incoming, "fetched", [])
        return
    if incoming == local:
        _done(ctx, remote_name, local, "up-to-date", [])
        return
    if _descends(repo, incoming, local):
        compare_and_swap_ref(repo, STORE_REF, incoming, expected_old=local)
        _done(ctx, remote_name, incoming, "fast-forwarded", [])
        return
    if _descends(repo, local, incoming):
        _done(ctx, remote_name, local, "ahead", [])
        return

    base_sha = repo.merge_base(local, incoming)
    base = store_files_at(repo, str(base_sha)) if base_sha else {}
    try:
        merged, notes = merge_stores(
            base, store_files_at(repo, local), store_files_at(repo, incoming)
        )
    except StoreMergeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    store = GitRefStore(repo)
    store.commit_merge(merged, f"merge feature store from {remote_name}", other_parent=incoming)
    _done(ctx, remote_name, store.tip or "", "merged", notes)


def _require_remote(repo: pygit2.Repository, name: str) -> pygit2.Remote:
    try:
        return repo.remotes[name]
    except (KeyError, ValueError):
        typer.echo(f"error: no remote named {name!r}", err=True)
        raise typer.Exit(1) from None


def _push_rejected(remote_name: str, detail: str) -> None:
    typer.echo(f"error: push to {remote_name} rejected ({detail})", err=True)
    typer.echo(
        f"the remote store has new commits — run 'git feature store fetch {remote_name}'"
        " (it merges automatically), then push again",
        err=True,
    )
    raise typer.Exit(1)


def _descends(repo: pygit2.Repository, descendant: str, ancestor: str) -> bool:
    try:
        return repo.descendant_of(descendant, ancestor)
    except (KeyError, pygit2.GitError):
        return False


def _done(ctx: typer.Context, remote_name: str, tip: str, outcome: str, notes: list[str]) -> None:
    if json_mode(ctx):
        typer.echo(
            json.dumps({"remote": remote_name, "outcome": outcome, "tip": tip, "notes": notes})
        )
        return
    messages = {
        "fetched": f"fetched feature store from {remote_name}",
        "up-to-date": "feature store already up to date",
        "fast-forwarded": f"fast-forwarded feature store to {remote_name}",
        "ahead": f"local feature store is ahead of {remote_name} — push when ready",
        "merged": f"merged feature store from {remote_name} — push to share the result",
    }
    typer.echo(messages[outcome])
    for note in notes:
        typer.echo(f"  ({note})")
