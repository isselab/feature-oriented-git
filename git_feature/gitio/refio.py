"""Reference reading and guarded writing."""

import pygit2


class RefUpdateConflict(Exception):
    """Raised when a guarded ref update finds an unexpected current target."""


def read_ref(repo: pygit2.Repository, name: str) -> str | None:
    """Return the commit sha a ref points to, or None if the ref doesn't exist."""
    ref = repo.references.get(name)
    if ref is None:
        return None
    return str(ref.peel(pygit2.Commit).id)


def write_ref(repo: pygit2.Repository, name: str, target: str) -> None:
    """Point a ref at a commit, creating or force-updating it."""
    repo.references.create(name, target, force=True)


def compare_and_swap_ref(
    repo: pygit2.Repository, name: str, target: str, expected_old: str | None
) -> None:
    """Update a ref only if it currently points at `expected_old` (None = must not exist)."""
    current = read_ref(repo, name)
    if current != expected_old:
        raise RefUpdateConflict(f"{name}: expected {expected_old}, found {current}")
    if current is None:
        repo.references.create(name, target)
    else:
        repo.references[name].set_target(target)
