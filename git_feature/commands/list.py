"""`git feature list` — the feature catalog with annotation counts."""

import json

import typer

from ..domain.query.catalog import iter_annotations, presence_features
from .common import json_mode, require_repo, require_store


def run(ctx: typer.Context) -> None:
    repo = require_repo()
    store = require_store(repo)

    annotation_counts: dict[str, int] = {}
    change_sets: dict[str, set[str]] = {}
    for change_id, annotation in iter_annotations(store):
        for name in presence_features(annotation.presence):
            annotation_counts[name] = annotation_counts.get(name, 0) + 1
            change_sets.setdefault(name, set()).add(change_id)

    rows = []
    for name in store.list_features():
        feature = store.read_feature(name)
        rows.append(
            {
                "name": name,
                "annotations": annotation_counts.get(name, 0),
                "changes": len(change_sets.get(name, ())),
                "auto_created": bool(feature and feature.auto_created),
                "description": feature.description if feature else "",
            }
        )

    if json_mode(ctx):
        typer.echo(json.dumps(rows))
        return
    if not rows:
        typer.echo("no features defined yet (annotate something, or add them to model.cfr)")
        return
    name_width = max(len(str(row["name"])) for row in rows)
    typer.echo(f"{'FEATURE':<{name_width}}  ANNOTATIONS  CHANGES")
    for row in rows:
        auto = "  (auto)" if row["auto_created"] else ""
        typer.echo(
            f"{row['name']:<{name_width}}  {row['annotations']:>11}  {row['changes']:>7}{auto}"
        )
