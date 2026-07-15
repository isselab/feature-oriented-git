"""`git feature doctor` — health check for store, hooks, and change-id map."""

from typing import Any

import typer

from . import not_implemented


def run(ctx: typer.Context, **kwargs: Any) -> None:
    not_implemented(ctx)
