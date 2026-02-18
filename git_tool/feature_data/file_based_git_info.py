"""
Functions to retrieve git information for a specific file rather than starting with
a list of features or commits
"""

from typing import Optional

from git_tool.feature_data.models_and_context.repo_context import (
    get_current_branch,
    repo_context,
)


def get_commits_for_file(
    file_name: str, branch_name: Optional[str] = None
) -> list[str]:
    """
    Search git history for commits targeting a file, then collecting the commit ids.
    If no branchname is given, the current branch is used
    """
    with repo_context() as repo:
        if branch_name is None:
            branch_name = get_current_branch()
        commit_id_only = "--pretty=format:%H"
        try:
            commits = repo.git.log(branch_name, commit_id_only, "--", file_name)
            return commits.split("\n")
        except Exception:
            # this happens for example if no commits exists
            return []
