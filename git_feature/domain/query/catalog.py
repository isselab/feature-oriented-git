"""Catalog and annotation lookups shared by the query commands."""

import re
from collections.abc import Iterator

from ...store.base import Store
from ...store.types import Annotation

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def presence_features(presence: str) -> set[str]:
    """Feature names referenced by a presence condition (token scan until the algebra lands)."""
    return set(_IDENT.findall(presence))


def iter_annotations(store: Store) -> Iterator[tuple[str, Annotation]]:
    """Yield (change_id, annotation) for every stored annotation."""
    for change_id in store.list_annotated_changes():
        for annotation in store.read_annotations(change_id):
            yield change_id, annotation


def feature_annotations(store: Store, name: str) -> list[tuple[str, Annotation]]:
    """All (change_id, annotation) pairs whose presence condition references a feature."""
    return [
        (change_id, annotation)
        for change_id, annotation in iter_annotations(store)
        if name in presence_features(annotation.presence)
    ]
