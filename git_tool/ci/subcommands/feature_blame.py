from pathlib import Path
from typing import Any

import typer
from git import Repo
from git_tool.feature_data.read_feature_data.parse_data import get_features_touched_by_commit
from git_tool.feature_data.models_and_context.repo_context import (
    repo_context,
)

app = typer.Typer(no_args_is_help=True)


def read_file_lines(file_path: Path) -> list[str]:
    """
    Reads the lines of a file and returns them as a list.
    """
    with file_path.open("r", encoding="utf-8") as f:
        return f.readlines()


def get_line_to_blame_mapping(
    repo: Repo, file_path: Path, start_line: int, end_line: int
) -> dict[int, tuple[str, str]]:
    """
    Returns a mapping of line numbers to (commit hash, blame line).
    """
    blame_output = repo.git.blame(
        "-L", f"{start_line},{end_line}", "--date=short", str(file_path)
    )

    line_to_blame = {}
    line_number = start_line

    for line in blame_output.splitlines():
        if line.startswith(":"):
            continue
        blame_part = line.split(" ", 1)
        short_hash = blame_part[0]
        blame_text = blame_part[1] if len(blame_part) > 1 else ""
        full_hash = repo.git.rev_parse(short_hash)
        line_to_blame[line_number] = (short_hash, blame_text)
        line_number += 1

    return line_to_blame


def get_commit_to_features_mapping(line_to_commit: dict[int, tuple[str, str]]) -> dict[str, str]:
    """
    Returns a mapping of commit hashes to features.
    """
    unique_commits = {commit for commit, _ in line_to_commit.values()}

    commit_to_features = {
        commit_id: ", ".join(get_features_touched_by_commit(commit_id))
        for commit_id in unique_commits
    }

    return commit_to_features


def get_line_to_features_mapping(
    repo: Repo, file_path: Path, start_line: int, end_line: int
) -> tuple[dict[int, Any], dict[int, tuple[str, str]]]:
    """
    Returns a mapping of line numbers to features.
    """
    # Get the commit for each line using 'git blame'
    line_to_blame = get_line_to_blame_mapping(repo, file_path, start_line, end_line)
    # for debugging: print("Step 1: ", line_to_blame)

    # Get the features for each commit
    commit_to_features = get_commit_to_features_mapping(line_to_blame)
    # for debugging: print("Step 2: ", commit_to_features)

    # Map each line to its corresponding feature
    line_to_features = {
        line: commit_to_features.get(commit_hash, "UNKNOWN")
        for line, (commit_hash, _) in line_to_blame.items()
    }
    # for debugging: print("Step 3: ", line_to_features)

    return line_to_features, line_to_blame


def print_feature_blame_output(
    lines: list[str],
    mappings: tuple[dict[int, Any], dict[int, tuple[str, str]]],
    start_line: int,
    end_line: int,
):
    """
    Prints the feature blame output similar to git blame.
    """
    line_to_features, line_to_blame = mappings
    # Get the max width of feature strings for alignment
    max_feature_width = max(
        (len(line_to_features.get(commit, "UNKNOWN")) for commit in line_to_features.values()),
        default=15,
    )

    for i in range(start_line, end_line + 1):
        line = lines[i - 1]  # Adjust because list is 0-indexed, but line numbers start from 1
        commit_hash, blame_text = line_to_blame.get(i)
        blame_text = blame_text.replace("(", "", 1)
        feature = line_to_features.get(i, "UNKNOWN")
        typer.echo(f"{feature:<15} ({commit_hash} {blame_text}")


@app.command(help="Display features associated with file lines.", no_args_is_help=True, name=None)
def feature_blame(
    filename: str = typer.Argument(
        ..., help="The file to display feature blame for."
    ),
    line: str = typer.Option(
        None, help="Specify a line or range of lines (e.g., '5' or '5-10')."
    ),
):
    """
    Displays features associated with file lines. You can optionally specify a line or a range of lines.
    """
    file_path = Path(filename)

    if not file_path.exists():
        typer.echo(f"Error: file '{filename}' not found.")
        raise typer.Exit(code=1)

    # Read the file contents
    lines = read_file_lines(file_path)

    # Default to the entire file if no line argument is provided
    start_line = 1
    end_line = len(lines)

    if line:
        if "-" in line:
            # Handle a range of lines
            start_line, end_line = map(int, line.split("-"))
        else:
            # Handle a single line
            start_line = end_line = int(line)

    # Ensure the line range is valid
    if start_line < 1 or end_line > len(lines):
        typer.echo("Error: Line number out of range.")
        raise typer.Exit(code=1)

    if start_line > end_line:
        typer.echo("Error: Start line must be less than end line.")
        raise typer.Exit(code=1)

    with repo_context() as repo:  # Use repo_context for the git operations
        feature_to_line_mapping = get_line_to_features_mapping(
            repo, file_path, start_line, end_line
        )

    print_feature_blame_output(
        lines, feature_to_line_mapping, start_line, end_line
    )


if __name__ == "__main__":
    app()
