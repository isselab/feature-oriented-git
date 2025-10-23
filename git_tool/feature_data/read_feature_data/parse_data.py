"""
    All functions needed to parse data from feature files.

"""

import logging
from typing import Generator, List, Optional, Set, Tuple

from git import Commit

from git_tool.feature_data.models_and_context.fact_model import FeatureFactModel
from git_tool.feature_data.models_and_context.repo_context import (
    FEATURE_BRANCH_NAME,
    branch_folder_list,
    repo_context,
)

# Usages: FEATURE INFO-ALL
def _get_feature_uuids() -> list[str]:
    """
    Each feature has its own folder where the foldername is equivalent to the uuid that the
    feature has.
    Get all directories at the upper level of the Feature data branch

    Returns:
        list[str]: UUIDs of Features
    """
    with repo_context() as repo:
        folder_string = repo.git.ls_tree(
            "-d", FEATURE_BRANCH_NAME, name_only=True
        )
        folders = folder_string.split()
        return folders


def _get_associated_files(feature_uuid: str, ref_commit: str) -> list[str]:
    return []


def _get_fact_from_featurefile(file: str):
    with open(file, "r") as f:
        return FeatureFactModel.model_validate_json(f.read())


def get_metadata(
    feature_uuid: str, ref_commit: Optional[str] = None
) -> list[FeatureFactModel]:
    """
    Get all facts about the feature that are true for ref_commit.
    If ref_commit is not specified, use latest commit.
    Output describes cummulation of all facts and can be used as foundation to display
    feature evolution.
    Only facts that are merged in the main branch are used. Currently, the name must be main.

    Args:
        feature_uuid (str): Feature Reference
        ref_commit (Optional[str]): Commit Identifier which is the last one

    Returns:
        CumulatedFactsModel: List of all facts sorted chronologically
    """
    facts = [
        _get_fact_from_featurefile(f)
        for f in _get_associated_files(
            feature_uuid=feature_uuid, ref_commit=ref_commit
        )
    ]
    facts = [x for x in facts if x is not None]
    return facts


def get_feature_log(feature_uuid: str):
    """
    Output all commits from a feature to the command line.
    # TODO Still need to incorpoarte all possible flags of git log somehow

    Args:
        feature_uuid (str): Reference for feature
    """
    commit_ids = [
        fact.commit for fact in get_metadata(feature_uuid=feature_uuid)
    ]
    print(commit_ids)
    with repo_context() as repo:
        print(
            repo.git.log(
                "--no-walk",
                "--decorate",
                "--color",
                commit_ids,
            )
        )

# Usages: compare_branches.py (potentially FEATURE BLAME)
def get_features_touched_by_commit(commit: Commit) -> Set[str]:
    """
    Retrieves the set of features touched by a given commit.

    Args:
        commit (Commit): The commit to analyze.

    Returns:
        Set[str]: Set of features touched by the commit.
    """
    # Annahme: Diese Funktion wertet die Änderungen in einem Commit aus und extrahiert die Features.
    feature_facts = extract_facts_from_commit(commit)
    features = set()
    for fact in feature_facts:
        features.update(fact.features)
    return features


def get_feature_sets_for_branch(branch_name: str) -> List[Set[str]]:
    """
    Retrieves the sets of features touched together in a branch.

    Args:
        branch_name (str): The branch to analyze.

    Returns:
        List[Set[str]]: List of sets of features touched together in the branch.
    """
    with repo_context() as repo:
        commits = list(repo.iter_commits(branch_name))
        feature_sets = [
            get_features_touched_by_commit(commit) for commit in commits
        ]
    # TODO optimize: for each feature check for each commit if that commit is on the branch. else there will be redundant checks
    return feature_sets


def is_commit_compatible_with_branch(
    commit: Commit, branch_name: str
) -> Tuple[bool, Set[str]]:
    """
    Checks if a commit is compatible with a branch.

    Args:
        commit (Commit): The commit to check.
        branch_name (str): The branch to check against.

    Returns:
        Tuple[bool, Set[str]]: Whether the commit is compatible and the set of features it touches.
    """
    commit_features = get_features_touched_by_commit(commit)
    branch_feature_sets = get_feature_sets_for_branch(branch_name)

    for feature_set in branch_feature_sets:
        if commit_features.issubset(feature_set):
            return (True, commit_features)
    return (False, commit_features)


def display_results_and_check_warnings(commit: Commit, branch_name: str):
    """
    Displays the feature set result to the user and gives warnings or errors depending on the result.

    Args:
        commit (Commit): The commit to analyze.
        branch_name (str): The branch to check against.
    """
    is_compatible, commit_features = is_commit_compatible_with_branch(
        commit, branch_name
    )
    if is_compatible:
        print(f"Commit {commit} is compatible with branch {branch_name}.")
    else:
        print(f"Commit {commit} is NOT compatible with branch {branch_name}.")
        print(f"Touched features: {commit_features}")
        logging.warning(
            f"Commit {commit} touches features not fully compatible with branch {branch_name}."
        )


def extract_facts_from_commit(commit: Commit) -> List[FeatureFactModel]:
    """
    Extracts facts from a given commit.

    Args:
        commit (Commit): The commit to analyze.

    Returns:
        List[FeatureFactModel]: List of facts extracted from the commit.
    """
    facts = []
    with branch_folder_list() as (features, repo):
        for feature in features:
            try:
                commits = repo.git.ls_tree(
                    "-r", "--name-only", FEATURE_BRANCH_NAME, feature
                ).split()
                associated_w_commit = [x for x in commits if str(commit) in x]
                for file in associated_w_commit:
                    file_content = repo.git.show(
                        f"{FEATURE_BRANCH_NAME}:{file}"
                    )
                    facts.append(
                        FeatureFactModel.model_validate_json(file_content)
                    )
            except:
                print("error")
    return facts


if __name__ == "__main__":
    # get_metadata("abc")
    # logging.info("Get Metadata success")
    # get_feature_log("abc")
    ids = _get_feature_uuids()
    print(ids)
    feature = input(f"Select one of {ids}\n")
    # if len(ids) >= 1:
    #     _resolve_feature_name(ids[0])
    get_feature_log(feature)
