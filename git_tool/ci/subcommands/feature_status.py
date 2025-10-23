from collections import defaultdict
import typer

from git_tool.feature_data.git_status_per_feature import (
    get_features_for_file,
    get_files_by_git_change,
)
from git_tool.feature_data.models_and_context.feature_state import (
    read_staged_featureset,
)

WITHOUT_FEATURE = "Without Feature"

app = typer.Typer(
    no_args_is_help=False,  # Allow running without arguments to show help
    name=None,
    help="Display the current status of staged, unstaged, and untracked files, \
        along with their associated features.",
)


@app.command(name="status")
def feature_status(
    help: bool = typer.Option(
        None, "--help", "-h", is_eager=True, help="Show this message and exit."
    )
):
    """
    Displays the current status of files in the working directory, showing staged, unstaged, and untracked changes along with their associated features.
    Files without associated features will be highlighted, and suggestions for adding features will be provided.
    """
    if help:
        typer.echo(app.rich_help_panel)
        raise typer.Exit()

    changes = get_files_by_git_change()

    def group_files_by_feature(files: list[str]):
        feature_dict = defaultdict(list)
        for file in files:
            features = get_features_for_file(file)
            if not features:
                features = [WITHOUT_FEATURE]
            for feature in features:
                feature_dict[feature].append(file)
        return feature_dict

    def print_changes(
        change_type: str, files: list[str], staged_features: list[str] = []
    ):
        feature_dict = group_files_by_feature(files)
        typer.echo(f"{change_type.replace('_', ' ').title()}:")
        for feature, files in feature_dict.items():
            typer.echo(f"\t{feature}:")
            if feature == WITHOUT_FEATURE:
                typer.echo(
                    """\t (To assign a feature, run git feature-add <filename> <feature>)"""
                )
            for file in files:
                typer.echo(f"\t\t{file}")

    printed = False

    if len(changes.get("staged_files", [])) > 0:
        printed = True

        staged_features = read_staged_featureset()
        typer.echo("Staged Features: ")
        typer.echo(
            "\t(Features in parentheses are associated but not yet staged for the corresponding files)",
            color="yellow",
        )
        if staged_features:
            typer.echo(", ".join(staged_features))
        else:
            typer.echo(
                "No feature information found for the staged files. Please run 'git feature-add from-staged' \
                    to associate features.",
                err=True,
            )

        typer.echo("Feature changes to be committed:")
        for item in changes["staged_files"]:
            additional_features = get_features_for_file(item)
            unstaged_features = [
                f for f in additional_features if not f in staged_features
            ]
            if unstaged_features:
                non_staged_str = f" ({', '.join(unstaged_features)})"
            else:
                non_staged_str = ""
            typer.echo(f"\t{item} {non_staged_str}")

    if len(changes.get("unstaged_files", [])) > 0:
        printed = True
        print_changes(
            "Feature changes not staged for commit", changes["unstaged_files"]
        )

    if len(changes.get("untracked_files", [])) > 0:
        printed = True
        print_changes("Untracked files", changes["untracked_files"])

    if not printed:
        typer.echo("No changes.")


def is_commit_in_list(commit_id: str, commit_id_list: list[str]) -> bool:
    for commit in commit_id_list:
        min_length = min(len(commit_id), len(commit))
        if commit_id[:min_length] == commit[:min_length]:
            return True

    return False
