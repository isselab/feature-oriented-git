"""Command-line interface for git-feature."""

from enum import StrEnum
from importlib import metadata
from typing import Annotated

import typer

from .commands import annotate as annotate_cmd
from .commands import blame as blame_cmd
from .commands import checkout as checkout_cmd
from .commands import coverage as coverage_cmd
from .commands import doctor as doctor_cmd
from .commands import hook_run as hook_run_cmd
from .commands import info as info_cmd
from .commands import init as init_cmd
from .commands import list as list_cmd
from .commands import model as model_cmd
from .commands import putback as putback_cmd
from .commands import reconcile as reconcile_cmd
from .commands import status as status_cmd
from .commands import store as store_cmd
from .commands import sync as sync_cmd
from .commands import variant as variant_cmd
from .commands import view as view_cmd
from .commands import whatfeature as whatfeature_cmd

app = typer.Typer(name="git-feature", no_args_is_help=True)


def _version(value: bool) -> None:
    if value:
        typer.echo(metadata.version("git-feature"))
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON output.")
    ] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Feature-oriented version control on top of git."""
    ctx.obj = {"json": as_json}


@app.command()
def init(
    ctx: typer.Context,
    backfill: Annotated[
        bool,
        typer.Option(help="Mint change-ids for all existing history upfront (default: lazy)."),
    ] = False,
    hooks: Annotated[bool, typer.Option(help="Install chained git hooks.")] = True,
) -> None:
    """Initialize the feature store, hooks, and a starter model.cfr."""
    init_cmd.run(ctx, backfill=backfill, hooks=hooks)


@app.command()
def annotate(
    ctx: typer.Context,
    rev: Annotated[str | None, typer.Argument(help="Commit to annotate (default HEAD).")] = None,
    features: Annotated[
        list[str] | None, typer.Option("--feature", help="Feature name (repeatable).")
    ] = None,
    presence: Annotated[
        str | None, typer.Option(help="Presence condition expression, e.g. 'a & !b'.")
    ] = None,
    paths: Annotated[
        list[str] | None,
        typer.Option("--path", help="Pathspec glob to restrict hunks (repeatable)."),
    ] = None,
    rev_range: Annotated[
        str | None, typer.Option("--range", help="Annotate every commit in range A..B.")
    ] = None,
) -> None:
    """Associate diff hunks with features."""
    annotate_cmd.run(
        ctx,
        rev=rev,
        features=tuple(features or ()),
        presence=presence,
        paths=tuple(paths or ()),
        rev_range=rev_range,
    )


@app.command(name="list")
def list_(ctx: typer.Context) -> None:
    """List the feature catalog with annotation counts."""
    list_cmd.run(ctx)


@app.command()
def info(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Feature name.")],
    files: Annotated[bool, typer.Option("--files", help="List files the feature touches.")] = False,
    commits: Annotated[bool, typer.Option("--commits", help="List the feature's commits.")] = False,
    authors: Annotated[bool, typer.Option("--authors", help="List contributing authors.")] = False,
    branches: Annotated[
        bool, typer.Option("--branches", help="Cross-branch presence view.")
    ] = False,
) -> None:
    """Show detailed information about a feature."""
    info_cmd.run(ctx, name=name, files=files, commits=commits, authors=authors, branches=branches)


@app.command()
def status(ctx: typer.Context) -> None:
    """Show working-directory and staged changes grouped by feature."""
    status_cmd.run(ctx)


@app.command()
def blame(
    ctx: typer.Context,
    file: Annotated[str, typer.Argument(help="File to inspect.")],
    line: Annotated[int | None, typer.Option(help="Show only this line number.")] = None,
) -> None:
    """Show per-line feature presence conditions for a file."""
    blame_cmd.run(ctx, file=file, line=line)


@app.command()
def whatfeature(
    ctx: typer.Context,
    rev: Annotated[str, typer.Argument(help="Commit to inspect.")],
) -> None:
    """Show which features a commit touches."""
    whatfeature_cmd.run(ctx, rev=rev)


@app.command()
def coverage(
    ctx: typer.Context,
    rev_range: Annotated[
        str | None, typer.Argument(help="Range A..B (default: all reachable commits).")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", help="Per-commit listing.")] = False,
) -> None:
    """Report annotated vs unannotated changes over a range."""
    coverage_cmd.run(ctx, rev_range=rev_range, verbose=verbose)


model_app = typer.Typer(no_args_is_help=True)
app.add_typer(model_app, name="model", help="Feature model (model.cfr) operations.")


@model_app.command()
def validate(
    ctx: typer.Context,
    instance: Annotated[
        str | None, typer.Argument(help="Variant instance to check (default: whole model).")
    ] = None,
) -> None:
    """Validate the model, annotations, or a specific instance/configuration."""
    model_cmd.run(ctx, instance=instance)


@app.command()
def checkout(
    ctx: typer.Context,
    instance: Annotated[str, typer.Argument(help="Variant instance from model.cfr.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report the variant plan without materializing.")
    ] = False,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Update an existing variant branch.")
    ] = False,
    base: Annotated[
        str | None, typer.Option(help="Base revision to build the variant from (default HEAD).")
    ] = None,
    no_switch: Annotated[
        bool,
        typer.Option("--no-switch", help="Create the variant branch without switching to it."),
    ] = False,
    verify_only: Annotated[
        bool, typer.Option("--verify-only", help="Re-verify an existing variant, don't rebuild.")
    ] = False,
) -> None:
    """Check out a product variant for a model instance."""
    checkout_cmd.run(
        ctx,
        instance=instance,
        dry_run=dry_run,
        refresh=refresh,
        base=base,
        no_switch=no_switch,
        verify_only=verify_only,
    )


variant_app = typer.Typer(no_args_is_help=True)
app.add_typer(variant_app, name="variant", help="Manage derived variants.")

store_app = typer.Typer(no_args_is_help=True)
app.add_typer(store_app, name="store", help="Share the feature store with remotes.")


@store_app.command(name="push")
def store_push(
    ctx: typer.Context,
    remote: Annotated[str, typer.Argument(help="Remote to push the store to.")] = "origin",
) -> None:
    """Push the feature store ref to a remote."""
    store_cmd.run_push(ctx, remote_name=remote)


@store_app.command(name="fetch")
def store_fetch(
    ctx: typer.Context,
    remote: Annotated[str, typer.Argument(help="Remote to fetch the store from.")] = "origin",
) -> None:
    """Fetch a remote's feature store and merge it if the stores diverged."""
    store_cmd.run_fetch(ctx, remote_name=remote)


@variant_app.command(name="list")
def variant_list(ctx: typer.Context) -> None:
    """List derived variants, their base commit, configuration, and staleness."""
    variant_cmd.run(ctx)


@app.command()
def view(
    ctx: typer.Context,
    instance: Annotated[str, typer.Argument(help="Variant instance from model.cfr.")],
) -> None:
    """Check out a variant as an editable view (edits go back with putback)."""
    view_cmd.run(ctx, instance=instance)


@app.command()
def putback(
    ctx: typer.Context,
    message: Annotated[
        str | None, typer.Option("--message", "-m", help="Commit message for the source commit.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report the mapped edits without committing.")
    ] = False,
) -> None:
    """Transplant edits from a variant view back to the source branch."""
    putback_cmd.run(ctx, dry_run=dry_run, message=message)


@app.command()
def sync(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="Branch to propagate commits from.")],
    feature: Annotated[
        str | None, typer.Option("--feature", "-f", help="Restrict propagation to one feature.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report what would be cherry-picked.")
    ] = False,
) -> None:
    """Propagate a feature's missing commits from SOURCE onto the current branch."""
    sync_cmd.run(ctx, source=source, feature=feature, dry_run=dry_run)


@app.command()
def reconcile(
    ctx: typer.Context,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report planned links without writing.")
    ] = False,
    interactive: Annotated[
        bool, typer.Option("--interactive", help="Resolve ambiguous matches interactively.")
    ] = False,
) -> None:
    """Re-link commits that arrived outside the hooks (cherry-picks, imports)."""
    reconcile_cmd.run(ctx, dry_run=dry_run, interactive=interactive)


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Health-check the store, hooks, and change-id map."""
    doctor_cmd.run(ctx)


class HookName(StrEnum):
    POST_COMMIT = "post-commit"
    POST_REWRITE = "post-rewrite"


@app.command(name="hook-run", hidden=True)
def hook_run(
    ctx: typer.Context,
    hook: Annotated[HookName, typer.Argument(help="Hook being dispatched.")],
) -> None:
    """Internal: entry point invoked by the installed git hooks."""
    hook_run_cmd.run(ctx, hook=hook.value)
