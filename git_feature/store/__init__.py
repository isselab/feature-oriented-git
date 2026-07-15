"""Feature store: typed persistence for annotations, features, ids, and manifests."""

from .base import Store
from .gitref import STORE_REF, GitRefStore
from .memory import MemoryStore
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
    "StoreMeta",
]
