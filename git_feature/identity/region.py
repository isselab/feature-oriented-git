"""Region anchors and the blame-forward resolver (tiers 1–2)."""

from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

import pygit2
import xxhash

from ..gitio import (
    Hunk,
    blob_lines,
    commit_diff,
    line_origins,
    resolve_commit,
    tree_paths,
)
from ..store.types import Confidence, RegionAnchor
from .change_id import ChangeIdMap

FUZZY_THRESHOLD = 0.75


def normalized_fingerprint(lines: Sequence[str]) -> str:
    """Whitespace-insensitive content hash of a sequence of lines."""
    joined = "\n".join("".join(line.split()) for line in lines)
    return xxhash.xxh3_64_hexdigest(joined)


def anchor_from_hunk(change_id: str, path: str, hunk: Hunk) -> RegionAnchor:
    """Anchor a hunk to the change that introduced it."""
    return RegionAnchor(
        change_id=change_id,
        path=path,
        old_span=hunk.old_span,
        new_span=hunk.new_span,
        fingerprint=normalized_fingerprint(hunk.added_lines),
    )


@dataclass(frozen=True)
class Resolution:
    """Where a region lives at a target commit, and how sure we are."""

    span: tuple[int, int] | None
    confidence: Confidence


class RegionResolver:
    """Answers: which lines does an anchored region occupy at a target commit?"""

    def __init__(self, repo: pygit2.Repository, cid_map: ChangeIdMap) -> None:
        self._repo = repo
        self._map = cid_map
        self._cache: dict[tuple[str, str, tuple[int, int], str, str], Resolution] = {}
        self._origins_cache: dict[tuple[str, str], list[str] | None] = {}

    def resolve(self, anchor: RegionAnchor, target: str | pygit2.Commit) -> Resolution:
        commit = resolve_commit(self._repo, target)
        key = (anchor.change_id, anchor.path, anchor.new_span, anchor.fingerprint, str(commit.id))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        resolution = (
            self._blame_forward(anchor, commit)
            or self._fingerprint_search(anchor, commit)
            or Resolution(None, "lost")
        )
        self._cache[key] = resolution
        return resolution

    def _blame_forward(self, anchor: RegionAnchor, commit: pygit2.Commit) -> Resolution | None:
        origins = self._line_origins(anchor.path, commit)
        if origins is None:
            return None
        shas = set(self._map.shas_for(anchor.change_id))
        mine = [i + 1 for i, sha in enumerate(origins) if sha in shas]
        if not mine:
            return None
        lines = blob_lines(self._repo, commit, anchor.path) or []
        length = anchor.new_span[1]
        for run in _contiguous_runs(mine):
            for start in range(run[0], run[0] + len(run) - length + 1):
                window = lines[start - 1 : start - 1 + length]
                if normalized_fingerprint(window) == anchor.fingerprint:
                    return Resolution((start, length), "exact")
        return Resolution((mine[0], mine[-1] - mine[0] + 1), "moved")

    def _line_origins(self, path: str, commit: pygit2.Commit) -> list[str] | None:
        """One blame pass per (path, target commit), shared by every anchor."""
        key = (path, str(commit.id))
        if key not in self._origins_cache:
            self._origins_cache[key] = line_origins(self._repo, commit, path)
        return self._origins_cache[key]

    def _fingerprint_search(self, anchor: RegionAnchor, commit: pygit2.Commit) -> Resolution | None:
        length = anchor.new_span[1]
        if length == 0:
            return None
        paths = [anchor.path] + sorted(
            p for p in tree_paths(self._repo, commit) if p != anchor.path
        )
        for path in paths:
            lines = blob_lines(self._repo, commit, path)
            if lines is None or len(lines) < length:
                continue
            for start in range(1, len(lines) - length + 2):
                window = lines[start - 1 : start - 1 + length]
                if normalized_fingerprint(window) == anchor.fingerprint:
                    return Resolution((start, length), "fuzzy")
        return self._similarity_search(anchor, commit, paths)

    def _similarity_search(
        self, anchor: RegionAnchor, commit: pygit2.Commit, paths: list[str]
    ) -> Resolution | None:
        original = self._original_lines(anchor)
        if not original:
            return None
        target_text = "\n".join("".join(line.split()) for line in original)
        length = anchor.new_span[1]
        best: tuple[float, tuple[int, int]] | None = None
        for path in paths:
            lines = blob_lines(self._repo, commit, path)
            if lines is None or len(lines) < length:
                continue
            for start in range(1, len(lines) - length + 2):
                window = lines[start - 1 : start - 1 + length]
                window_text = "\n".join("".join(line.split()) for line in window)
                score = SequenceMatcher(None, target_text, window_text).ratio()
                if best is None or score > best[0]:
                    best = (score, (start, length))
        if best is not None and best[0] >= FUZZY_THRESHOLD:
            return Resolution(best[1], "fuzzy")
        return None

    def _original_lines(self, anchor: RegionAnchor) -> tuple[str, ...] | None:
        """Recover the anchor's added lines from the frozen diff of its change."""
        for sha in self._map.shas_for(anchor.change_id):
            if sha not in self._repo:
                continue
            for file_diff in commit_diff(self._repo, sha):
                if file_diff.new_path != anchor.path:
                    continue
                for hunk in file_diff.hunks:
                    if hunk.new_span == anchor.new_span and hunk.old_span == anchor.old_span:
                        return hunk.added_lines
        return None


def _contiguous_runs(line_numbers: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for number in line_numbers:
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return runs
