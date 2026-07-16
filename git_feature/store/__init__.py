"""Feature store: typed persistence for annotations, features, ids, and manifests."""

from .base import Store
from .gitref import STORE_REF, GitRefStore, store_files_at
from .memory import MemoryStore
from .merge import StoreMergeError, merge_stores
from .types import (
    SCHEMA_VERSION,
    Annotation,
    ChangeIdRecord,
    Confidence,
    DerivationManifest,
    FeatureDef,
    RegionAnchor,
    RegionDecision,
    StoreMeta,
    ViewSession,
)

__all__ = [
    "SCHEMA_VERSION",
    "STORE_REF",
    "Annotation",
    "ChangeIdRecord",
    "Confidence",
    "DerivationManifest",
    "FeatureDef",
    "GitRefStore",
    "MemoryStore",
    "RegionAnchor",
    "RegionDecision",
    "Store",
    "StoreMergeError",
    "StoreMeta",
    "ViewSession",
    "merge_stores",
    "store_files_at",
]
