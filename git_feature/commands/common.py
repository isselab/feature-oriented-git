"""Shared plumbing for command implementations."""

import pygit2
import typer

from ..gitio import RepositoryNotFound, open_repository
from ..store import GitRefStore


def require_repo() -> pygit2.Repository:
    """Open the repository from cwd or exit with an error."""
    try:
        return open_repository()
    except RepositoryNotFound as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None


def require_store(repo: pygit2.Repository) -> GitRefStore:
    """Open the feature store or exit if the tool was never initialized."""
    store = GitRefStore(repo)
    if store.read_meta() is None:
        typer.echo("error: not initialized (run 'git feature init')", err=True)
        raise typer.Exit(1)
    return store


def json_mode(ctx: typer.Context) -> bool:
    """Whether the global --json flag was given."""
    return bool(ctx.obj and ctx.obj.get("json"))
