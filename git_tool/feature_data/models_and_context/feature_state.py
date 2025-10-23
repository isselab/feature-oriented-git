"""
To prepare messages and store the set of features used, we need to create a file that contains all feature data.
"""

from pathlib import Path
from typing import List

from git_tool.feature_data.models_and_context.repo_context import repo_context



def get_feature_file()-> Path:
    """
    Depending on whether the repo is a git worktree or a usual git repo, the resolution of the .git folder
    works differently
    """
    with repo_context() as repo:
        git_repo=  Path(repo.git.rev_parse("--show-toplevel")).resolve().joinpath(".git")
        if git_repo.is_file():
            return Path(repo.git.rev_parse("--show-toplevel")).resolve().joinpath(".FEATUREINFO")
        else:
            return git_repo.joinpath("FEATUREINFO")

def read_staged_featureset() -> List[str]:
    """
    Read the list of staged features from the FEATUREINFO file.

    Returns:
        List[str]: A list of staged features.
    """
    feature_file = get_feature_file()
    if not feature_file.exists():
        return []
    with feature_file.open(mode="r", encoding="utf-8") as f:
        features = set(line.strip() for line in f.readlines())
    return list(features)

# Usage: FEATURE ADD, ADD-FROM-STAGED
def write_staged_featureset(features: List[str]):
    """
    Write the list of staged features to the FEATUREINFO file.

    Args:
        features (List[str]): A list of features to be written.
    """
    if not get_feature_file().exists():
        get_feature_file().touch()
    with get_feature_file().open(mode="w+", encoding="utf-8") as f:
        for feature in features:
            f.write(f"{feature}\n")

def reset_staged_featureset():
    """
    Reset the FEATUREINFO file by clearing its content.
    """
    feature_file = get_feature_file()
    if feature_file.exists():
        feature_file.unlink()