import typer


def derive_variant(
    name: str = typer.Argument(..., help="Name of the variant"),
    features: list[str] = typer.Option(
        ...,
        "--features",
        "-f",
        help="One or more features to include",
    ),
):
    """Derive a variant from the provided feature set."""
    print(f"Deriving variant: {name} with features: {features}!")
