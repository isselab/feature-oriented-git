"""Command implementations, one module per CLI subcommand."""

import typer


def not_implemented(ctx: typer.Context) -> None:
    """Print a placeholder notice for a command that is not implemented yet."""
    typer.echo(f"{ctx.command_path}: not implemented yet")
