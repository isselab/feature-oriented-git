"""Tests for change-id minting, the map API, patch-ids, and backfill."""

from collections.abc import Callable

from git_feature.gitio import patch_id
from git_feature.identity import ChangeIdMap, backfill, mint_change_id
from git_feature.store import GitRefStore, MemoryStore
from tests.fixtures import RepoBuilder


def test_mint_change_id_is_unique_ulid() -> None:
    ids = {mint_change_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(i) == 26 for i in ids)


class TestChangeIdMap:
    def test_insert_and_get(self) -> None:
        cid_map = ChangeIdMap(MemoryStore())
        record = cid_map.insert("aa" * 20, patch_id="p1")
        assert cid_map.get("aa" * 20) == record
        assert cid_map.get("bb" * 20) is None

    def test_get_or_mint_is_lazy_and_idempotent(self) -> None:
        cid_map = ChangeIdMap(MemoryStore())
        first, minted = cid_map.get_or_mint("aa" * 20)
        assert minted
        again, minted_again = cid_map.get_or_mint("aa" * 20)
        assert not minted_again
        assert again == first

    def test_migrate_carries_change_id_to_new_sha(self) -> None:
        cid_map = ChangeIdMap(MemoryStore())
        old = cid_map.insert("aa" * 20)
        assert cid_map.migrate("aa" * 20, "bb" * 20)
        new = cid_map.get("bb" * 20)
        assert new is not None
        assert new.change_id == old.change_id
        assert set(cid_map.shas_for(old.change_id)) == {"aa" * 20, "bb" * 20}

    def test_migrate_overwrites_a_stray_mapping_of_the_new_sha(self) -> None:
        # On amend, post-commit mints for the new sha before post-rewrite runs;
        # the old sha's change-id must win.
        cid_map = ChangeIdMap(MemoryStore())
        old = cid_map.insert("aa" * 20)
        cid_map.insert("bb" * 20)  # stray id minted by post-commit
        assert cid_map.migrate("aa" * 20, "bb" * 20)
        new = cid_map.get("bb" * 20)
        assert new is not None
        assert new.change_id == old.change_id

    def test_migrate_of_unmapped_sha_is_a_noop(self) -> None:
        cid_map = ChangeIdMap(MemoryStore())
        assert not cid_map.migrate("aa" * 20, "bb" * 20)
        assert cid_map.get("bb" * 20) is None


class TestPatchId:
    def test_same_patch_on_different_bases_matches(
        self, repo_builder: Callable[[str], RepoBuilder]
    ) -> None:
        builder = repo_builder("repo")
        builder.commit("base", files={"a.txt": "one\ntwo\nthree\n"})
        builder.branch("other")
        sha_a = builder.commit("change", files={"a.txt": "one\nTWO\nthree\n"})
        builder.switch("other")
        builder.commit("drift", files={"b.txt": "unrelated\n"})
        sha_b = builder.commit("change again", files={"a.txt": "one\nTWO\nthree\n"})
        assert sha_a != sha_b
        assert patch_id(builder.repo, sha_a) == patch_id(builder.repo, sha_b)

    def test_different_patches_differ(self, repo_builder: Callable[[str], RepoBuilder]) -> None:
        builder = repo_builder("repo")
        builder.commit("base", files={"a.txt": "one\n"})
        sha_a = builder.commit("x", files={"a.txt": "one\nx\n"})
        sha_b = builder.commit("y", files={"a.txt": "one\nx\ny\n"})
        assert patch_id(builder.repo, sha_a) != patch_id(builder.repo, sha_b)

    def test_whitespace_changes_do_not_affect_patch_id(
        self, repo_builder: Callable[[str], RepoBuilder]
    ) -> None:
        builder = repo_builder("repo")
        builder.commit("base", files={"a.txt": "one\n"})
        builder.branch("other")
        sha_a = builder.commit("add", files={"a.txt": "one\nnew line\n"})
        builder.switch("other")
        sha_b = builder.commit("add spaced", files={"a.txt": "one\nnew  line\n"})
        assert patch_id(builder.repo, sha_a) == patch_id(builder.repo, sha_b)


class TestBackfill:
    def test_maps_all_commits_across_branches(
        self, repo_builder: Callable[[str], RepoBuilder]
    ) -> None:
        builder = repo_builder("repo")
        shas = [builder.commit("one", files={"a.txt": "a\n"})]
        builder.branch("side")
        shas.append(builder.commit("two", files={"a.txt": "a\nb\n"}))
        builder.switch("side")
        shas.append(builder.commit("three", files={"c.txt": "c\n"}))

        store = GitRefStore(builder.repo)
        cid_map = ChangeIdMap(store)
        assert backfill(builder.repo, cid_map) == 3
        for sha in shas:
            record = cid_map.get(sha)
            assert record is not None
            assert record.patch_id is not None

    def test_rerun_is_a_noop(self, repo_builder: Callable[[str], RepoBuilder]) -> None:
        builder = repo_builder("repo")
        builder.commit("one", files={"a.txt": "a\n"})
        cid_map = ChangeIdMap(GitRefStore(builder.repo))
        assert backfill(builder.repo, cid_map) == 1
        assert backfill(builder.repo, cid_map) == 0
