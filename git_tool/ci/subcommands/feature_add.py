import typer

from git_tool.feature_data.git_status_per_feature import (
    get_features_for_file,
    get_files_by_git_change,
)
from git_tool.feature_data.models_and_context.feature_state import (
    reset_staged_featureset,
    write_staged_featureset,
)
from git_tool.feature_data.models_and_context.repo_context import repo_context
from git_tool.finding_features import features_for_file_by_annotation

app = typer.Typer(no_args_is_help=True)


@app.command("add", help="Stage files and associate them with the provided features.", no_args_is_help=True)
def feature_add_by_add(
    feature_names: list[str] = typer.Argument(
        None, help="List of feature names to associate with the staged files"
    ),
    all_files: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Stage all tracked changes and associate with features",
    ),
    selected_files: list[str] = typer.Option(
        None,
        "--files",
        "-f",
        help="Specify a list of files to stage and associate with features",
    ),
):
    """
    Stage specific files or all files and associate them with the provided features.
    """
    if all_files:
        typer.echo("Staging all files and associating with features")
        stage_files(get_files_by_git_change().get("tracked_files", []))
    elif selected_files:
        typer.echo(f"Staging selected files: {selected_files}")
        stage_files(selected_files)
    else:
        typer.echo("No files selected. Use --all or --files.", err=True)
        return

    if feature_names:
        typer.echo(f"Associating features: {feature_names}")
        write_staged_featureset(feature_names)
    else:
        typer.echo("No features provided.", err=True)



def stage_files(selected_files: list[str]) -> bool:
    """
    Stage all selected files and return whether the staging area has changed.

    Arguments:
        selected_files -- List of file identifiers that git understands for git add

    Returns:
        Boolean whether there were actually new staged changes.
    """
    typer.echo("Staging files")
    with repo_context() as repo:
        for file in selected_files:
            try:
                initial_diff = repo.git.diff("--cached")
                repo.git.add(file)
                typer.echo(f"Staged file: {file}")
                final_diff = repo.git.diff("--cached")
                if initial_diff == final_diff:
                    typer.echo(
                        "No changes were made to the staging area. Aborting.",
                        err=True,
                    )
                    return False
            except Exception as e:
                typer.echo(f"Error staging file {file}: {e}", err=True)
                return False
    return True


def is_staging_area_empty() -> bool:
    typer.echo("Checking if there are staged files")
    changes = get_files_by_git_change()

    if len(changes["staged_files"]) == 0:
        typer.echo(
            "No staged changes, so no feature information to add", err=True
        )
        reset_staged_featureset()
        return True
    else:
        return False


def create_feature_meta_info(
    features: list[str], insert_annotations: bool = False
):
    typer.echo(f"Adding feature information {features} to staged files")
    write_staged_featureset(features)
    if insert_annotations:
        typer.echo("Not adding annotations, not implemented yet", err=True)


if __name__ == "__main__":
    app()
