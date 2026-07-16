"""`git feature status` — working-directory changes grouped by feature."""

import json

import pygit2
import typer

from ..domain.query.catalog import iter_annotations
from ..gitio import worktree_diff
from ..identity import ChangeIdMap, RegionResolver
from ..store import GitRefStore
from .common import json_mode, require_repo, require_store


def run(ctx: typer.Context) -> None:
    repo = require_repo()
    store = require_store(repo)

    dirty = worktree_diff(repo)
    if not any(file_diff.hunks for file_diff in dirty):
        typer.echo("working tree clean")
        return

    dirty_paths = {f.old_path for f in dirty if f.old_path} | {
        f.new_path for f in dirty if f.new_path
    }
    regions = _resolved_regions(repo, store, dirty_paths)

    by_feature: dict[str, list[str]] = {}
    unassigned: list[str] = []
    for file_diff in dirty:
        path = file_diff.old_path or file_diff.new_path or ""
        for hunk in file_diff.hunks:
            location = f"{file_diff.new_path or path} @ {hunk.new_span[0]}"
            touched = sorted(
                {
                    presence
                    for region_path, span, presence in regions
                    if region_path == path and _overlaps(hunk.old_span, span)
                }
            )
            if touched:
                for presence in touched:
                    by_feature.setdefault(presence, []).append(location)
            else:
                unassigned.append(location)

    if json_mode(ctx):
        typer.echo(json.dumps({"features": by_feature, "unassigned": unassigned}))
        return
    for presence in sorted(by_feature):
        typer.echo(f"{presence}:")
        for location in by_feature[presence]:
            typer.echo(f"  {location}")
    if unassigned:
        typer.echo("unassigned:")
        for location in unassigned:
            typer.echo(f"  {location}")


def _resolved_regions(
    repo: pygit2.Repository, store: GitRefStore, paths: set[str]
) -> list[tuple[str, tuple[int, int], str]]:
    """(path, span at HEAD, presence) for annotations on the given paths."""
    cid_map = ChangeIdMap(store)
    resolver = RegionResolver(repo, cid_map)
    regions = []
    for _, annotation in iter_annotations(store):
        if annotation.anchor.path not in paths:
            continue
        resolution = resolver.resolve(annotation.anchor, "HEAD")
        for run in resolution.line_runs():
            regions.append((annotation.anchor.path, run, annotation.presence))
    return regions


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    a_end = a[0] + max(a[1], 1) - 1
    b_end = b[0] + max(b[1], 1) - 1
    return a[0] <= b_end and b[0] <= a_end
