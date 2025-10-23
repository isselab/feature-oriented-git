import typer

from git_tool.feature_data.read_feature_data.parse_data import (
    _get_feature_uuids,
)


app = typer.Typer()


@app.command(name="info-all")
def all_feature_info():
    """
    Inspects feature information.
    """
    typer.echo("All Features")
    print_list_w_indent(_get_feature_uuids())


def print_list_w_indent(stuff: list, indent: int = 1) -> None:
    for item in stuff:
        typer.echo("\t" * indent + item)