"""Tests for sharing the feature store: 3-way merge, push, and fetch."""

from collections.abc import Callable
from pathlib import Path

import pygit2
import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.store import (
    STORE_REF,
    GitRefStore,
    MemoryStore,
    StoreMergeError,
    merge_stores,
)
from git_feature.store.types import (
    Annotation,
    ChangeIdRecord,
    FeatureDef,
    RegionAnchor,
    StoreMeta,
)
from tests.fixtures import RepoBuilder


def _anchor(path: str = "src/a.py") -> RegionAnchor:
    return RegionAnchor(
        change_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        path=path,
        old_span=(1, 0),
        new_span=(1, 2),
        fingerprint="abc",
    )


def _annotation(presence: str, ts: str = "2026-07-01T00:00:00Z") -> Annotation:
    return Annotation(anchor=_anchor(), presence=presence, author="a@example.com", ts=ts)


def _store_with(
    features: tuple[str, ...] = (),
    annotations: dict[str, list[Annotation]] | None = None,
    changeids: tuple[ChangeIdRecord, ...] = (),
) -> dict[str, bytes]:
    store = MemoryStore()
    store.write_meta(StoreMeta())
    for name in features:
        store.write_feature(FeatureDef(name=name))
    for change_id, items in (annotations or {}).items():
        store.write_annotations(change_id, items)
    for record in changeids:
        store.put_changeid(record)
    return dict(store._files)


def test_merge_unions_disjoint_annotations() -> None:
    base = _store_with()
    ours = _store_with(features=["auth"], annotations={"cid-1": [_annotation("auth")]})
    theirs = _store_with(features=["ui"], annotations={"cid-2": [_annotation("ui")]})

    merged, notes = merge_stores(base, ours, theirs)
    result = MemoryStore()
    result._files = merged
    assert result.list_features() == ["auth", "ui"]
    assert [a.presence for a in result.read_annotations("cid-1")] == ["auth"]
    assert [a.presence for a in result.read_annotations("cid-2")] == ["ui"]
    assert notes == []


def test_merge_unions_annotations_of_the_same_change() -> None:
    base = _store_with()
    shared = _annotation("core")
    ours = _store_with(annotations={"cid-1": [shared, _annotation("auth")]})
    theirs = _store_with(annotations={"cid-1": [shared, _annotation("ui")]})

    merged, _ = merge_stores(base, ours, theirs)
    result = MemoryStore()
    result._files = merged
    presences = sorted(a.presence for a in result.read_annotations("cid-1"))
    assert presences == ["auth", "core", "ui"]


def test_merge_is_symmetric_when_a_sha_is_minted_twice() -> None:
    sha = "d" * 40
    older = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    newer = "01BX5ZZKBKACTAV9WEVGEMMVRZ"
    base = _store_with()
    ours = _store_with(
        changeids=[ChangeIdRecord(sha=sha, change_id=older)],
        annotations={older: [_annotation("auth")]},
    )
    theirs = _store_with(
        changeids=[ChangeIdRecord(sha=sha, change_id=newer)],
        annotations={newer: [_annotation("ui")]},
    )

    forward, notes = merge_stores(base, ours, theirs)
    backward, _ = merge_stores(base, theirs, ours)
    assert forward == backward
    assert any("minted on both sides" in note for note in notes)

    result = MemoryStore()
    result._files = forward
    # the older ULID wins and inherits the newer id's annotations
    record = result.get_changeid(sha)
    assert record is not None and record.change_id == older
    presences = sorted(a.presence for a in result.read_annotations(older))
    assert presences == ["auth", "ui"]
    assert result.read_annotations(newer) == []


def test_merge_features_field_wise() -> None:
    base = _store_with(features=["auth"])
    ours_store = MemoryStore()
    ours_store._files = dict(_store_with())
    ours_store.write_feature(FeatureDef(name="auth", description="login", owners=["ann"]))
    theirs_store = MemoryStore()
    theirs_store._files = dict(_store_with())
    theirs_store.write_feature(FeatureDef(name="auth", owners=["bob"], tags=["security"]))

    merged, _ = merge_stores(base, dict(ours_store._files), dict(theirs_store._files))
    result = MemoryStore()
    result._files = merged
    feature = result.read_feature("auth")
    assert feature is not None
    assert feature.description == "login"
    assert feature.owners == ["ann", "bob"]
    assert feature.tags == ["security"]


def test_merge_rejects_mismatched_schema_versions() -> None:
    ours = _store_with()
    theirs = dict(ours)
    theirs["meta.json"] = StoreMeta(schema_version=999).model_dump_json().encode()
    with pytest.raises(StoreMergeError):
        merge_stores({}, ours, theirs)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def shared_remote(tmp_path: Path) -> str:
    remote_path = tmp_path / "remote.git"
    pygit2.init_repository(str(remote_path), bare=True)
    return str(remote_path)


def _machine(
    repo_builder: Callable[[str], RepoBuilder],
    runner: CliRunner,
    name: str,
    remote_url: str,
) -> RepoBuilder:
    builder = repo_builder(name)
    builder.repo.remotes.create("origin", remote_url)
    builder.commit("base", files={"app.py": f"# {name}\ndef run():\n    pass\n"})
    return builder


def test_push_fetch_and_merge_between_two_machines(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    shared_remote: str,
) -> None:
    ann = _machine(repo_builder, runner, "ann", shared_remote)
    bob = _machine(repo_builder, runner, "bob", shared_remote)

    # machine ann initializes, annotates, and shares the store
    monkeypatch.chdir(ann.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    ann_sha = ann.commit("auth code", files={"auth.py": "def login():\n    pass\n"})
    assert runner.invoke(app, ["annotate", ann_sha, "--feature", "auth"]).exit_code == 0
    assert runner.invoke(app, ["store", "push"]).exit_code == 0

    # machine bob starts from ann's store instead of initializing its own
    monkeypatch.chdir(bob.path)
    result = runner.invoke(app, ["store", "fetch"])
    assert result.exit_code == 0, result.output
    assert "fetched" in result.output
    assert GitRefStore(bob.repo).list_features() == ["auth"]

    # both sides annotate independently -> the stores diverge
    bob_sha = bob.commit("ui code", files={"ui.py": "def render():\n    pass\n"})
    assert runner.invoke(app, ["annotate", bob_sha, "--feature", "ui"]).exit_code == 0
    monkeypatch.chdir(ann.path)
    ann_sha2 = ann.commit("search code", files={"search.py": "def find():\n    pass\n"})
    assert runner.invoke(app, ["annotate", ann_sha2, "--feature", "search"]).exit_code == 0
    assert runner.invoke(app, ["store", "push"]).exit_code == 0

    # bob's push is rejected, fetch merges, then the push goes through
    monkeypatch.chdir(bob.path)
    result = runner.invoke(app, ["store", "push"])
    assert result.exit_code == 1
    assert "store fetch" in result.output
    result = runner.invoke(app, ["store", "fetch"])
    assert result.exit_code == 0, result.output
    assert "merged" in result.output
    assert GitRefStore(bob.repo).list_features() == ["auth", "search", "ui"]
    assert runner.invoke(app, ["store", "push"]).exit_code == 0

    # ann fast-forwards to the merged store
    monkeypatch.chdir(ann.path)
    result = runner.invoke(app, ["store", "fetch"])
    assert result.exit_code == 0, result.output
    assert "fast-forwarded" in result.output
    assert GitRefStore(ann.repo).list_features() == ["auth", "search", "ui"]


def test_fetch_reports_up_to_date_and_ahead(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    shared_remote: str,
) -> None:
    ann = _machine(repo_builder, runner, "ann", shared_remote)
    monkeypatch.chdir(ann.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["store", "push"]).exit_code == 0

    result = runner.invoke(app, ["store", "fetch"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output

    sha = ann.commit("auth code", files={"auth.py": "def login():\n    pass\n"})
    assert runner.invoke(app, ["annotate", sha, "--feature", "auth"]).exit_code == 0
    result = runner.invoke(app, ["store", "fetch"])
    assert result.exit_code == 0, result.output
    assert "ahead" in result.output


def test_init_adds_the_store_fetch_refspec(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    shared_remote: str,
) -> None:
    ann = _machine(repo_builder, runner, "ann", shared_remote)
    monkeypatch.chdir(ann.path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert "fetch refspec" in result.output
    refspecs = ann.repo.remotes["origin"].fetch_refspecs
    assert f"+{STORE_REF}:refs/feature/incoming/origin" in refspecs


def test_push_without_remote_fails_cleanly(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    builder = repo_builder("solo")
    builder.commit("base", files={"app.py": "pass\n"})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    result = runner.invoke(app, ["store", "push"])
    assert result.exit_code == 1
    assert "no remote" in result.output
