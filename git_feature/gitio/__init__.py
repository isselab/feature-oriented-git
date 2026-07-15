"""Thin pygit2 wrappers: repository access, diffs, history walks, ref I/O."""

from .blame import blob_lines, line_origins, tree_paths
from .diff import FileDiff, Hunk, commit_diff, resolve_commit, worktree_diff
from .history import iter_all_commits, iter_commits, iter_range
from .patchid import patch_id
from .refio import RefUpdateConflict, compare_and_swap_ref, read_ref, write_ref
from .repo import RepositoryNotFound, open_repository

__all__ = [
    "FileDiff",
    "Hunk",
    "RefUpdateConflict",
    "RepositoryNotFound",
    "blob_lines",
    "commit_diff",
    "compare_and_swap_ref",
    "iter_all_commits",
    "iter_commits",
    "iter_range",
    "line_origins",
    "open_repository",
    "patch_id",
    "read_ref",
    "resolve_commit",
    "tree_paths",
    "worktree_diff",
    "write_ref",
]
