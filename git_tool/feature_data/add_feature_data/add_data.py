"""
This wraps the fast-import utils and writes the necessary code for determining all data artefacts
needed to add a FeatureFact to the respective metadata branch.
"""

import hashlib
import os
import tempfile
from pathlib import Path

from git import Commit

from git_tool.feature_data.analyze_feature_data.feature_utils import (
    get_uuid_for_featurename,
)
from git_tool.feature_data.models_and_context.fact_model import FeatureFactModel
from git_tool.feature_data.models_and_context.repo_context import (
    FEATURE_BRANCH_NAME,
    repo_context,
)
from git_tool.feature_data.utils.fast_import_utils import (
    AccumulatedCommitData,
    FastImportCommitData,
    to_fast_import_format,
)


def generate_fact_file_path(fact: FeatureFactModel) -> list[Path]:
    """
    The fact file is stored in the folder <feature-uuid>/<commit-hash>/<fact-filename>
    Each of these information is computed in this function

    Args:
        fact (FeatureFactModel): Information used to derive path

    Returns:
        list[str]: All paths where the associated fact needs to be stored
    """
    feature_uuids = [
        get_uuid_for_featurename(feature) for feature in fact.features
    ]
    fact_json = fact.model_dump_json()
    sha1_hash = hashlib.sha1(fact_json.encode("utf-8")).hexdigest()

    paths = [
        Path(uuid)
        .joinpath(Path(fact.commit))
        .joinpath(
            f"{fact.date.isoformat(timespec='minutes').replace(':', '-')}-{sha1_hash[:7]}"
        )
        .as_posix()
        for uuid in feature_uuids
    ]
    return paths


def generate_fact_commit_data(
    fact: FeatureFactModel,
    branch_name: str = FEATURE_BRANCH_NAME,
    commit_ref: Commit = None,
):
    commit_data = AccumulatedCommitData(
        branch_name=branch_name,
        committer_name=commit_ref.author.name if commit_ref is not None else "",
        committer_email=(
            commit_ref.author.email if commit_ref is not None else ""
        ),
        message=f"Generate fact for {str(commit_ref)}\n\nTouching features {','.join(fact.features)}",
        add_files=[
            FastImportCommitData(
                file_path=file,
                content=fact.model_dump_json(),
            )
            for file in generate_fact_file_path(fact=fact)
        ],
    )
    return commit_data


def add_fact_to_metadata_branch(
    fact: FeatureFactModel,
    branch_name: str = FEATURE_BRANCH_NAME,
    commit_ref: Commit = None,
):
    """
    Create a new commit by creating a temporary file using the fast-import format.
    The commit data is derived from the fact information.
    :param fact Structured information used to generate the commit content
    :param branch-name reference for git which is used to determine the branch that a commit is added to
    :param commit_ref Optional parameter that can include more informatino for the commit content, specifying which commit the metadata describes

    """
    commit_data = generate_fact_commit_data(fact, branch_name, commit_ref)
    fast_import_content = to_fast_import_format(commits=[commit_data])
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w", encoding="utf-8", newline="\n"
        ) as temp_file:
            temp_file.write(fast_import_content)
            temp_file_path = temp_file.name

        with repo_context() as repo:
            with open(temp_file_path, "r") as file:
                repo.git.fast_import(istream=file)
    except Exception as e:
        print("error\n", e)
    finally:
        if temp_file_path:
            os.remove(temp_file_path)
    return commit_data
