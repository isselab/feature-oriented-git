"""`git feature init` — initialize the feature store, hooks, change-id backfill, and model.cfr."""

import json
from importlib import metadata
from pathlib import Path

import typer

from ..gitio import RepositoryNotFound, open_repository
from ..gitio.hooks import install_hooks
from ..identity import ChangeIdMap
from ..identity import backfill as backfill_change_ids
from ..store import GitRefStore, StoreMeta

MODEL_FILE = "model.cfr"

_MODEL_TEMPLATE = """\
// Feature model for this repository (git-feature).
// Declare an abstract feature tree, then named instances (= variant specs).
//
// abstract App {
//     core
//     extras ?
//
//     [ extras => core ]
// }
//
// Minimal : App {}
//
// Full : App {
//     [ extras ]
// }
"""


def run(ctx: typer.Context, *, backfill: bool, hooks: bool) -> None:
    try:
        repo = open_repository()
    except RepositoryNotFound as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    actions = []
    store = GitRefStore(repo)
    already_initialized = store.read_meta() is not None
    if not already_initialized:
        store.write_meta(StoreMeta(tool_version=metadata.version("git-feature")))
        store.commit("initialize feature store")
        actions.append("created feature store at refs/feature/store")

    if backfill:
        minted = backfill_change_ids(repo, ChangeIdMap(store))
        if minted:
            store.commit(f"backfill change-ids for {minted} commits")
            actions.append(f"backfilled change-ids for {minted} commits")

    if repo.workdir is not None:
        model_path = Path(repo.workdir) / MODEL_FILE
        if not model_path.exists():
            model_path.write_text(_MODEL_TEMPLATE)
            actions.append(f"created starter {MODEL_FILE}")

    if hooks:
        actions.extend(install_hooks(repo))

    if ctx.obj.get("json"):
        typer.echo(json.dumps({"initialized": not already_initialized, "actions": actions}))
        return
    if already_initialized and not actions:
        typer.echo("already initialized, nothing to do")
        return
    if already_initialized:
        typer.echo("already initialized, repaired missing pieces:")
    for action in actions:
        typer.echo(action)
