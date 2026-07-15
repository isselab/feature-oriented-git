"""Identity layer: change-id map, patch-id reconcile, region anchors + resolver."""

from .change_id import ChangeIdMap, backfill, mint_change_id
from .region import (
    RegionResolver,
    Resolution,
    anchor_from_hunk,
    normalized_fingerprint,
    original_added_lines,
)

__all__ = [
    "ChangeIdMap",
    "RegionResolver",
    "Resolution",
    "anchor_from_hunk",
    "backfill",
    "mint_change_id",
    "normalized_fingerprint",
    "original_added_lines",
]
