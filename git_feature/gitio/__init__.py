"""Thin pygit2 wrappers: repository access, diffs, history walks, ref I/O."""

from .diff import FileDiff, Hunk, commit_diff, resolve_commit
from .history import iter_all_commits, iter_commits, iter_range
from .refio import RefUpdateConflict, compare_and_swap_ref, read_ref, write_ref
from .repo import RepositoryNotFound, open_repository

__all__ = [
    "FileDiff",
    "Hunk",
    "RefUpdateConflict",
    "RepositoryNotFound",
    "commit_diff",
    "compare_and_swap_ref",
    "iter_all_commits",
    "iter_commits",
    "iter_range",
    "open_repository",
    "read_ref",
    "resolve_commit",
    "write_ref",
]
