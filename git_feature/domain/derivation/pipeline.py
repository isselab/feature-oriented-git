"""Variant derivation pipeline, stages 1–2: configure and project."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations

import pygit2

from ...domain.query.catalog import iter_annotations
from ...domain.variability import (
    ConfigurationError,
    Evaluator,
    ModelError,
    ModelParseError,
    model_text,
    parse_model,
)
from ...domain.variability.presence import (
    PresenceError,
    UnknownFeatureError,
    eval_presence,
    parse_presence,
)
from ...gitio import resolve_commit
from ...identity import ChangeIdMap, RegionResolver
from ...store.base import Store
from ...store.types import DerivationManifest, RegionDecision


class DerivationError(Exception):
    """Configuration cannot even be attempted (missing model, illegal instance...)."""


@dataclass(frozen=True)
class Conflict:
    """One reported problem from the projection consistency checks."""

    kind: str  # "overlap" | "dangling-dependency" | "lost-region" | "bad-presence"
    detail: str
    path: str | None = None


@dataclass
class Projection:
    """Everything stages 1–2 produce: the plan for a variant, before any write."""

    instance: str
    base_sha: str
    assignment: dict[str, bool]
    decisions: list[RegionDecision] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def removed(self) -> list[RegionDecision]:
        return [d for d in self.decisions if not d.included]

    def manifest(self) -> DerivationManifest:
        return DerivationManifest(
            instance=self.instance,
            base_commit=self.base_sha,
            assignment=self.assignment,
            decisions=self.decisions,
            created_at=datetime.now(UTC),
        )


def configure(repo: pygit2.Repository, instance: str, base_rev: str) -> tuple[dict[str, bool], str]:
    """Stage 1: resolve the instance against model.cfr as of the base commit."""
    base_sha = str(resolve_commit(repo, base_rev).id)
    text = model_text(repo, base_sha)
    if text is None:
        raise DerivationError(f"no model.cfr in the tree of base commit {base_sha[:12]}")
    try:
        module = parse_model(text)
        assignment = Evaluator(module).resolve_assignment(instance)
    except (ModelParseError, ModelError, ConfigurationError) as exc:
        raise DerivationError(str(exc)) from None
    return assignment, base_sha


def project(
    repo: pygit2.Repository,
    store: Store,
    instance: str,
    assignment: dict[str, bool],
    base_sha: str,
) -> Projection:
    """Stage 2: decide every region's fate at the base commit and check consistency."""
    projection = Projection(instance=instance, base_sha=base_sha, assignment=assignment)
    cid_map = ChangeIdMap(store)
    resolver = RegionResolver(repo, cid_map)
    for change_id, annotation in iter_annotations(store):
        if not _change_in_history(repo, cid_map, change_id, base_sha):
            continue  # the change is not part of the base commit; nothing to include or remove
        try:
            included = eval_presence(parse_presence(annotation.presence), assignment)
        except (PresenceError, UnknownFeatureError) as exc:
            projection.conflicts.append(
                Conflict("bad-presence", f"{annotation.presence!r}: {exc}", annotation.anchor.path)
            )
            continue
        resolution = resolver.resolve(annotation.anchor, base_sha)
        projection.decisions.append(
            RegionDecision(
                anchor=annotation.anchor,
                presence=annotation.presence,
                included=included,
                resolved_span=resolution.span,
                resolved_runs=list(resolution.runs) if resolution.runs else None,
                resolved_path=resolution.path,
                confidence=resolution.confidence,
            )
        )
        if not included and resolution.confidence == "lost":
            projection.conflicts.append(
                Conflict(
                    "lost-region",
                    f"region of {annotation.presence!r} in {annotation.anchor.path} must be"
                    " removed but cannot be located at the base commit",
                    annotation.anchor.path,
                )
            )
    projection.conflicts.extend(_consistency_conflicts(projection.decisions))
    return projection


def _change_in_history(
    repo: pygit2.Repository, cid_map: ChangeIdMap, change_id: str, base_sha: str
) -> bool:
    """Whether any incarnation of the change is the base commit or one of its ancestors."""
    base = repo[base_sha].peel(pygit2.Commit).id
    for sha in cid_map.shas_for(change_id):
        if sha == base_sha:
            return True
        try:
            if repo.descendant_of(base, sha):
                return True
        except (KeyError, pygit2.GitError):
            continue
    return False


def _consistency_conflicts(decisions: list[RegionDecision]) -> list[Conflict]:
    conflicts = []
    located = [d for d in decisions if d.resolved_span is not None]
    for a, b in combinations(located, 2):
        if a.location() != b.location() or a.included == b.included:
            continue
        enabled, disabled = (a, b) if a.included else (b, a)
        clash = [
            (kept, removed)
            for kept in enabled.runs()
            for removed in disabled.runs()
            if _overlaps(kept, removed)
        ]
        if not clash:
            continue
        kept_run, removed_run = clash[0]
        if _contained(kept_run, removed_run):
            conflicts.append(
                Conflict(
                    "dangling-dependency",
                    f"enabled region {enabled.presence!r} sits inside removed region"
                    f" {disabled.presence!r} in {enabled.location()}"
                    f" (lines {_span_text(kept_run)})",
                    enabled.location(),
                )
            )
        else:
            conflicts.append(
                Conflict(
                    "overlap",
                    f"regions {enabled.presence!r} (kept) and {disabled.presence!r} (removed)"
                    f" overlap in {enabled.location()}"
                    f" (lines {_span_text(removed_run)})",
                    enabled.location(),
                )
            )
    return conflicts


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    a_end = a[0] + max(a[1], 1) - 1
    b_end = b[0] + max(b[1], 1) - 1
    return a[0] <= b_end and b[0] <= a_end


def _contained(inner: tuple[int, int], outer: tuple[int, int]) -> bool:
    inner_end = inner[0] + max(inner[1], 1) - 1
    outer_end = outer[0] + max(outer[1], 1) - 1
    return outer[0] <= inner[0] and inner_end <= outer_end and inner != outer


def _span_text(span: tuple[int, int]) -> str:
    start, count = span
    return f"{start}-{start + max(count, 1) - 1}"
