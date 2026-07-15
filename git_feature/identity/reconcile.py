"""Match unmapped commits to known change-ids by patch-id, then fuzzy similarity."""

from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pygit2

from ..gitio import commit_diff, iter_all_commits, patch_id
from .change_id import ChangeIdMap

AUTO_LINK_THRESHOLD = 0.85
CANDIDATE_THRESHOLD = 0.6


@dataclass(frozen=True)
class Link:
    """A planned sha → existing change-id association."""

    sha: str
    change_id: str
    via: str  # "patch-id" or "fuzzy"
    score: float
    patch_id: str


@dataclass(frozen=True)
class Ambiguity:
    """An unmapped commit with several plausible change-id candidates."""

    sha: str
    candidates: tuple[tuple[str, float], ...]
    patch_id: str


@dataclass
class ReconcilePlan:
    """Outcome of the matching pass, before anything is written."""

    links: list[Link] = field(default_factory=list)
    ambiguous: list[Ambiguity] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)


def plan_reconcile(repo: pygit2.Repository, cid_map: ChangeIdMap) -> ReconcilePlan:
    """Compute links for unmapped reachable commits without writing anything."""
    known = _known_patch_ids(repo, cid_map)
    plan = ReconcilePlan()
    for commit in iter_all_commits(repo):
        sha = str(commit.id)
        if cid_map.get(sha) is not None:
            continue
        pid = patch_id(repo, commit)
        exact = sorted(known.get(pid, ()))
        if len(exact) == 1:
            plan.links.append(Link(sha, exact[0], via="patch-id", score=1.0, patch_id=pid))
            continue
        if len(exact) > 1:
            candidates = tuple((cid, 1.0) for cid in exact)
            plan.ambiguous.append(Ambiguity(sha, candidates, patch_id=pid))
            continue
        _fuzzy_match(repo, cid_map, sha, pid, plan)
    return plan


def apply_links(cid_map: ChangeIdMap, links: list[Link]) -> None:
    """Write the planned links into the change-id map."""
    for link in links:
        cid_map.insert(link.sha, change_id=link.change_id, patch_id=link.patch_id)


def _fuzzy_match(
    repo: pygit2.Repository, cid_map: ChangeIdMap, sha: str, pid: str, plan: ReconcilePlan
) -> None:
    text = _added_text(repo, sha)
    if not text:
        plan.unmatched.append(sha)
        return
    scores: dict[str, float] = {}
    for record in cid_map.iter_records():
        if record.sha not in repo:
            continue
        other = _added_text(repo, record.sha)
        if not other:
            continue
        score = SequenceMatcher(None, text, other).ratio()
        if score > scores.get(record.change_id, 0.0):
            scores[record.change_id] = score
    ranked = sorted(
        ((cid, s) for cid, s in scores.items() if s >= CANDIDATE_THRESHOLD),
        key=lambda pair: -pair[1],
    )
    if ranked and ranked[0][1] >= AUTO_LINK_THRESHOLD:
        best_cid, best_score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        if runner_up < AUTO_LINK_THRESHOLD:
            plan.links.append(Link(sha, best_cid, via="fuzzy", score=best_score, patch_id=pid))
            return
    if ranked:
        plan.ambiguous.append(Ambiguity(sha, tuple(ranked), patch_id=pid))
    else:
        plan.unmatched.append(sha)


def _known_patch_ids(repo: pygit2.Repository, cid_map: ChangeIdMap) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for record in cid_map.iter_records():
        pid = record.patch_id
        if pid is None and record.sha in repo:
            pid = patch_id(repo, record.sha)
        if pid is not None:
            index.setdefault(pid, set()).add(record.change_id)
    return index


def _added_text(repo: pygit2.Repository, sha: str) -> str:
    lines: list[str] = []
    for file_diff in commit_diff(repo, sha):
        for hunk in file_diff.hunks:
            lines.extend(line.strip() for line in hunk.added_lines)
    return "\n".join(lines)
