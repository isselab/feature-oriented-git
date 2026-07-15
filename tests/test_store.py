"""Round-trip tests for the store backends."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pygit2
import pytest

from git_feature.store import (
    STORE_REF,
    Annotation,
    ChangeIdRecord,
    DerivationManifest,
    FeatureDef,
    GitRefStore,
    MemoryStore,
    RegionAnchor,
    Store,
    StoreMeta,
)
from tests.fixtures import RepoBuilder

TS = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)

ANCHOR = RegionAnchor(
    change_id="01JCHANGEID000000000000000",
    path="src/auth/login.py",
    old_span=(0, 0),
    new_span=(10, 4),
    fingerprint="abc123",
)


@dataclass
class Backend:
    store: Store
    reopen: Callable[[], Store]
    history_len: Callable[[], int]


@pytest.fixture(params=["memory", "gitref"])
def backend(request: pytest.FixtureRequest, repo_builder: Callable[[str], RepoBuilder]) -> Backend:
    if request.param == "memory":
        memory = MemoryStore()
        return Backend(
            store=memory,
            reopen=lambda: memory,
            history_len=lambda: len(memory.commits),
        )
    builder = repo_builder("store")

    def history_len() -> int:
        repo = pygit2.Repository(str(builder.path))
        target = repo.references[STORE_REF].target
        return sum(1 for _ in repo.walk(target))

    return Backend(
        store=GitRefStore(builder.repo),
        reopen=lambda: GitRefStore(pygit2.Repository(str(builder.path))),
        history_len=history_len,
    )


def test_round_trip_all_object_kinds(backend: Backend) -> None:
    store = backend.store
    meta = StoreMeta(tool_version="0.1.0")
    feature = FeatureDef(name="auth", description="authentication", owners=["alice"])
    annotations = [
        Annotation(anchor=ANCHOR, presence="auth", author="alice", ts=TS),
        Annotation(anchor=ANCHOR, presence="auth & premium", author="bob", ts=TS, note="shared"),
    ]
    record_aa = ChangeIdRecord(sha="aa" * 20, change_id="01JAAA", patch_id="pa")
    record_ab = ChangeIdRecord(sha="ab" + "cd" * 19, change_id="01JBBB")
    manifest = DerivationManifest(
        instance="minimal",
        base_commit="aa" * 20,
        assignment={"auth": True, "premium": False},
        created_at=TS,
    )

    store.write_meta(meta)
    store.write_feature(feature)
    store.write_annotations(ANCHOR.change_id, annotations)
    store.put_changeid(record_aa)
    store.put_changeid(record_ab)
    store.write_manifest("minimal", manifest)
    store.commit("initial store content")

    reopened = backend.reopen()
    assert reopened.read_meta() == meta
    assert reopened.read_feature("auth") == feature
    assert reopened.list_features() == ["auth"]
    assert reopened.read_annotations(ANCHOR.change_id) == annotations
    assert reopened.list_annotated_changes() == [ANCHOR.change_id]
    assert reopened.get_changeid("aa" * 20) == record_aa
    assert reopened.get_changeid(record_ab.sha) == record_ab
    assert sorted(r.sha for r in reopened.iter_changeids()) == sorted(
        [record_aa.sha, record_ab.sha]
    )
    assert reopened.read_manifest("minimal") == manifest
    assert reopened.list_variants() == ["minimal"]


def test_missing_objects_read_as_empty(backend: Backend) -> None:
    store = backend.store
    assert store.read_meta() is None
    assert store.read_feature("nope") is None
    assert store.read_annotations("nope") == []
    assert store.get_changeid("aa" * 20) is None
    assert store.read_manifest("nope") is None
    assert store.list_features() == []
    assert list(store.iter_changeids()) == []


def test_staged_writes_visible_before_commit(backend: Backend) -> None:
    store = backend.store
    feature = FeatureDef(name="auth")
    store.write_feature(feature)
    assert store.read_feature("auth") == feature
    assert store.list_features() == ["auth"]


def test_sequential_commits_build_history(backend: Backend) -> None:
    store = backend.store
    store.write_meta(StoreMeta(tool_version="0.1.0"))
    store.commit("first")
    store.write_feature(FeatureDef(name="auth"))
    store.commit("second")
    assert backend.history_len() == 2
    reopened = backend.reopen()
    assert reopened.read_meta() is not None
    assert reopened.read_feature("auth") is not None


class TestGitRefBackend:
    def test_concurrent_commit_conflicts(self, repo_builder: Callable[[str], RepoBuilder]) -> None:
        from git_feature.gitio import RefUpdateConflict

        builder = repo_builder("conflict")
        store_a = GitRefStore(builder.repo)
        store_b = GitRefStore(pygit2.Repository(str(builder.path)))
        store_a.write_meta(StoreMeta())
        store_a.commit("from a")
        store_b.write_feature(FeatureDef(name="auth"))
        with pytest.raises(RefUpdateConflict):
            store_b.commit("from b")

    def test_changeid_map_is_sharded_by_sha_prefix(
        self, repo_builder: Callable[[str], RepoBuilder]
    ) -> None:
        builder = repo_builder("shards")
        store = GitRefStore(builder.repo)
        store.put_changeid(ChangeIdRecord(sha="aa" * 20, change_id="01JAAA"))
        store.put_changeid(ChangeIdRecord(sha="ab" + "aa" * 19, change_id="01JBBB"))
        store.commit("sharded")
        repo = pygit2.Repository(str(builder.path))
        tree = repo.references[STORE_REF].peel(pygit2.Commit).tree
        shard_names = sorted(entry.name for entry in tree["changeids"])
        assert shard_names == ["map-aa.json", "map-ab.json"]

    def test_store_ref_never_touches_worktree_or_branches(
        self, repo_builder: Callable[[str], RepoBuilder]
    ) -> None:
        builder = repo_builder("isolation")
        sha = builder.commit("code", files={"a.txt": "a\n"})
        store = GitRefStore(builder.repo)
        store.write_meta(StoreMeta())
        store.commit("store init")
        assert str(builder.repo.head.target) == sha
        assert list(builder.repo.branches.local) == [builder.default_branch]
        assert (builder.path / "a.txt").exists()
        assert not (builder.path / "meta.json").exists()
