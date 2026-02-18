from collections import namedtuple
from typing import List, TypedDict

from git import Commit, GitCommandError
from git_tool.feature_data.file_based_git_info import get_commits_for_file

from git_tool.feature_data.models_and_context.repo_context import (
    FEATURE_BRANCH_NAME,
    branch_folder_list,
    repo_context,
)


class GitChanges(TypedDict):
    """
    List files by git status
    """

    staged_files: List[str]
    unstaged_files: List[str]
    untracked_files: List[str]


GitStatusEntry = namedtuple("GitStatusEntry", ["status", "file_path"])


# Usages: FEATURE ADD, ADD-FROM-STAGED, PRE-COMMIT, STATUS
def get_files_by_git_change() -> GitChanges:
    """
    Retrieves files sorted by the type of git change (staged, unstaged, untracked).
    Can be used in combination with finding feature annotations for files to help
    figure out which features are already staged.

    Returns:
        Dict[str, List[str]]: A dictionary with keys 'staged_files', 'unstaged_files',
        and 'untracked_files', each containing a list of file paths.
    """

    def convert_to_status_entry(short_status_line: str) -> GitStatusEntry:
        return GitStatusEntry(short_status_line[:2], short_status_line[3:])

    with repo_context() as repo:
        result = repo.git.status("-s")
        lines = list(map(convert_to_status_entry, result.split("\n")))
        changes: GitChanges = {
            "staged_files": [],
            "unstaged_files": [],
            "untracked_files": [],
        }
        for entry in lines:
            if entry.status and entry.status[0] != " " and entry.status != "??":
                changes["staged_files"].append(entry.file_path)
            if entry.status and entry.status[1] != " " and entry.status != "??":
                changes["unstaged_files"].append(entry.file_path)
            if entry.status == "??":
                changes["untracked_files"].append(entry.file_path)

        return dict(changes)


def find_annotations_for_file(file: str):
    """
    Parse file for comment-based feature hints and search for file and folder annotations.
    This makes use of the feature-annotation system. Not documented further here.
    """
    raise NotImplementedError


# Usage: FEATURE ADD-FROM-STAGED, BLAME, STATUS
def get_features_for_file(
    file_path: str, use_annotations: bool = False
) -> List[str]:
    """
    Retrieves features for a given file.

    This function determines which features are associated with a specific file
    in a Git repository. It can use either feature annotations or the commit history
    to determine these associations.

    If the `use_annotations` flag is set to True, the function searches for annotations
    in the folder, file, and line levels. Otherwise, it examines the commit history to
    identify features associated with the file.

    Args:
        file_path (str): The path to the file whose features are to be retrieved.
        use_annotations (bool): Flag indicating whether to use annotations for
                                determining features. Defaults to False.

    Returns:
        List[str]: A list of features associated with the file. If no features are
                   found, an empty list is returned.
    """
    features = []
    if use_annotations:
        features = find_annotations_for_file(file_path)
        return features

    commits = get_commits_for_file(file_name=file_path, branch_name=None)
    with branch_folder_list() as (feature_folders, _):
        for commit in commits:
            for feature in feature_folders:
                feature_name = get_feature_name_from_folder(feature)
                if commit_in_feature_folder(commit, feature_name):
                    features.append(feature_name)
    return features


# Usages: FEATURE INFO, FEATURE STATUS
def get_commits_for_feature(feature_uuid: str) -> list[Commit]:
    with repo_context() as repo:
        output = repo.git.ls_tree(
            "-d", "--name-only", f"{FEATURE_BRANCH_NAME}:{feature_uuid}"
        )
        return [repo.commit(x) for x in output.split("\n")]


def commit_in_feature_folder(commit: str, feature_folder: str) -> bool:
    """
    Check if a commit is present for a feature.

    Args:
        commit (str): The commit hash.
        feature_folder (str): The path to the feature folder.

    Returns:
        bool: True if the commit is present in the feature folder, False otherwise.
    """
    assert isinstance(commit, str), (
        f"Expected commit to be a string, but got {type(commit).__name__}"
    )
    assert isinstance(feature_folder, str), (
        f"Expected feature_folder to be a string, but got {type(feature_folder).__name__}"
    )
    with repo_context() as repo:
        commit_obj = repo.commit(commit)
    result = commit_obj.hexsha in [
        x.hexsha for x in get_commits_for_feature(feature_uuid=feature_folder)
    ]
    return result


def get_feature_for_hunk(file_path: str, hunk: str) -> List[str]:
    """
    Retrieves features for specific changes (hunks) in a given file.

    Args:
        file_path (str): The path to the file.
        hunk (str): The specific changes (hunks) in the file.

    Returns:
        List[str]: A list of features associated with the specific hunks in the file.
    """
    raise NotImplementedError()
    # features = get_features_for_hunk(file_path, hunk)
    # return features


def get_feature_name_from_folder(feature_folder: str) -> str:
    """
    Retrieve the feature name from a feature folder path.

    Args:
        feature_folder (str): The path to the feature folder.

    Returns:
        str: The name of the feature.
    """
    # Extract the feature name from the folder path
    return str(feature_folder)
