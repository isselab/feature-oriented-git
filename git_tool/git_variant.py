import typer

from git_tool.ci.subcommands.variant_derive import derive_variant
from git_tool.ci.subcommands.variant_list import list_variant

app = typer.Typer(name="variant", no_args_is_help=True)
app.command(
    "derive",
    no_args_is_help=True,
)(derive_variant)
app.command(
    "list",
)(list_variant)

app()
