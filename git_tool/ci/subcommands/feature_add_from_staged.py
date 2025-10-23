import typer

from git_tool.feature_data.git_status_per_feature import (
    get_features_for_file,
    get_files_by_git_change,
)
from git_tool.feature_data.models_and_context.feature_state import (
    reset_staged_featureset,
    write_staged_featureset,
)


app = typer.Typer()


@app.command(name="add-from-staged", help="Associate staged files with features.")
def features_from_staging_area():
    """
    Use the staged files to add feature information.
    """
    feature_names = read_features_from_staged()
    if feature_names:
        typer.echo(f"Features in staging area: {feature_names}")
        write_staged_featureset(feature_names)
    else:
        typer.echo("No features found in staging area.", err=True)


def read_features_from_staged(type: str = "Union") -> list[str]:
    """
    Retrieve the features from the current staging area.

    Keyword Arguments:
        type -- Can be Union or Intersection. Describes how multiple features will be combined (default: {"Union"})

    Returns:
        List of features.
    """
    typer.echo("Using staged files")

    staged_files = get_files_by_git_change().get("staged_files", [])
    feature_sets = [set(get_features_for_file(f)) for f in staged_files]

    if not feature_sets:
        return []

    if type == "Union":
        combined_features = set.union(*feature_sets)
    elif type == "Intersection":
        combined_features = set.intersection(*feature_sets)
    else:
        raise ValueError(
            "Invalid type specified. Use 'Union' or 'Intersection'."
        )

    return list(combined_features)