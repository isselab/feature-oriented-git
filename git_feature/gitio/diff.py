"""Commit diffs exposed as plain data (no pygit2 types leak upward)."""

from dataclasses import dataclass

import pygit2


@dataclass(frozen=True)
class Hunk:
    """One contiguous change: spans are (start_line, line_count), 1-based."""

    old_span: tuple[int, int]
    new_span: tuple[int, int]
    header: str
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]


@dataclass(frozen=True)
class FileDiff:
    """All hunks of one file in a commit's diff against its first parent."""

    old_path: str | None
    new_path: str | None
    status: str
    hunks: tuple[Hunk, ...]


def resolve_commit(repo: pygit2.Repository, rev: str | pygit2.Commit) -> pygit2.Commit:
    """Resolve a revision string (or pass through a Commit) to a Commit object."""
    if isinstance(rev, pygit2.Commit):
        return rev
    return repo.revparse_single(str(rev)).peel(pygit2.Commit)


def commit_diff(
    repo: pygit2.Repository, rev: str | pygit2.Commit, context_lines: int = 0
) -> list[FileDiff]:
    """Diff a commit against its first parent (or the empty tree for a root commit)."""
    commit = resolve_commit(repo, rev)
    if commit.parents:
        diff = repo.diff(commit.parents[0], commit, context_lines=context_lines)
    else:
        diff = commit.tree.diff_to_tree(swap=True, context_lines=context_lines)
    diff.find_similar()
    return _convert_diff(diff)


def worktree_diff(repo: pygit2.Repository, context_lines: int = 0) -> list[FileDiff]:
    """Diff HEAD against the working directory, staged and unstaged changes included."""
    diff = repo.diff("HEAD", context_lines=context_lines)
    return _convert_diff(diff)


def diff_to_workdir(
    repo: pygit2.Repository, rev: str | pygit2.Commit, context_lines: int = 0
) -> list[FileDiff]:
    """Diff a commit's tree against the working directory, untracked files included."""
    commit = resolve_commit(repo, rev)
    flags = (
        pygit2.enums.DiffOption.INCLUDE_UNTRACKED
        | pygit2.enums.DiffOption.SHOW_UNTRACKED_CONTENT
        | pygit2.enums.DiffOption.RECURSE_UNTRACKED_DIRS
    )
    diff = repo.diff(str(commit.id), flags=flags, context_lines=context_lines)
    return _convert_diff(diff)


def _convert_diff(diff: pygit2.Diff) -> list[FileDiff]:
    files = []
    for patch in diff:
        if patch is None:
            continue
        delta = patch.delta
        hunks = tuple(_convert_hunk(h) for h in patch.hunks) if not delta.is_binary else ()
        files.append(
            FileDiff(
                old_path=delta.old_file.path if delta.status_char() != "A" else None,
                new_path=delta.new_file.path if delta.status_char() != "D" else None,
                status=delta.status_char(),
                hunks=hunks,
            )
        )
    return files


def _convert_hunk(hunk: pygit2.DiffHunk) -> Hunk:
    added = []
    removed = []
    for line in hunk.lines:
        if line.origin == "+":
            added.append(line.content.removesuffix("\n"))
        elif line.origin == "-":
            removed.append(line.content.removesuffix("\n"))
    return Hunk(
        old_span=(hunk.old_start, hunk.old_lines),
        new_span=(hunk.new_start, hunk.new_lines),
        header=hunk.header.removesuffix("\n"),
        added_lines=tuple(added),
        removed_lines=tuple(removed),
    )
