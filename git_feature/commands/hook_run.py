"""`git feature hook-run` — internal entry point invoked by the installed git hooks."""

from typing import Any

import typer

from . import not_implemented


def run(ctx: typer.Context, **kwargs: Any) -> None:
    not_implemented(ctx)
