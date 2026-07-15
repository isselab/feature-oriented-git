"""`git feature list` — list the feature catalog with counts."""

from typing import Any

import typer

from . import not_implemented


def run(ctx: typer.Context, **kwargs: Any) -> None:
    not_implemented(ctx)
