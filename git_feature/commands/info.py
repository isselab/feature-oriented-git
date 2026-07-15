"""`git feature info` — a feature's files, commits, authors, and branches."""

import json

import pygit2
import typer

from ..domain.query.catalog import feature_annotations
from ..gitio import iter_all_commits
from ..identity import ChangeIdMap
from ..store import GitRefStore
from .common import json_mode, require_repo, require_store


def run(
    ctx: typer.Context,
    *,
    name: str,
    files: bool,
    commits: bool,
    authors: bool,
    branches: bool,
) -> None:
    repo = require_repo()
    store = require_store(repo)

    pairs = feature_annotations(store, name)
    if not pairs and store.read_feature(name) is None:
        typer.echo(f"error: unknown feature '{name}'", err=True)
        raise typer.Exit(1)

    change_ids = sorted({change_id for change_id, _ in pairs})
    file_list = sorted({annotation.anchor.path for _, annotation in pairs})
    commit_rows, author_list = _commits_and_authors(repo, store, change_ids)
    branch_rows = _branches(repo, store, change_ids)

    show_all = not (files or commits or authors or branches)
    payload: dict[str, object] = {"name": name, "changes": len(change_ids)}
    if files or show_all:
        payload["files"] = file_list
    if commits or show_all:
        payload["commits"] = commit_rows
    if authors or show_all:
        payload["authors"] = author_list
    if branches or show_all:
        payload["branches"] = branch_rows

    if json_mode(ctx):
        typer.echo(json.dumps(payload))
        return

    typer.echo(f"feature {name}: {len(change_ids)} change(s), {len(pairs)} annotation(s)")
    if "files" in payload:
        typer.echo("files:")
        for path in file_list:
            typer.echo(f"  {path}")
    if "commits" in payload:
        typer.echo("commits:")
        for row in commit_rows:
            typer.echo(f"  {row['sha'][:12]}  {row['subject']}")
    if "authors" in payload:
        typer.echo("authors:")
        for author in author_list:
            typer.echo(f"  {author}")
    if "branches" in payload:
        typer.echo("branches:")
        for branch_row in branch_rows:
            missing = int(branch_row["total"]) - int(branch_row["present"])  # type: ignore[call-overload]
            marker = f"  [missing {missing}]" if missing else ""
            typer.echo(
                f"  {branch_row['name']}: {branch_row['present']}/{branch_row['total']}"
                f" change(s){marker}"
            )


def _commits_and_authors(
    repo: pygit2.Repository, store: GitRefStore, change_ids: list[str]
) -> tuple[list[dict[str, str]], list[str]]:
    cid_map = ChangeIdMap(store)
    reachable = {str(commit.id) for commit in iter_all_commits(repo)}
    rows = []
    authors = set()
    for change_id in change_ids:
        for sha in cid_map.shas_for(change_id):
            if sha not in reachable:
                continue
            commit = repo[sha].peel(pygit2.Commit)
            rows.append(
                {
                    "sha": sha,
                    "change_id": change_id,
                    "subject": commit.message.splitlines()[0] if commit.message else "",
                    "author": commit.author.name,
                }
            )
            authors.add(commit.author.name)
    return rows, sorted(authors)


def _branches(
    repo: pygit2.Repository, store: GitRefStore, change_ids: list[str]
) -> list[dict[str, object]]:
    cid_map = ChangeIdMap(store)
    cid_shas = {change_id: set(cid_map.shas_for(change_id)) for change_id in change_ids}
    rows: list[dict[str, object]] = []
    for branch_name in sorted(repo.branches.local):
        branch = repo.branches.local[branch_name]
        contained = {str(commit.id) for commit in repo.walk(branch.target)}
        present = sum(1 for shas in cid_shas.values() if shas & contained)
        rows.append({"name": branch_name, "present": present, "total": len(change_ids)})
    return rows
