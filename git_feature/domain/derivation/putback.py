"""Putback: remap view-space edits through a derivation manifest onto the source tree."""

from dataclasses import dataclass, field

from ...gitio import FileDiff, Hunk
from ...store.types import DerivationManifest
from .pipeline import Conflict


@dataclass(frozen=True)
class MappedEdit:
    """One hunk translated from view coordinates to source coordinates."""

    path: str
    view_span: tuple[int, int]
    source_span: tuple[int, int]


@dataclass
class PutbackPlan:
    """Everything needed to transplant view edits onto the source commit."""

    replacements: dict[str, bytes] = field(default_factory=dict)
    additions: list[str] = field(default_factory=list)
    edits: list[MappedEdit] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)


def plan_putback(
    manifest: DerivationManifest,
    file_diffs: list[FileDiff],
    base_content: dict[str, bytes | None],
    workdir_content: dict[str, bytes],
) -> PutbackPlan:
    """Map every edited file's hunks from view coordinates to source coordinates.

    `base_content` holds each changed path's bytes at the manifest's base commit
    (None if absent there); `workdir_content` holds the edited view's bytes.
    """
    plan = PutbackPlan()
    for file_diff in file_diffs:
        path = file_diff.new_path or file_diff.old_path
        if path is None:
            continue
        if file_diff.status in ("A", "?"):  # added in the view, or untracked-new
            plan.replacements[path] = workdir_content[path]
            plan.additions.append(path)
            continue
        if file_diff.status != "M":
            plan.conflicts.append(
                Conflict(
                    "unsupported-change",
                    f"{path}: only edits and new files can be put back"
                    f" (change status {file_diff.status!r})",
                    path,
                )
            )
            continue
        if not file_diff.hunks:
            plan.conflicts.append(
                Conflict("unsupported-change", f"{path}: binary or metadata change", path)
            )
            continue
        base_raw = base_content.get(path)
        if base_raw is None:
            plan.conflicts.append(
                Conflict("putback", f"{path}: not found at the view's base commit", path)
            )
            continue
        _map_file(
            plan,
            path,
            base_raw,
            workdir_content[path],
            manifest.removed_runs(path),
            file_diff.hunks,
        )
    return plan


def _map_file(
    plan: PutbackPlan,
    path: str,
    base_raw: bytes,
    edited_raw: bytes,
    runs: list[tuple[int, int]],
    hunks: tuple[Hunk, ...],
) -> None:
    """Splice one file's edited view lines into its base content at mapped positions."""
    base_lines = base_raw.decode("utf-8").splitlines(keepends=True)
    edited_lines = edited_raw.decode("utf-8").splitlines(keepends=True)
    removed: set[int] = set()
    for start, count in runs:
        removed.update(range(start, start + count))
    # kept[k-1] = the base line number that appears as view line k
    kept = [number for number in range(1, len(base_lines) + 1) if number not in removed]

    # (source_start, delete_count, replacement_lines), collected then applied bottom-up
    operations: list[tuple[int, int, list[str]]] = []
    for hunk in hunks:
        old_start, old_count = hunk.old_span
        new_start, new_count = hunk.new_span
        replacement = edited_lines[new_start - 1 : new_start - 1 + new_count]
        if old_count == 0:
            # pure insertion after view line `old_start` (0 = top of file)
            if old_start > len(kept):
                plan.conflicts.append(
                    Conflict(
                        "putback",
                        f"{path}: view line {old_start} does not map onto the view's"
                        " derivation — re-open the view",
                        path,
                    )
                )
                return
            anchor = kept[old_start - 1] if old_start >= 1 else 0
            operations.append((anchor + 1, 0, replacement))
            source_span = (anchor + 1, 0)
        else:
            if old_start < 1 or old_start + old_count - 1 > len(kept):
                plan.conflicts.append(
                    Conflict(
                        "putback",
                        f"{path}: view lines {_span_text(hunk.old_span)} do not map onto"
                        " the view's derivation — re-open the view",
                        path,
                    )
                )
                return
            positions = kept[old_start - 1 : old_start - 1 + old_count]
            if positions[-1] - positions[0] + 1 != old_count:
                plan.conflicts.append(
                    Conflict(
                        "removed-region",
                        f"{path}: edit at view lines {_span_text(hunk.old_span)} crosses"
                        " a region removed from this variant",
                        path,
                    )
                )
                return
            operations.append((positions[0], old_count, replacement))
            source_span = (positions[0], old_count)
        plan.edits.append(MappedEdit(path, hunk.old_span, source_span))

    for start, delete_count, replacement in sorted(operations, reverse=True):
        base_lines[start - 1 : start - 1 + delete_count] = replacement
    plan.replacements[path] = "".join(base_lines).encode("utf-8")


def _span_text(span: tuple[int, int]) -> str:
    start, count = span
    return f"{start}-{start + max(count, 1) - 1}" if count > 1 else str(start)
