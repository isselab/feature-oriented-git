"""Typed store interface over an abstract path→bytes backend."""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from pydantic import TypeAdapter

from .types import (
    Annotation,
    ChangeIdRecord,
    DerivationManifest,
    FeatureDef,
    StoreMeta,
)

_META_PATH = "meta.json"
_ANNOTATIONS = TypeAdapter(list[Annotation])
_CHANGEID_SHARD = TypeAdapter(dict[str, ChangeIdRecord])


class Store(ABC):
    """Feature store: typed reads/writes staged in memory until `commit`."""

    @abstractmethod
    def _read(self, path: str) -> bytes | None:
        """Return the content stored at a path, or None."""

    @abstractmethod
    def _write(self, path: str, data: bytes) -> None:
        """Stage content for a path."""

    @abstractmethod
    def _list(self, prefix: str) -> list[str]:
        """Return all paths under a prefix, sorted."""

    @abstractmethod
    def commit(self, message: str) -> None:
        """Persist all staged writes atomically."""

    def read_meta(self) -> StoreMeta | None:
        data = self._read(_META_PATH)
        return None if data is None else StoreMeta.model_validate_json(data)

    def write_meta(self, meta: StoreMeta) -> None:
        self._write(_META_PATH, _encode(meta.model_dump_json(indent=2)))

    def read_feature(self, name: str) -> FeatureDef | None:
        data = self._read(f"features/{name}.json")
        return None if data is None else FeatureDef.model_validate_json(data)

    def write_feature(self, feature: FeatureDef) -> None:
        self._write(f"features/{feature.name}.json", _encode(feature.model_dump_json(indent=2)))

    def list_features(self) -> list[str]:
        return [_basename(p, "features/") for p in self._list("features/")]

    def read_annotations(self, change_id: str) -> list[Annotation]:
        data = self._read(f"annotations/{change_id}.json")
        return [] if data is None else _ANNOTATIONS.validate_json(data)

    def write_annotations(self, change_id: str, annotations: list[Annotation]) -> None:
        data = _ANNOTATIONS.dump_json(annotations, indent=2)
        self._write(f"annotations/{change_id}.json", data)

    def list_annotated_changes(self) -> list[str]:
        return [_basename(p, "annotations/") for p in self._list("annotations/")]

    def get_changeid(self, sha: str) -> ChangeIdRecord | None:
        return self._read_shard(sha).get(sha)

    def put_changeid(self, record: ChangeIdRecord) -> None:
        shard = self._read_shard(record.sha)
        shard[record.sha] = record
        data = _CHANGEID_SHARD.dump_json(dict(sorted(shard.items())), indent=2)
        self._write(_shard_path(record.sha), data)

    def iter_changeids(self) -> Iterator[ChangeIdRecord]:
        for path in self._list("changeids/"):
            data = self._read(path)
            if data is not None:
                yield from _CHANGEID_SHARD.validate_json(data).values()

    def read_manifest(self, name: str) -> DerivationManifest | None:
        data = self._read(f"variants/{name}.json")
        return None if data is None else DerivationManifest.model_validate_json(data)

    def write_manifest(self, name: str, manifest: DerivationManifest) -> None:
        self._write(f"variants/{name}.json", _encode(manifest.model_dump_json(indent=2)))

    def list_variants(self) -> list[str]:
        return [_basename(p, "variants/") for p in self._list("variants/")]

    def _read_shard(self, sha: str) -> dict[str, ChangeIdRecord]:
        data = self._read(_shard_path(sha))
        return {} if data is None else _CHANGEID_SHARD.validate_json(data)


def _shard_path(sha: str) -> str:
    return f"changeids/map-{sha[:2]}.json"


def _basename(path: str, prefix: str) -> str:
    return path.removeprefix(prefix).removesuffix(".json")


def _encode(text: str) -> bytes:
    return text.encode("utf-8")
