"""`git feature sync` — propagate a feature's commits between branches."""

import json
from dataclasses import dataclass

import pygit2
import typer

from ..domain.query.catalog import presence_features
from ..gitio import (
    checkout_branch,
    cherrypick_tree,
    compare_and_swap_ref,
    create_commit,
    iter_commits,
    patch_id,
    resolve_commit,
    worktree_diff,
)
from ..identity import ChangeIdMap
from ..store import GitRefStore
from .common import json_mode, require_repo, require_store


@dataclass
class Candidate:
    """One commit missing from the target branch and eligible for propagation."""

    commit: pygit2.Commit
    change_id: str | None
    features: list[str]

    @property
    def sha(self) -> str:
        return str(self.commit.id)

    @property
    def subject(self) -> str:
        return self.commit.message.splitlines()[0] if self.commit.message else ""


def run(ctx: typer.Context, *, source: str, feature: str | None, dry_run: bool) -> None:
    repo = require_repo()
    store = require_store(repo)

    if repo.head_is_unborn or repo.head_is_detached:
        typer.echo("error: check out the branch to sync onto first", err=True)
        raise typer.Exit(1)
    target_branch = repo.head.shorthand
    if target_branch.startswith("variant/"):
        typer.echo("error: variants are derived, not synced — switch to a source branch", err=True)
        raise typer.Exit(1)
    try:
        resolve_commit(repo, source)
    except (KeyError, pygit2.GitError):
        typer.echo(f"error: unknown revision {source!r}", err=True)
        raise typer.Exit(1) from None

    cid_map = ChangeIdMap(store)
    sha_to_cid = {record.sha: record.change_id for record in cid_map.iter_records()}
    candidates, skipped = _plan(repo, store, source, feature, sha_to_cid)

    if not candidates:
        typer.echo(
            f"nothing to sync from {source}" + (f" for feature {feature}" if feature else "")
        )
        for note in skipped:
            typer.echo(f"  ({note})")
        return

    if dry_run:
        _report(ctx, candidates, skipped, source, target_branch, applied=None)
        return

    if worktree_diff(repo):
        typer.echo("error: uncommitted changes — commit or stash them before syncing", err=True)
        raise typer.Exit(1)

    old_tip = str(repo.head.target)
    tip = old_tip
    applied: list[tuple[Candidate, str]] = []
    for candidate in candidates:
        tree = cherrypick_tree(repo, candidate.commit, tip)
        if tree is None:
            typer.echo(
                f"error: cherry-pick of {candidate.sha[:12]} ({candidate.subject})"
                f" conflicts — nothing was applied",
                err=True,
            )
            raise typer.Exit(1)
        if tree == resolve_commit(repo, tip).tree.id:
            skipped.append(f"{candidate.sha[:12]} adds no changes on {target_branch}, skipped")
            continue
        new_sha = create_commit(
            repo, tree, candidate.commit.message, [tip], author=candidate.commit.author
        )
        origin, _ = cid_map.get_or_mint(candidate.sha, patch_id=patch_id(repo, candidate.commit))
        cid_map.insert(new_sha, change_id=origin.change_id, patch_id=patch_id(repo, new_sha))
        applied.append((candidate, new_sha))
        tip = new_sha

    if not applied:
        typer.echo(f"nothing to sync from {source}")
        for note in skipped:
            typer.echo(f"  ({note})")
        return

    refname = f"refs/heads/{target_branch}"
    compare_and_swap_ref(repo, refname, tip, expected_old=old_tip)
    checkout_branch(repo, refname, force=True)
    store.commit(f"sync {len(applied)} commit(s) from {source}")
    _report(ctx, candidates, skipped, source, target_branch, applied=applied)


def _plan(
    repo: pygit2.Repository,
    store: GitRefStore,
    source: str,
    feature: str | None,
    sha_to_cid: dict[str, str],
) -> tuple[list[Candidate], list[str]]:
    """Commits reachable from source but absent (by change-id) from the target, oldest first."""
    target_cids = {
        cid for commit in iter_commits(repo) if (cid := sha_to_cid.get(str(commit.id))) is not None
    }
    candidates = []
    skipped = []
    for commit in reversed(list(iter_commits(repo, source, exclude=["HEAD"]))):
        if len(commit.parents) > 1:
            skipped.append(f"{str(commit.id)[:12]} is a merge commit, skipped")
            continue
        change_id = sha_to_cid.get(str(commit.id))
        if change_id is not None and change_id in target_cids:
            continue  # another incarnation of this change is already on the target
        annotations = store.read_annotations(change_id) if change_id else []
        features = sorted({f for a in annotations for f in presence_features(a.presence)})
        if feature is not None and feature not in features:
            continue
        candidates.append(Candidate(commit=commit, change_id=change_id, features=features))
    return candidates, skipped


def _report(
    ctx: typer.Context,
    candidates: list[Candidate],
    skipped: list[str],
    source: str,
    target_branch: str,
    applied: list[tuple[Candidate, str]] | None,
) -> None:
    if json_mode(ctx):
        new_shas = {candidate.sha: new_sha for candidate, new_sha in applied or []}
        typer.echo(
            json.dumps(
                {
                    "source": source,
                    "target": target_branch,
                    "dry_run": applied is None,
                    "commits": [
                        {
                            "sha": c.sha,
                            "new_sha": new_shas.get(c.sha),
                            "change_id": c.change_id,
                            "features": c.features,
                            "subject": c.subject,
                        }
                        for c in candidates
                        if applied is None or c.sha in new_shas
                    ],
                    "notes": skipped,
                }
            )
        )
        return
    if applied is None:
        typer.echo(f"would sync from {source} onto {target_branch}:")
        for candidate in candidates:
            features = f"  [{', '.join(candidate.features)}]" if candidate.features else ""
            typer.echo(f"  {candidate.sha[:12]} {candidate.subject}{features}")
    else:
        for candidate, new_sha in applied:
            features = f"  [{', '.join(candidate.features)}]" if candidate.features else ""
            typer.echo(
                f"synced {candidate.sha[:12]} -> {new_sha[:12]} {candidate.subject}{features}"
            )
        typer.echo(f"{target_branch}: {len(applied)} commit(s) from {source}")
    for note in skipped:
        typer.echo(f"  ({note})")
