from datetime import datetime, timedelta
import os
import tempfile
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Generator, Iterable, Tuple

import git
from dotenv import load_dotenv
import typer

load_dotenv(Path(__file__).parents[1].joinpath(".env").absolute())
FEATURE_BRANCH_NAME = os.getenv("BRANCH_NAME", "feature-metadata")
# FEATURE_BRANCH_NAME = "feature6-metadata"
MAIN_BRANCH_NAME = os.getenv("MAIN_BRANCH_NAME", "main")
REPO_PATH = os.getenv("REPO_PATH", os.getcwd())
assert FEATURE_BRANCH_NAME is not None
assert MAIN_BRANCH_NAME is not None
assert REPO_PATH is not None

# print(f"FEATURE_BRANCH_NAME: {FEATURE_BRANCH_NAME}")
# print(f"MAIN_BRANCH_NAME: {MAIN_BRANCH_NAME}")
# print(f"REPO_PATH: {REPO_PATH}")


def create_empty_branch(branch_name: str, repo: git.Repo) -> str:
    """
    Create an orphan branch without checking it out using fast-import. An orphan branch
    does not have any parent commits.

    Args:
        branch_name (str): The name of the branch to create.
        repo (git.Repo): The Git repository object.

    Returns:
        str: The fast-import script as a string.
    """
    timestamp = int(datetime.now().timestamp())
    committer_name = os.getenv("GIT_COMMITTER_NAME", "Unknown")
    committer_email = os.getenv("GIT_COMMITTER_EMAIL", "unknown@example.com")

    result = []
    result.append(f"commit refs/heads/{branch_name}")
    result.append(
        f"committer {committer_name} <{committer_email}> {timestamp} +0000"
    )
    result.append("data <<EOM")
    result.append(f"Initial empty commit for {branch_name}")
    result.append("EOM")

    fast_import_script = "\n".join(result)

    try:
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w", encoding="utf-8", newline="\n"
        ) as temp_file:
            temp_file.write(fast_import_script)
            temp_file_path = temp_file.name

        with open(temp_file_path, "r", encoding="utf-8") as file:
            repo.git.fast_import(istream=file)
            try:
                repo.git.push("-u", "origin", branch_name)
            except Exception:
                ...
                # If origin is not defined yet, I can't set an upstream. Will need to do this manually elsewhere
        print(f"Branch {branch_name} successfully created.")
    except Exception as e:
        print(f"Error while creating branch: {e}")
    finally:
        if temp_file_path:
            os.remove(temp_file_path)

    return fast_import_script


HOME_DIR = os.path.expanduser("~")
TIMESTAMP_FILE = os.path.join(HOME_DIR, ".feature_branch_timestamp.txt")


def get_last_execution_time():
    if os.path.exists(TIMESTAMP_FILE):
        with open(TIMESTAMP_FILE, "r") as f:
            try:
                return datetime.fromisoformat(f.read().strip())
            except ValueError:
                return None
    return None


def update_last_execution_time():
    with open(TIMESTAMP_FILE, "w") as f:
        f.write(datetime.now().isoformat())


def ensure_feature_branch(func):
    """
    Decorator to ensure that the feature branch is created if it does not exist.
    This will only be executed once, even if the context manager is called multiple times.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        last_execution_time = get_last_execution_time()
        repo = git.Repo(REPO_PATH)
        current_time = datetime.now()
        # print("Executing ensure feautre branch")
        if last_execution_time is None or (
            (current_time - last_execution_time) > timedelta(minutes=5)
        ):
            update_last_execution_time()
            if FEATURE_BRANCH_NAME not in repo.heads:
                try:
                    repo.git.branch(
                        FEATURE_BRANCH_NAME, f"origin/{FEATURE_BRANCH_NAME}"
                    )
                    typer.echo(
                        f"Branch {FEATURE_BRANCH_NAME} created locally from origin."
                    )
                except git.GitCommandError:
                    typer.echo(
                        f"Branch {FEATURE_BRANCH_NAME} does not exist on origin. Creating an empty branch."
                    )
                    create_empty_branch(FEATURE_BRANCH_NAME, repo)
            try:
                typer.echo("Fetching new feature-metadata")
                repo.git.fetch("origin", FEATURE_BRANCH_NAME)
            except:
                print("Origin does not have ", FEATURE_BRANCH_NAME)
        return func(*args, **kwargs)

    return wrapper


@ensure_feature_branch
@contextmanager
def repo_context(repo_path=REPO_PATH):
    repo = git.Repo(repo_path)
    try:
        yield repo
    finally:
        del repo


@contextmanager
def branch_folder_list(
    branch: str = FEATURE_BRANCH_NAME, repo_path: str = REPO_PATH
) -> Generator[Tuple[Iterable[Path], git.Repo], None, None]:
    """
    Get all folders in a branch. Standard is to list all feature folders
    in the feature metadata branch.

    Args:
        branch (str): Branch that is analysed for folders
        repo_path (str): Path to git repo

    Yields:
        Tuple[Iterable[Path], git.Repo]: A tuple where the first element is an
        iterable of feature folder paths as pathlib.Path objects, and the second element is the git repository object.
    """
    with repo_context(repo_path) as repo:
        try:
            feature_folders = repo.git.ls_tree(
                "-d", "--name-only", branch
            ).split("\n")
            yield feature_folders, repo
        finally:
            pass


def get_current_branch() -> str:
    with repo_context() as repo:
        return repo.active_branch.name


def sync_feature_branch():
    with repo_context() as repo:
        remote_name = "origin"
        try:
            print(f"Fetching {FEATURE_BRANCH_NAME} from {remote_name}")
            repo.git.fetch(remote_name, FEATURE_BRANCH_NAME)
        except Exception as e:
            print(f"Error fetching the branch: {e}")
            return

        try:
            print(f"Pushing {FEATURE_BRANCH_NAME} to {remote_name}")
            repo.git.push(
                remote_name, FEATURE_BRANCH_NAME, force_with_lease=True
            )
        except Exception as e:
            # print(f"Error pushing the branch: {e}")
            print("Warning: Feature Updates could not be pushed to remote")


def get_yes_no_input(prompt: str) -> bool:
    while True:
        response = input(prompt).strip().lower()
        if response in ["yes", "y"]:
            return True
        elif response in ["no", "n"]:
            return False
        else:
            print("Please enter 'yes' or 'no'.")


def get_all_commits() -> list[str]:
    with repo_context() as repo:
        not_string = f"^refs/heads/{FEATURE_BRANCH_NAME}"
        all_commits = repo.git.log(
            "--all", not_string, "--no-merges", "--pretty=format:%H"
        )
        commit_list = all_commits.splitlines()
        return commit_list


def get_commit_title(commit_id: str) -> str:
    with repo_context() as repo:
        commit = repo.commit(commit_id)
        return commit.summary


def get_current_branchname() -> str:
    with repo_context() as repo:
        try:
            return repo.active_branch.name
        except TypeError:
            return "HEAD detached"
