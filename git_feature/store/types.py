"""Persisted schema types for the feature store."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

Confidence = Literal["exact", "moved", "fuzzy", "lost"]


class StoreMeta(BaseModel):
    """Store-wide metadata written at initialization."""

    schema_version: int = SCHEMA_VERSION
    tool_version: str = "0"


class FeatureDef(BaseModel):
    """Definition record of a feature."""

    name: str
    description: str = ""
    owners: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    auto_created: bool = False


class RegionAnchor(BaseModel):
    """A hunk pinned to the immutable diff of the change that introduced it."""

    change_id: str
    path: str
    old_span: tuple[int, int]
    new_span: tuple[int, int]
    fingerprint: str


class Annotation(BaseModel):
    """Association of an anchored region with a feature presence condition."""

    anchor: RegionAnchor
    presence: str
    author: str
    ts: datetime
    note: str | None = None


class ChangeIdRecord(BaseModel):
    """One entry of the SHA ↔ change-id map."""

    sha: str
    change_id: str
    patch_id: str | None = None


class RegionDecision(BaseModel):
    """Per-region outcome of a variant projection."""

    anchor: RegionAnchor
    presence: str
    included: bool
    resolved_span: tuple[int, int] | None = None  # overall extent (first..last line)
    resolved_runs: list[tuple[int, int]] | None = None  # exact surviving line runs
    confidence: Confidence | None = None

    def runs(self) -> list[tuple[int, int]]:
        """The region's line runs; falls back to the overall span."""
        if self.resolved_runs:
            return self.resolved_runs
        return [self.resolved_span] if self.resolved_span else []


class DerivationManifest(BaseModel):
    """Record of how a variant was produced from a base commit."""

    instance: str
    base_commit: str
    assignment: dict[str, bool]
    decisions: list[RegionDecision] = Field(default_factory=list)
    created_at: datetime
