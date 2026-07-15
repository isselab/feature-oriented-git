"""ChangeId minting and the SHA ↔ change-id map over the store."""

import pygit2
from ulid import ULID

from ..gitio import iter_all_commits, patch_id
from ..store.base import Store
from ..store.types import ChangeIdRecord


def mint_change_id() -> str:
    """Return a fresh ULID string."""
    return str(ULID())


class ChangeIdMap:
    """Typed access to the SHA ↔ change-id map persisted in a feature store."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def get(self, sha: str) -> ChangeIdRecord | None:
        """Return the record for a commit sha, or None if unmapped."""
        return self._store.get_changeid(sha)

    def shas_for(self, change_id: str) -> list[str]:
        """Return every sha mapped to a change-id (rewrites and cherry-picks share one)."""
        return [r.sha for r in self._store.iter_changeids() if r.change_id == change_id]

    def insert(
        self, sha: str, change_id: str | None = None, patch_id: str | None = None
    ) -> ChangeIdRecord:
        """Map a sha to a change-id (freshly minted unless given)."""
        record = ChangeIdRecord(sha=sha, change_id=change_id or mint_change_id(), patch_id=patch_id)
        self._store.put_changeid(record)
        return record

    def get_or_mint(self, sha: str, patch_id: str | None = None) -> tuple[ChangeIdRecord, bool]:
        """Return the record for a sha, minting one lazily; True if newly minted."""
        existing = self.get(sha)
        if existing is not None:
            return existing, False
        return self.insert(sha, patch_id=patch_id), True

    def migrate(self, old_sha: str, new_sha: str, patch_id: str | None = None) -> bool:
        """Carry an old sha's change-id over to its rewritten sha; False if old is unmapped."""
        old = self.get(old_sha)
        if old is None:
            return False
        if self.get(new_sha) is None:
            self.insert(new_sha, change_id=old.change_id, patch_id=patch_id)
        return True


def backfill(repo: pygit2.Repository, cid_map: ChangeIdMap) -> int:
    """Mint change-ids + patch-ids for every unmapped commit reachable from any ref."""
    minted = 0
    for commit in iter_all_commits(repo):
        sha = str(commit.id)
        if cid_map.get(sha) is None:
            cid_map.insert(sha, patch_id=patch_id(repo, commit))
            minted += 1
    return minted
