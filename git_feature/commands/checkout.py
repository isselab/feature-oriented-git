"""`git feature checkout` — check out a product variant derived from the feature model."""

from typing import Any

import typer

from . import not_implemented


def run(ctx: typer.Context, **kwargs: Any) -> None:
    not_implemented(ctx)
