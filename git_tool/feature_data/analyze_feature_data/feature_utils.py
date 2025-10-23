"""
All functions working on feature-uuids that help to get data in a structured format
based on a given feature
"""

import uuid
from datetime import datetime
from typing import Generator, Optional

from git import Commit

from git_tool.feature_data.models_and_context.fact_model import (
    get_fact_from_featurefile,
)
from git_tool.feature_data.models_and_context.repo_context import (
    FEATURE_BRANCH_NAME,
    repo_context,
)


class FeatureNameNotFoundException(Exception): ...


def get_associated_files(feature_uuid: str) -> Generator[str, None, None]:
    """Search for all files belonging to a certain feature_uuid. Assume that all files are
    stored in the folder with the name feature_uuid

    Args:
        feature_uuid (str): Identifier for feature

    Returns:
        Generator[str, None, None]: Iterator over all filenames associated with the feature
    """
    with repo_context() as repo:
        # repo.git always allows to execute git commands, see
        # https://gitpython.readthedocs.io/en/stable/tutorial.html#using-git-directly
        result: str = repo.git.ls_tree(
            "-r", "--name_only", FEATURE_BRANCH_NAME, feature_uuid
        )
        files: list[str] = (
            result.split()
        )  # outputs one string. Filenames are separated by whitespace-like delimiters
        return files


def get_featurename_from_uuid(
    uuid: uuid.UUID,
) -> str | list[tuple[datetime, str]]:
    """
    Look through all changes associated with the feature uuid and check which ones
    changed the name

    Arguments:
        uuid -- Feature UUID

    Raises:
        FeatureNameNotFoundException: No Name Found for the feature

    Returns:
       If there is just one name, return the name. If there are multiple names, return
       tuples of name and timestamp so the context can decide which name to look for
    """
    feature_files = get_associated_files(feature_uuid=uuid)
    names: list[tuple[datetime, str]] = []
    for file in feature_files:
        fact = get_fact_from_featurefile(file)
        if fact.changes.name_change:
            names.append((fact.date, fact.changes.name_change.feature_name))
    if len(names) == 0:
        raise FeatureNameNotFoundException
    elif len(names) == 1:
        return names[0][1]
    else:
        return names


def get_uuid_for_featurename(name: str) -> uuid.UUID:
    """
    git log feature_metadata -S <string>  --name-only --pretty=format:
    lists the filenames of all files that contain the given string.
    They are sorted by commit and separated by a newline for each commit

    Arguments:
        name -- Featurename that is searched for
    Returns:
        UUID associated with the feautre
    """
    with repo_context() as repo:
        repo.git.log(
            FEATURE_BRANCH_NAME,
            f"-S {name}",
            name_only=True,
            oneline=True,
            pretty="format:",
        )
    # TODO this is not implemented correctly
    return name

# Usages: FEATURE INFO
def get_current_branchname() -> str:
    with repo_context() as repo:
        return repo.active_branch

# Usages: FEATURE INFO
def get_commits_for_feature_on_other_branches(
    feature_commits: set[str],
    current_branch: str = get_current_branchname(),
    other_branch: str = "",
) -> set[Commit]:
    """
    Find commits on other branches that affect the same feature but are not present on the current branch.

    Args:
        repo: The Git repository object.
        feature_commits: A set of commit IDs associated with the feature.
        current_branch: The name of the current branch.
        other_branch: Optional limitatation of the branch that should be compared to

    Returns:
        A set of commit IDs that are on other branches but not on the current branch.
    """
    with repo_context() as repo:
        # Normalize the feature commits to full hashes if they are not already
        feature_commits = set(
            repo.git.rev_parse(commit) for commit in feature_commits
        )
        if other_branch:
            other_branches = [other_branch]
        else:
            other_branches = [
                branch.name
                for branch in repo.branches
                if branch.name != current_branch
            ]
        updatable_commits = set()

        for branch in other_branches:
            branch_commits = set(
                repo.git.log(
                    f"{current_branch}..{branch}", "--pretty=%H"
                ).split("\n")
            )
            relevant_commits = branch_commits.intersection(feature_commits)
            if relevant_commits:
                updatable_commits.update(relevant_commits)

        updatable_commit_objects = {
            repo.commit(commit_hash) for commit_hash in updatable_commits
        }

        return updatable_commit_objects


def get_all_features() -> list[str]:
    """
    Return list of all feature names. A feature name is equivalent to its folder name
    on the top level of the feature-metadata branch

    Returns:
        list[str]: List of folder names (features) at the top level.
    """
    with repo_context() as repo:
        folder_string = repo.git.ls_tree(
            "-d", "--name-only", FEATURE_BRANCH_NAME
        )
        folders = folder_string.splitlines()
        return folders

# Usages: FEATURE COMMITS
def get_commits_with_feature() -> list[str]:
    """
    Return a list of short ids of commits that are assoicated
    with at least one feature.

    Returns:
        list[str]
    """
    all_features = get_all_features()
    commit_ids = set()

    with repo_context() as repo:
        for feature in all_features:
            feature_files = repo.git.ls_tree(
                "-d", "--name-only", f"{FEATURE_BRANCH_NAME}:{feature}"
            ).splitlines()

            for commit_folder in feature_files:
                commit_id = commit_folder
                commit_ids.add(commit_id)
    return list(commit_ids)
