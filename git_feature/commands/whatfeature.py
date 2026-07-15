"""`git feature whatfeature` — which features a commit touches."""

import json

import typer

from ..gitio import resolve_commit
from ..identity import ChangeIdMap
from .common import json_mode, require_repo, require_store


def run(ctx: typer.Context, *, rev: str) -> None:
    repo = require_repo()
    store = require_store(repo)

    commit = resolve_commit(repo, rev)
    sha = str(commit.id)
    record = ChangeIdMap(store).get(sha)
    annotations = store.read_annotations(record.change_id) if record else []

    if json_mode(ctx):
        typer.echo(
            json.dumps(
                {
                    "sha": sha,
                    "change_id": record.change_id if record else None,
                    "annotations": [
                        {
                            "presence": a.presence,
                            "path": a.anchor.path,
                            "span": list(a.anchor.new_span),
                        }
                        for a in annotations
                    ],
                }
            )
        )
        return

    if not annotations:
        typer.echo(f"{sha[:12]}: no features recorded")
        return
    typer.echo(f"{sha[:12]}:")
    for annotation in annotations:
        anchor = annotation.anchor
        typer.echo(f"  {annotation.presence}  {anchor.path} @ {anchor.new_span[0]}")
