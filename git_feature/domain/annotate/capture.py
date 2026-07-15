"""Hunk capture: anchor a commit's hunks and write feature annotations."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch

import pygit2

from ...gitio import Hunk, commit_diff, patch_id, resolve_commit
from ...identity import ChangeIdMap, anchor_from_hunk
from ...store.base import Store
from ...store.types import Annotation, FeatureDef


@dataclass
class CaptureResult:
    """What a capture run did (aggregated over commits)."""

    written: int = 0
    duplicates: int = 0
    minted_change_ids: int = 0
    created_features: list[str] = field(default_factory=list)
    annotated_commits: int = 0


def matching_hunks(
    repo: pygit2.Repository, rev: str | pygit2.Commit, paths: tuple[str, ...]
) -> list[tuple[str, Hunk]]:
    """(path, hunk) pairs of a commit's diff whose path matches any glob (all if none)."""
    pairs = []
    for file_diff in commit_diff(repo, rev):
        if file_diff.new_path is None:  # pure deletion: nothing to attach a feature to
            continue
        if paths and not any(fnmatch(file_diff.new_path, glob) for glob in paths):
            continue
        for hunk in file_diff.hunks:
            pairs.append((file_diff.new_path, hunk))
    return pairs


def ensure_features(store: Store, names: list[str], result: CaptureResult) -> None:
    """Auto-create a minimal definition for any unknown feature name."""
    for name in names:
        if store.read_feature(name) is None:
            store.write_feature(FeatureDef(name=name, auto_created=True))
            result.created_features.append(name)


def annotate_commit(
    repo: pygit2.Repository,
    store: Store,
    rev: str | pygit2.Commit,
    presences: list[str],
    paths: tuple[str, ...],
    author: str,
    result: CaptureResult,
) -> None:
    """Write one annotation per (matching hunk × presence condition) for a commit."""
    commit = resolve_commit(repo, rev)
    pairs = matching_hunks(repo, commit, paths)
    if not pairs:
        return
    cid_map = ChangeIdMap(store)
    sha = str(commit.id)
    record, minted = cid_map.get_or_mint(sha, patch_id=patch_id(repo, commit))
    if minted:
        result.minted_change_ids += 1

    annotations = store.read_annotations(record.change_id)
    existing = {
        (a.anchor.path, a.anchor.old_span, a.anchor.new_span, a.presence) for a in annotations
    }
    added = False
    for path, hunk in pairs:
        anchor = anchor_from_hunk(record.change_id, path, hunk)
        for presence in presences:
            key = (anchor.path, anchor.old_span, anchor.new_span, presence)
            if key in existing:
                result.duplicates += 1
                continue
            annotations.append(
                Annotation(anchor=anchor, presence=presence, author=author, ts=datetime.now(UTC))
            )
            existing.add(key)
            result.written += 1
            added = True
    if added:
        store.write_annotations(record.change_id, annotations)
        result.annotated_commits += 1


def signature_name(repo: pygit2.Repository) -> str:
    """The configured git author name, or a placeholder."""
    try:
        return repo.default_signature.name or "unknown"
    except (KeyError, pygit2.GitError):
        return "unknown"
