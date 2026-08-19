"""`git feature log-diff` — commits on target missing from HEAD, by change-id."""

import json
from dataclasses import dataclass

import pygit2
import typer

from ..gitio import iter_commits, resolve_commit
from ..identity import ChangeIdMap
from .common import json_mode, require_repo, require_store


@dataclass
class Entry:
    """A commit reachable from target but absent (by change-id) from HEAD."""

    commit: pygit2.Commit
    change_id: str | None

    @property
    def sha(self) -> str:
        return str(self.commit.id)

    @property
    def subject(self) -> str:
        return self.commit.message.splitlines()[0] if self.commit.message else ""


def run(ctx: typer.Context, *, target: str) -> None:
    repo = require_repo()
    store = require_store(repo)

    try:
        resolve_commit(repo, target)
    except (KeyError, pygit2.GitError):
        typer.echo(f"error: unknown revision {target!r}", err=True)
        raise typer.Exit(1) from None

    sha_to_cid = {record.sha: record.change_id for record in ChangeIdMap(store).iter_records()}
    head_shas = {str(commit.id) for commit in iter_commits(repo, "HEAD")}
    head_cids = {cid for sha in head_shas if (cid := sha_to_cid.get(sha)) is not None}

    missing = []
    for commit in iter_commits(repo, target):
        sha = str(commit.id)
        if sha in head_shas:
            continue
        change_id = sha_to_cid.get(sha)
        if change_id is not None and change_id in head_cids:
            continue  # another incarnation of this change (e.g. cherry-pick) is on HEAD
        missing.append(Entry(commit=commit, change_id=change_id))

    _report(ctx, target, missing)


def _report(ctx: typer.Context, target: str, missing: list[Entry]) -> None:
    if json_mode(ctx):
        typer.echo(
            json.dumps(
                {
                    "target": target,
                    "commits": [
                        {"sha": e.sha, "change_id": e.change_id, "subject": e.subject}
                        for e in missing
                    ],
                }
            )
        )
        return

    if not missing:
        typer.echo(f"no commits on {target} missing from HEAD")
        return
    for entry in missing:
        typer.echo(f"{entry.sha[:12]} {entry.subject}")
