"""Three-way merge of diverged feature stores (union annotations, structured map merge)."""

from pydantic import TypeAdapter

from .types import (
    Annotation,
    ChangeIdRecord,
    DerivationManifest,
    FeatureDef,
    StoreMeta,
    ViewSession,
)

_ANNOTATIONS = TypeAdapter(list[Annotation])
_SHARD = TypeAdapter(dict[str, ChangeIdRecord])


class StoreMergeError(Exception):
    """The two stores cannot be merged automatically."""


def merge_stores(
    base: dict[str, bytes], ours: dict[str, bytes], theirs: dict[str, bytes]
) -> tuple[dict[str, bytes], list[str]]:
    """Merge two diverged store trees; returns the merged files and human-readable notes.

    Every rule is deterministic and symmetric, so both machines converge on the
    same content: change-ids minted twice keep the older ULID (annotations of the
    newer one are re-keyed), annotation lists are unioned, feature definitions are
    merged field-wise, and manifests/views keep the newest record.
    """
    notes: list[str] = []
    merged: dict[str, bytes] = {}

    merged["meta.json"] = _merge_meta(ours, theirs)
    records, remap = _merge_changeids(ours, theirs, notes)
    for shard, content in _shards(records).items():
        merged[shard] = content
    for path, content in _merge_annotations(ours, theirs, remap).items():
        merged[path] = content

    for path in sorted(set(ours) | set(theirs)):
        prefix = path.partition("/")[0] + "/"
        if path == "meta.json" or prefix in ("changeids/", "annotations/"):
            continue
        our_raw, their_raw = ours.get(path), theirs.get(path)
        if our_raw == their_raw or their_raw is None:
            merged[path] = our_raw  # type: ignore[assignment]
        elif our_raw is None:
            merged[path] = their_raw
        elif prefix == "features/":
            merged[path] = _merge_feature(base.get(path), our_raw, their_raw, path, notes)
        elif prefix == "variants/":
            merged[path] = _newest(our_raw, their_raw, DerivationManifest, path, notes)
        elif prefix == "views/":
            merged[path] = _newest(our_raw, their_raw, ViewSession, path, notes)
        else:
            merged[path] = our_raw
            notes.append(f"{path}: changed on both sides; kept the local version")
    return merged, notes


def _merge_meta(ours: dict[str, bytes], theirs: dict[str, bytes]) -> bytes:
    our_raw, their_raw = ours.get("meta.json"), theirs.get("meta.json")
    if our_raw is None or their_raw is None:
        raw = our_raw or their_raw
        if raw is None:
            raise StoreMergeError("neither store has meta.json")
        return raw
    our_meta = StoreMeta.model_validate_json(our_raw)
    their_meta = StoreMeta.model_validate_json(their_raw)
    if our_meta.schema_version != their_meta.schema_version:
        raise StoreMergeError(
            f"schema versions differ ({our_meta.schema_version} vs"
            f" {their_meta.schema_version}) — upgrade the tool on both sides first"
        )
    return our_raw


def _merge_changeids(
    ours: dict[str, bytes], theirs: dict[str, bytes], notes: list[str]
) -> tuple[dict[str, ChangeIdRecord], dict[str, str]]:
    """Union of both maps; a sha minted twice keeps the older (smaller) ULID."""
    records = _parse_records(ours)
    remap: dict[str, str] = {}
    for sha, their_record in _parse_records(theirs).items():
        mine = records.get(sha)
        if mine is None:
            records[sha] = their_record
            continue
        if mine.change_id == their_record.change_id:
            if mine.patch_id is None and their_record.patch_id is not None:
                records[sha] = their_record
            continue
        winner, loser = sorted((mine.change_id, their_record.change_id))
        remap[loser] = winner
        kept = mine if mine.change_id == winner else their_record
        other = their_record if kept is mine else mine
        if kept.patch_id is None and other.patch_id is not None:
            kept = kept.model_copy(update={"patch_id": other.patch_id})
        records[sha] = kept
        notes.append(f"{sha[:12]}: change-id minted on both sides; kept {winner}")
    resolved = {
        sha: record.model_copy(update={"change_id": _canonical(record.change_id, remap)})
        for sha, record in records.items()
    }
    return resolved, remap


def _canonical(change_id: str, remap: dict[str, str]) -> str:
    while change_id in remap:
        change_id = remap[change_id]
    return change_id


def _parse_records(files: dict[str, bytes]) -> dict[str, ChangeIdRecord]:
    records: dict[str, ChangeIdRecord] = {}
    for path, raw in files.items():
        if path.startswith("changeids/"):
            records.update(_SHARD.validate_json(raw))
    return records


def _shards(records: dict[str, ChangeIdRecord]) -> dict[str, bytes]:
    shards: dict[str, dict[str, ChangeIdRecord]] = {}
    for sha, record in records.items():
        shards.setdefault(f"changeids/map-{sha[:2]}.json", {})[sha] = record
    return {
        path: _SHARD.dump_json(dict(sorted(shard.items())), indent=2)
        for path, shard in shards.items()
    }


def _merge_annotations(
    ours: dict[str, bytes], theirs: dict[str, bytes], remap: dict[str, str]
) -> dict[str, bytes]:
    """Union both sides' annotation lists, re-keyed through the change-id remap."""
    combined: dict[str, dict[str, Annotation]] = {}
    for side in (ours, theirs):
        for path, raw in side.items():
            if not path.startswith("annotations/"):
                continue
            change_id = _canonical(path.removeprefix("annotations/").removesuffix(".json"), remap)
            bucket = combined.setdefault(change_id, {})
            for annotation in _ANNOTATIONS.validate_json(raw):
                bucket[annotation.model_dump_json()] = annotation
    return {
        f"annotations/{change_id}.json": _ANNOTATIONS.dump_json(
            sorted(bucket.values(), key=lambda a: (a.ts.isoformat(), a.presence)), indent=2
        )
        for change_id, bucket in combined.items()
    }


def _merge_feature(
    base_raw: bytes | None, our_raw: bytes, their_raw: bytes, path: str, notes: list[str]
) -> bytes:
    base = FeatureDef.model_validate_json(base_raw) if base_raw else None
    our = FeatureDef.model_validate_json(our_raw)
    their = FeatureDef.model_validate_json(their_raw)
    description = our.description
    if our.description != their.description:
        if base is not None and our.description == base.description:
            description = their.description
        elif base is None or their.description != base.description:
            description = min(our.description, their.description, key=lambda d: (len(d), d))
            notes.append(f"{path}: descriptions differ; kept {description!r}")
    merged = FeatureDef(
        name=our.name,
        description=description,
        owners=sorted({*our.owners, *their.owners}),
        tags=sorted({*our.tags, *their.tags}),
        links=sorted({*our.links, *their.links}),
        auto_created=our.auto_created and their.auto_created,
    )
    return merged.model_dump_json(indent=2).encode("utf-8")


def _newest(
    our_raw: bytes,
    their_raw: bytes,
    model: type[DerivationManifest] | type[ViewSession],
    path: str,
    notes: list[str],
) -> bytes:
    our = model.model_validate_json(our_raw)
    their = model.model_validate_json(their_raw)
    if their.created_at > our.created_at:
        notes.append(f"{path}: kept the newer remote record")
        return their_raw
    return our_raw
