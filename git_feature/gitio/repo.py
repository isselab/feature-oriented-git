"""Repository discovery and access."""

import os
from pathlib import Path

import pygit2


class RepositoryNotFound(Exception):
    """Raised when no git repository can be discovered from the given path."""


def open_repository(path: str | Path | None = None) -> pygit2.Repository:
    """Open the repository containing `path` (default: cwd), worktree-safe."""
    start = str(path) if path is not None else os.getcwd()
    try:
        found = pygit2.discover_repository(start)
    except Exception as exc:
        raise RepositoryNotFound(f"no git repository found from {start!r}") from exc
    if found is None:
        raise RepositoryNotFound(f"no git repository found from {start!r}")
    return pygit2.Repository(found)
