import os
import re
import tempfile
from pathlib import PurePosixPath

import typer
from git import Blob, Repo, Tree

from git_tool.feature_data.models_and_context.repo_context import (
    FEATURE_BRANCH_NAME,
    repo_context,
)


def derive_variant(
    name: str = typer.Argument(..., help="Name of the variant"),
    features: list[str] = typer.Option(
        ...,
        "--features",
        "-f",
        help="One or more features to include",
    ),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Refresh the variant"
    ),
):
    """Derive a variant from the provided feature set."""
    with repo_context() as repo:
        if repo.is_dirty(untracked_files=True):
            raise RuntimeError(
                "Repository is not clean. Commit or stash your changes first."
            )

        ref_name = f"refs/heads/variant/{name}"
        target_features: set[str] = set(features)

        existing_ref = None
        try:
            existing_ref = repo.commit(ref_name)
        except:
            pass

        if existing_ref is not None and not refresh:
            raise RuntimeError(
                f"Variant branch '{ref_name}' already exists. Pass --refresh to overwrite."
            )

        # Load metadata tree once to avoid re-resolving per commit
        metadata_tree = repo.commit(f"refs/heads/{FEATURE_BRANCH_NAME}").tree

        head_tree = repo.head.commit.tree
        new_tree_oid = build_variant_tree(
            repo, head_tree, PurePosixPath(""), target_features, metadata_tree
        )

        commit_msg = f"Variant derivation with features: '{features}'"
        new_commit_oid = repo.git.commit_tree(
            new_tree_oid, m=commit_msg
        ).strip()
        repo.git.update_ref(ref_name, new_commit_oid)


def build_variant_tree(
    repo: Repo,
    tree: Tree,
    base_path: PurePosixPath,
    target_features: set[str],
    metadata_tree: Tree,
) -> str:
    mktree_lines: list[str] = []

    for item in tree:
        child_path = base_path / item.name

        if item.type == "blob":
            filtered = process_blob(
                repo, item, child_path, target_features, metadata_tree
            )
            # Skip committing the file if empty
            if not filtered or not filtered.strip():
                continue

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(filtered.encode())
                tmp_path = tmp.name

            try:
                new_sha = repo.git.hash_object("-w", tmp_path)
            finally:
                os.unlink(tmp_path)

            mktree_lines.append(f"{item.mode:06o} blob {new_sha}\t{item.name}")

        elif item.type == "tree":
            subtree_sha = build_variant_tree(
                repo, item, child_path, target_features, metadata_tree
            )
            mktree_lines.append(f"040000 tree {subtree_sha}\t{item.name}")

        else:
            mktree_lines.append(
                f"{item.mode:06o} {item.type} {item.hexsha}\t{item.name}"
            )

    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".mktree"
    ) as tmp:
        tmp.write("\n".join(mktree_lines))
        tmp_path = tmp.name

    try:
        with open(tmp_path) as f:
            new_tree_sha = repo.git.mktree(istream=f)
    finally:
        os.unlink(tmp_path)

    return new_tree_sha.strip()


def process_blob(
    repo: Repo,
    blob: Blob,
    path: PurePosixPath,
    target_features: set[str],
    metadata_tree: Tree,
) -> str:
    raw = blob.data_stream.read().decode("utf-8", errors="replace")
    lines = raw.splitlines(keepends=True)

    if not lines:
        return ""

    blame_output = repo.git.blame("HEAD", "--porcelain", "--", str(path))
    line_to_sha = _parse_blame_porcelain(blame_output)

    # Per-commit feature membership cache
    commit_cache: dict[str, bool] = {}

    result: list[str] = []
    for i, line in enumerate(lines):
        line_no = i + 1
        sha = line_to_sha.get(line_no)

        if sha is None:
            raise RuntimeError("Blame info missing for line!")

        if sha not in commit_cache:
            commit_cache[sha] = _commit_has_feature(
                sha, target_features, metadata_tree
            )

        if commit_cache[sha]:
            result.append(line)
        else:
            result.append("")

    return "".join(result)


def _parse_blame_porcelain(porcelain: str) -> dict[int, str]:
    line_to_sha: dict[int, str] = {}
    lines = porcelain.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Blame header starts with a 40-char hex
        if len(line) >= 40 and re.match(r"^[0-9a-f]{40}", line):
            parts = line.split()
            sha = parts[0]
            result_line = int(parts[2])
            line_to_sha[result_line] = sha
        i += 1
    return line_to_sha


def _commit_has_feature(
    sha: str, target_features: set[str], metadata_tree: Tree
) -> bool:
    for feature in target_features:
        try:
            metadata_tree[feature][sha]
            return True
        except KeyError:
            continue
    return False
