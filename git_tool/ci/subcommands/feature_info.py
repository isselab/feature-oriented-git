import typer

from git_tool.feature_data.analyze_feature_data.feature_utils import (
    get_commits_for_feature_on_other_branches,
    get_current_branchname,
)
from git_tool.feature_data.git_helper import (
    get_author_for_commit,
    get_branches_for_commit,
    get_files_for_commit,
)
from git_tool.feature_data.git_status_per_feature import get_commits_for_feature


def print_list_w_indent(stuff: list, indent: int = 1) -> None:
    for item in stuff:
        typer.echo("\t" * indent + item)


app = typer.Typer(
    help="Displaying feature information for the entire git repo",
    no_args_is_help=True,
)


# TODO sollte zu git feature-status
# @currently_staged_app.command(name=None)
# def get_stuff():
#     typer.echo("Currently staged")
#     print_list_w_indent(read_staged_featureset())
#     return


@app.command(name="info")
def inspect_feature(
    feature: str = typer.Argument(..., help="Inspect a particular feature"),
    authors: bool = typer.Option(
        False, help="Show all authors who contributed to this feature."
    ),
    files: bool = typer.Option(
        False, help="List all files associated with the feature."
    ),
    branches: bool = typer.Option(
        False, help="Show all branches where the feature is present."
    ),
    updatable: bool = typer.Option(
        False,
        help="Check if the feature has updates available on other branches and list the update options.",
    ),
    branch: str = typer.Option(
        None,
        help="Used with --updatable to specify a branch for checking updates. \
            Ignored if --updatable is not set.",
    ),
):
    typer.echo(f"Collecting information for feature {feature}")
    try:
        typer.echo("Commit IDs")
        commit_ids = [x.hexsha for x in get_commits_for_feature(feature)]
        print_list_w_indent(commit_ids)
    except Exception:
        commit_ids = []
        typer.echo(f"No commit-ids for feature {feature} found")
    if branches:
        typer.echo("Branches (* indicates current branch)")
        branches = set(
            [
                branch
                for c in commit_ids
                for branch in get_branches_for_commit(c)
            ]
        )
        print_list_w_indent(branches)
    if authors:
        typer.echo("Authors")
        authors = set([get_author_for_commit(c) for c in commit_ids])
        print_list_w_indent(authors)
    if files:
        typer.echo("Files")
        files = set(
            file for c in commit_ids for file in get_files_for_commit(c)
        )
        print_list_w_indent(files)
    if updatable:
        typer.echo(
            f"Evaluating if feature {feature} can be updated on current branch {get_current_branchname()}"
        )
        if branch:
            typer.echo(
                f"Comparing commits for the feature '{feature}' on the current branch '{get_current_branchname()}' with branch '{branch}'"
            )
            try:
                other_commits = get_commits_for_feature_on_other_branches(
                    feature_commits=commit_ids, other_branch=branch
                )
                if other_commits:
                    typer.echo(
                        f"Found {len(other_commits)} commits for feature '{feature}' on branch '{branch}'."
                    )
                    for commit in other_commits:
                        typer.echo(
                            f"{commit.hexsha} - {commit.message.splitlines()[0]}"
                        )

                else:
                    typer.echo(
                        f"No commits found for feature '{feature}' on branch '{branch}'."
                    )
            except Exception as e:
                typer.secho(
                    f"Error retrieving commits for branch '{branch}': {e}",
                    fg=typer.colors.RED,
                )
        else:
            typer.echo(
                f"Comparing commits for the feature '{feature}' on all other branches with the current branch '{get_current_branchname()}'"
            )
            try:
                other_commits = get_commits_for_feature_on_other_branches(
                    feature_commits=commit_ids
                )
                if other_commits:
                    typer.echo(
                        f"Found {len(other_commits)} commits for feature '{feature}' on other branches."
                    )
                    for commit in other_commits:
                        typer.echo(
                            f"{commit.hexsha[:7]} - {commit.message.splitlines()[0]}"
                        )
                else:
                    typer.echo(
                        f"No commits found for feature '{feature}' on other branches."
                    )
            except Exception as e:
                typer.secho(
                    f"Error retrieving commits for other branches: {e}",
                    fg=typer.colors.RED,
                )


if __name__ == "__main__":
    app()
