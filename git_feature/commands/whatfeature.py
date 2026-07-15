"""`git feature whatfeature` — show which features a commit touches."""

from typing import Any

import typer

from . import not_implemented


def run(ctx: typer.Context, **kwargs: Any) -> None:
    not_implemented(ctx)
