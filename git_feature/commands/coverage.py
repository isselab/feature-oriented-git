"""`git feature coverage` — annotated vs unannotated changes over a range."""

import json

import typer

from ..gitio import iter_all_commits, iter_range
from ..identity import ChangeIdMap
from .common import json_mode, require_repo, require_store


def run(ctx: typer.Context, *, rev_range: str | None, verbose: bool) -> None:
    repo = require_repo()
    store = require_store(repo)
    cid_map = ChangeIdMap(store)
    annotated_changes = set(store.list_annotated_changes())

    commits = iter_range(repo, rev_range) if rev_range else iter_all_commits(repo)
    rows = []
    for commit in commits:
        sha = str(commit.id)
        record = cid_map.get(sha)
        annotated = record is not None and record.change_id in annotated_changes
        rows.append(
            {
                "sha": sha,
                "subject": commit.message.splitlines()[0] if commit.message else "",
                "annotated": annotated,
            }
        )

    total = len(rows)
    covered = sum(1 for row in rows if row["annotated"])
    unannotated = [str(row["sha"]) for row in rows if not row["annotated"]]

    if json_mode(ctx):
        typer.echo(
            json.dumps(
                {
                    "total": total,
                    "annotated": covered,
                    "unannotated": unannotated,
                }
            )
        )
        return

    percent = (100 * covered // total) if total else 0
    typer.echo(f"{covered}/{total} commits annotated ({percent}%)")
    if verbose:
        for row in rows:
            marker = "+" if row["annotated"] else "-"
            typer.echo(f"  {marker} {str(row['sha'])[:12]}  {row['subject']}")
