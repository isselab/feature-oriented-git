"""`git feature blame` — per-line feature presence conditions for a file."""

import json

import typer

from ..domain.query.catalog import iter_annotations
from ..gitio import blob_lines
from ..identity import ChangeIdMap, RegionResolver
from .common import json_mode, require_repo, require_store


def run(ctx: typer.Context, *, file: str, line: int | None) -> None:
    repo = require_repo()
    store = require_store(repo)

    lines = blob_lines(repo, "HEAD", file)
    if lines is None:
        typer.echo(f"error: '{file}' not found at HEAD (or binary)", err=True)
        raise typer.Exit(1)

    conditions: dict[int, list[str]] = {}
    resolver = RegionResolver(repo, ChangeIdMap(store))
    for _, annotation in iter_annotations(store):
        if annotation.anchor.path != file:
            continue
        resolution = resolver.resolve(annotation.anchor, "HEAD")
        if resolution.span is None:
            continue
        start, count = resolution.span
        for number in range(start, start + count):
            conditions.setdefault(number, []).append(annotation.presence)

    rows = [
        {
            "line": number,
            "presence": " , ".join(sorted(set(conditions.get(number, [])))) or None,
            "content": text,
        }
        for number, text in enumerate(lines, start=1)
        if line is None or number == line
    ]
    if line is not None and not rows:
        typer.echo(f"error: line {line} is out of range (file has {len(lines)} lines)", err=True)
        raise typer.Exit(1)

    if json_mode(ctx):
        typer.echo(json.dumps(rows))
        return
    width = max((len(str(row["presence"] or "-")) for row in rows), default=1)
    for row in rows:
        presence = str(row["presence"] or "-")
        typer.echo(f"{row['line']:>4}  {presence:<{width}}  {row['content']}")
