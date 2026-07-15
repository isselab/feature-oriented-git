"""Programmatic throwaway git repositories for tests."""

from pathlib import Path

import pygit2

_SIG_NAME = "Test User"
_SIG_EMAIL = "test@example.com"


class RepoBuilder:
    """Builds a real git repository step by step (commit, branch, merge)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.repo = pygit2.init_repository(str(path))
        self._clock = 1_700_000_000

    @property
    def default_branch(self) -> str:
        """Name of the branch HEAD was born on."""
        return self.repo.head.shorthand

    def _signature(self) -> pygit2.Signature:
        self._clock += 60
        return pygit2.Signature(_SIG_NAME, _SIG_EMAIL, self._clock, 0)

    def write(self, relpath: str, content: str) -> None:
        """Write a file inside the working tree, creating parent directories."""
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(
        self,
        message: str,
        files: dict[str, str] | None = None,
        remove: list[str] | None = None,
    ) -> str:
        """Write the given files, stage everything, and commit; returns the sha."""
        for relpath, content in (files or {}).items():
            self.write(relpath, content)
        index = self.repo.index
        for relpath in remove or []:
            (self.path / relpath).unlink()
            index.remove(relpath)
        index.add_all()
        index.write()
        tree = index.write_tree()
        parents = [] if self.repo.head_is_unborn else [self.repo.head.target]
        sig = self._signature()
        oid = self.repo.create_commit("HEAD", sig, sig, message, tree, parents)
        return str(oid)

    def amend(self, message: str, files: dict[str, str] | None = None) -> str:
        """Amend the HEAD commit (new message and/or files); returns the new sha."""
        for relpath, content in (files or {}).items():
            self.write(relpath, content)
        index = self.repo.index
        index.add_all()
        index.write()
        tree = index.write_tree()
        head = self.repo[self.repo.head.target].peel(pygit2.Commit)
        oid = self.repo.amend_commit(head, "HEAD", message=message, tree=tree)
        return str(oid)

    def branch(self, name: str, at: str | None = None) -> None:
        """Create a branch at the given sha (default: current HEAD)."""
        target = self.repo[at] if at else self.repo[self.repo.head.target]
        self.repo.branches.local.create(name, target.peel(pygit2.Commit))

    def switch(self, name: str) -> None:
        """Check out an existing branch."""
        self.repo.checkout(f"refs/heads/{name}")

    def merge(self, other_branch: str, message: str) -> str:
        """Merge another branch into the current one (must not conflict)."""
        their = self.repo.branches.local[other_branch].peel(pygit2.Commit)
        self.repo.merge(their.id)
        if self.repo.index.conflicts is not None:
            raise RuntimeError(f"fixture merge of {other_branch!r} conflicted")
        tree = self.repo.index.write_tree()
        sig = self._signature()
        oid = self.repo.create_commit(
            "HEAD", sig, sig, message, tree, [self.repo.head.target, their.id]
        )
        self.repo.state_cleanup()
        self.repo.checkout_head(strategy=pygit2.enums.CheckoutStrategy.FORCE)
        return str(oid)
