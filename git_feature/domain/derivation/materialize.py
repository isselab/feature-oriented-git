"""Variant derivation stages 3–4: materialize the reduced tree and verify it."""

import pygit2

from ...gitio import blob_data, rewrite_tree
from ...identity import ChangeIdMap, original_added_lines
from ...store.base import Store
from ...store.types import RegionDecision
from .pipeline import Conflict, Projection


def removal_plan(projection: Projection) -> dict[str, list[tuple[int, int]]]:
    """Line runs to delete per file, from the projection's removed decisions."""
    plan: dict[str, list[tuple[int, int]]] = {}
    for decision in projection.removed:
        plan.setdefault(decision.anchor.path, []).extend(decision.runs())
    return plan


def materialize_tree(repo: pygit2.Repository, projection: Projection) -> pygit2.Oid:
    """Build the variant tree: base tree with disabled spans spliced out of each file."""
    replacements = {}
    for path, spans in removal_plan(projection).items():
        raw = blob_data(repo, projection.base_sha, path)
        if raw is None:
            raise KeyError(f"'{path}' not found in base commit {projection.base_sha[:12]}")
        replacements[path] = splice_out(raw, spans)
    return rewrite_tree(repo, projection.base_sha, replacements)


def splice_out(raw: bytes, spans: list[tuple[int, int]]) -> bytes:
    """Remove 1-based line spans from file content, byte-exact for the kept lines."""
    drop: set[int] = set()
    for start, count in spans:
        drop.update(range(start, start + count))
    lines = raw.decode("utf-8").splitlines(keepends=True)
    return "".join(line for number, line in enumerate(lines, start=1) if number not in drop).encode(
        "utf-8"
    )


def verify_tree(
    repo: pygit2.Repository,
    store: Store,
    tree_rev: str | pygit2.Commit,
    base_sha: str,
    decisions: list[RegionDecision],
) -> list[Conflict]:
    """Check a derived tree against what each region *originally said*, not against
    the resolver's answer: a removed region's content must be gone, a kept region's
    content must survive. This catches mis-resolved spans that spliced wrong lines.
    """
    cid_map = ChangeIdMap(store)
    conflicts = []
    for decision in decisions:
        content = _region_content(repo, cid_map, decision, base_sha)
        if not content:
            continue
        # Regions evolve: later commits may have rewritten these lines. Only what
        # was literally present at the base can be demanded from (or denied to)
        # the derived tree.
        if not _content_present(repo, base_sha, decision.anchor.path, content):
            continue
        present = _content_present(repo, tree_rev, decision.anchor.path, content)
        if decision.included and not present:
            conflicts.append(
                Conflict(
                    "verify",
                    f"kept region {decision.presence!r} is missing from the derived"
                    f" {decision.anchor.path}",
                    decision.anchor.path,
                )
            )
        if not decision.included and present:
            conflicts.append(
                Conflict(
                    "verify",
                    f"removed region {decision.presence!r} still present in the derived"
                    f" {decision.anchor.path}",
                    decision.anchor.path,
                )
            )
    return conflicts


def _region_content(
    repo: pygit2.Repository, cid_map: ChangeIdMap, decision: RegionDecision, base_sha: str
) -> list[str]:
    """The region's salient lines: whitespace-normalized, blanks dropped."""
    lines = original_added_lines(repo, cid_map, decision.anchor)
    if lines is None and decision.resolved_span is not None:
        raw = blob_data(repo, base_sha, decision.anchor.path)
        if raw is not None:
            start, count = decision.resolved_span
            lines = tuple(raw.decode("utf-8").splitlines()[start - 1 : start - 1 + count])
    return _salient(lines or ())


def _content_present(
    repo: pygit2.Repository, rev: str | pygit2.Commit, path: str, content: list[str]
) -> bool:
    raw = blob_data(repo, rev, path)
    if raw is None:
        return False
    haystack = _salient(raw.decode("utf-8").splitlines())
    length = len(content)
    return any(
        haystack[i : i + length] == content for i in range(0, max(len(haystack) - length + 1, 1))
    )


def _salient(lines: tuple[str, ...] | list[str]) -> list[str]:
    normalized = ("".join(line.split()) for line in lines)
    return [line for line in normalized if line]
