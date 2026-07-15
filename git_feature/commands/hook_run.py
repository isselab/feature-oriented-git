"""`git feature hook-run` — internal entry point invoked by the installed git hooks."""

import sys

import pygit2
import typer

from ..gitio import open_repository, patch_id
from ..identity import ChangeIdMap
from ..store import GitRefStore


def run(ctx: typer.Context, *, hook: str) -> None:
    try:
        _dispatch(hook)
    except Exception as exc:  # hooks must never block the user's git command
        typer.echo(f"git-feature: {hook} hook skipped: {exc}", err=True)


def _dispatch(hook: str) -> None:
    repo = open_repository()
    store = GitRefStore(repo)
    if store.read_meta() is None:
        return
    cid_map = ChangeIdMap(store)
    if hook == "post-commit":
        _post_commit(repo, store, cid_map)
    elif hook == "post-rewrite":
        _post_rewrite(repo, store, cid_map)


def _post_commit(repo: pygit2.Repository, store: GitRefStore, cid_map: ChangeIdMap) -> None:
    sha = str(repo.head.target)
    _, minted = cid_map.get_or_mint(sha, patch_id=patch_id(repo, sha))
    if minted:
        store.commit(f"mint change-id for {sha[:12]}")


def _post_rewrite(repo: pygit2.Repository, store: GitRefStore, cid_map: ChangeIdMap) -> None:
    migrated = 0
    for line in sys.stdin:
        parts = line.split()
        if len(parts) < 2:
            continue
        old_sha, new_sha = parts[0], parts[1]
        if cid_map.migrate(old_sha, new_sha, patch_id=patch_id(repo, new_sha)):
            migrated += 1
    if migrated:
        store.commit(f"migrate {migrated} change-ids after rewrite")
