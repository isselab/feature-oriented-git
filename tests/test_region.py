"""Tests for region anchors and the two-tier resolver."""

from collections.abc import Callable

import pytest

from git_feature.gitio import commit_diff, patch_id
from git_feature.identity import ChangeIdMap, RegionResolver, anchor_from_hunk
from git_feature.store import MemoryStore, RegionAnchor
from tests.fixtures import RepoBuilder

BASE = "def top():\n    return 1\n\n\ndef bottom():\n    return 2\n"
WITH_REGION = (
    "def top():\n    return 1\n\n\ndef region_a():\n    x = compute()\n    return x\n\n\n"
    "def bottom():\n    return 2\n"
)


@pytest.fixture
def setup(
    repo_builder: Callable[[str], RepoBuilder],
) -> tuple[RepoBuilder, ChangeIdMap, RegionAnchor]:
    builder = repo_builder("repo")
    builder.commit("base", files={"code.py": BASE})
    region_sha = builder.commit("add region", files={"code.py": WITH_REGION})

    cid_map = ChangeIdMap(MemoryStore())
    record = cid_map.insert(region_sha, patch_id=patch_id(builder.repo, region_sha))

    (file_diff,) = commit_diff(builder.repo, region_sha)
    (hunk,) = file_diff.hunks
    anchor = anchor_from_hunk(record.change_id, "code.py", hunk)
    return builder, cid_map, anchor


def test_anchor_from_hunk_captures_spans(
    setup: tuple[RepoBuilder, ChangeIdMap, RegionAnchor],
) -> None:
    _, _, anchor = setup
    assert anchor.path == "code.py"
    assert anchor.new_span[1] == 5  # the region block incl. surrounding blank lines
    assert anchor.fingerprint


def test_untouched_region_resolves_exactly_in_place(
    setup: tuple[RepoBuilder, ChangeIdMap, RegionAnchor],
) -> None:
    builder, cid_map, anchor = setup
    resolution = RegionResolver(builder.repo, cid_map).resolve(anchor, "HEAD")
    assert resolution.confidence == "exact"
    assert resolution.span == anchor.new_span


def test_edits_above_shift_span_but_stay_exact(
    setup: tuple[RepoBuilder, ChangeIdMap, RegionAnchor],
) -> None:
    builder, cid_map, anchor = setup
    shifted = WITH_REGION.replace("def top():\n", "import os\nimport sys\n\n\ndef top():\n")
    builder.commit("edits above", files={"code.py": shifted})
    resolution = RegionResolver(builder.repo, cid_map).resolve(anchor, "HEAD")
    assert resolution.confidence == "exact"
    assert resolution.span == (anchor.new_span[0] + 4, anchor.new_span[1])


def test_rename_plus_edit_resolves_fuzzily(
    setup: tuple[RepoBuilder, ChangeIdMap, RegionAnchor],
) -> None:
    builder, cid_map, anchor = setup
    edited = WITH_REGION.replace("return 2", "return 42")
    builder.commit("rename and edit", files={"renamed.py": edited}, remove=["code.py"])
    resolution = RegionResolver(builder.repo, cid_map).resolve(anchor, "HEAD")
    assert resolution.confidence == "fuzzy"
    assert resolution.span == anchor.new_span  # region itself did not move


def test_edit_inside_region_after_rename_still_found_by_similarity(
    setup: tuple[RepoBuilder, ChangeIdMap, RegionAnchor],
) -> None:
    builder, cid_map, anchor = setup
    edited = WITH_REGION.replace("x = compute()", "x = compute(fast=True)")
    builder.commit("rename and edit inside", files={"renamed.py": edited}, remove=["code.py"])
    resolution = RegionResolver(builder.repo, cid_map).resolve(anchor, "HEAD")
    assert resolution.confidence == "fuzzy"
    assert resolution.span == anchor.new_span


def test_deleted_region_reports_lost(
    setup: tuple[RepoBuilder, ChangeIdMap, RegionAnchor],
) -> None:
    builder, cid_map, anchor = setup
    builder.commit("remove region", files={"code.py": BASE})
    resolution = RegionResolver(builder.repo, cid_map).resolve(anchor, "HEAD")
    assert resolution.confidence == "lost"
    assert resolution.span is None


def test_partial_survival_reports_moved(
    setup: tuple[RepoBuilder, ChangeIdMap, RegionAnchor],
) -> None:
    builder, cid_map, anchor = setup
    partial = WITH_REGION.replace("    x = compute()\n", "")
    builder.commit("shrink region", files={"code.py": partial})
    resolution = RegionResolver(builder.repo, cid_map).resolve(anchor, "HEAD")
    assert resolution.confidence == "moved"
    assert resolution.span is not None


def test_resolution_is_cached_per_anchor_and_target(
    setup: tuple[RepoBuilder, ChangeIdMap, RegionAnchor],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, cid_map, anchor = setup
    resolver = RegionResolver(builder.repo, cid_map)
    calls = {"n": 0}
    original = RegionResolver._blame_forward

    def counting(self: RegionResolver, a: RegionAnchor, c: object) -> object:
        calls["n"] += 1
        return original(self, a, c)  # type: ignore[arg-type]

    monkeypatch.setattr(RegionResolver, "_blame_forward", counting)
    first = resolver.resolve(anchor, "HEAD")
    second = resolver.resolve(anchor, "HEAD")
    assert first == second
    assert calls["n"] == 1
