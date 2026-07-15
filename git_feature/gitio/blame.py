"""Blame and tree-content access used by the region resolver."""

from collections.abc import Iterator

import pygit2

from .diff import resolve_commit


def line_origins(repo: pygit2.Repository, rev: str | pygit2.Commit, path: str) -> list[str] | None:
    """Per-line origin commit sha of a file at a revision, or None if the file is absent."""
    commit = resolve_commit(repo, rev)
    lines = blob_lines(repo, commit, path)
    if lines is None:
        return None
    blame = repo.blame(path, newest_commit=commit.id)
    origins = [""] * len(lines)
    for hunk in blame:
        for i in range(hunk.lines_in_hunk):
            index = hunk.final_start_line_number - 1 + i
            if 0 <= index < len(origins):
                origins[index] = str(hunk.orig_commit_id)
    return origins


def blob_lines(repo: pygit2.Repository, rev: str | pygit2.Commit, path: str) -> list[str] | None:
    """Text lines of a file at a revision, or None if absent or binary."""
    commit = resolve_commit(repo, rev)
    try:
        entry = commit.tree[path]
    except KeyError:
        return None
    obj = repo[entry.id]
    if not isinstance(obj, pygit2.Blob) or obj.is_binary:
        return None
    try:
        text = obj.data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text.splitlines()


def tree_paths(repo: pygit2.Repository, rev: str | pygit2.Commit) -> Iterator[str]:
    """Yield every file path in a revision's tree."""
    commit = resolve_commit(repo, rev)
    yield from _walk_tree(repo, commit.tree, "")


def _walk_tree(repo: pygit2.Repository, tree: pygit2.Tree, prefix: str) -> Iterator[str]:
    for entry in tree:
        obj = repo[entry.id]
        name = f"{prefix}{entry.name}"
        if isinstance(obj, pygit2.Tree):
            yield from _walk_tree(repo, obj, f"{name}/")
        elif isinstance(obj, pygit2.Blob):
            yield name
