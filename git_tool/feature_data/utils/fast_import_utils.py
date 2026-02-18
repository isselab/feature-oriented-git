"""
Module that wraps git fast-import -> https://git-scm.com/docs/git-fast-import
This is the best way to add commits to a branch which is currently not checked out,
which is exactly what we try to prevent in this setup.
Here, all the boilerplate code goes that creates the commit meta data and makes sure
that the content is added as expected
"""

from datetime import datetime
from pathlib import Path
from typing import List

from git import GitCommandError
from pydantic import BaseModel, EmailStr

from git_tool.feature_data.models_and_context import repo_context


class FastImportCommitData(BaseModel):
    """
    Datastructure to store the file and its expected contents.

    """

    permissions: str = "644"  # all files have same permissions
    file_path: str | Path
    content: str

    @property
    def content_length(self) -> int:
        return len(self.content.encode("utf-8"))


class AccumulatedCommitData(BaseModel):
    """
    Holds all meta information for the commit as well as
    all files that should be added.
    Because we are working with immutable filecontents
    to ensure absence of merge conflicts, we only have
    added contents.
    """

    branch_name: str
    committer_name: str
    committer_email: EmailStr
    commit_datetime: datetime = datetime.now()
    message: str
    add_files: List[FastImportCommitData]

    @property
    def message_length(self) -> int:
        return len(self.message.encode("utf-8"))

    @property
    def timestamp(self) -> int:
        """
        Format according to fast-import specs
        """
        return int(self.commit_datetime.timestamp())

    @property
    def timezone(self) -> str:
        offset = self.commit_datetime.utcoffset()
        if offset is None:
            return "+0000"
        total_minutes = int(offset.total_seconds() // 60)
        hours, minutes = divmod(abs(total_minutes), 60)
        sign = "+" if total_minutes >= 0 else "-"
        return f"{sign}{hours:02}{minutes:02}"

    def to_partial_fast_import_format(self) -> str:
        """
        This function returns the string as expected for one change to the branch.
        Please note that this is not a fully viable fast import text strig, as it
        is missing the done tag.

        It includes the following information, derived from the object:
        - Commit reference: Specifies the branch the commit is for (usually automatically derived, metadata branch).
        - Committer: The name and email of the committer along with the timestamp and timezone.
        - Commit message length and message: The length of the commit message and the actual message.
        - From: Indicates the parent commit reference (if it exists). Done by using the repo context and looking for the last commit on the branch
        - File changes: Specifies the permissions, path, and content of the files being added/modified.

        Returns:
            str: Fast-import compatible format. Still lacking info. Needs to be used with
            to_fast_import_format
        """
        result = []
        result.append(f"commit refs/heads/{self.branch_name}")
        result.append(
            f"committer {self.committer_name} <{self.committer_email}> {self.timestamp} {self.timezone}"
        )
        result.append(f"data {self.message_length}")
        result.append(self.message)
        with repo_context.repo_context() as repo:
            try:
                from_message: str = f"from {repo.git.rev_parse(f'refs/heads/{self.branch_name}')}"
                result.append(from_message)
            except GitCommandError:
                print(
                    "This will be the first commit on the feature data branch"
                )
        for change in self.add_files:
            result.append(f"M {change.permissions} inline {change.file_path}")
            # print(
            #     "Fileline is ",
            #     f"M {change.permissions} inline {change.file_path}",
            # )
            result.append(f"data {change.content_length}")
            result.append(change.content)
        return "\n".join(result)


def to_fast_import_format(commits: list[AccumulatedCommitData]) -> str:
    """
    This function converts multiple CommitData objects into a fast-import compatible format.

    Returns:
        str: Full fast import format string including the done tag.
    """
    result = [commit.to_partial_fast_import_format() for commit in commits]
    result.append("done")
    return "\n".join(result) + "\n"


# Example Code. This cannot be executed in this context
if __name__ == "__main__":
    commit_change = FastImportCommitData(
        file_path="new2",
        content="This bug really sucks2",
    )

    commit = AccumulatedCommitData(
        branch_name="test",
        committer_name="Tabea",
        committer_email="agserm@gmail.com",
        message="Added 'This bug really sucks'",
        add_files=[commit_change],
    )

    fast_import_data = to_fast_import_format([commit])

    # Schreibe die Daten in eine Datei
    with open("git_fast_import_data.txt", "w") as f:
        f.write(fast_import_data)

    print("git fast-import data written to git_fast_import_data.txt")
