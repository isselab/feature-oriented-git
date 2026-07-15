"""Revision-walk helpers."""

from collections.abc import Iterator

import pygit2

from .diff import resolve_commit


def iter_commits(
    repo: pygit2.Repository,
    rev: str | None = None,
    exclude: list[str] | None = None,
) -> Iterator[pygit2.Commit]:
    """Yield commits reachable from `rev` (default HEAD), newest first."""
    tip = resolve_commit(repo, rev or "HEAD")
    walker = repo.walk(tip.id, pygit2.enums.SortMode.TOPOLOGICAL)
    for ex in exclude or []:
        walker.hide(resolve_commit(repo, ex).id)
    yield from walker


def iter_range(repo: pygit2.Repository, range_spec: str) -> Iterator[pygit2.Commit]:
    """Yield commits in a `base..tip` range, newest first."""
    base, sep, tip = range_spec.partition("..")
    if not sep:
        raise ValueError(f"not a range: {range_spec!r} (expected 'base..tip')")
    return iter_commits(repo, tip or "HEAD", exclude=[base])


def iter_all_commits(repo: pygit2.Repository) -> Iterator[pygit2.Commit]:
    """Yield every commit reachable from any reference, deduplicated."""
    walker = None
    for name in repo.references:
        ref = repo.references[name]
        try:
            target = ref.peel(pygit2.Commit)
        except (pygit2.GitError, pygit2.InvalidSpecError, KeyError):
            continue
        if walker is None:
            walker = repo.walk(target.id, pygit2.enums.SortMode.TOPOLOGICAL)
        else:
            walker.push(target.id)
    if walker is not None:
        yield from walker
