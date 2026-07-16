"""Variant materialization driver shared by checkout, view, and putback."""

from dataclasses import dataclass

import pygit2

from ...gitio import compare_and_swap_ref, create_commit, read_ref
from ...store.base import Store
from ...store.types import DerivationManifest
from .materialize import materialize_tree, verify_tree
from .pipeline import Conflict, Projection


def variant_ref(instance: str) -> str:
    """The branch ref a variant is materialized on."""
    return f"refs/heads/variant/{instance}"


class ProjectionConflicts(Exception):
    """The projection reported conflicts; nothing was materialized."""

    def __init__(self, projection: Projection) -> None:
        super().__init__(f"{len(projection.conflicts)} conflict(s)")
        self.projection = projection


class VariantExists(Exception):
    """The variant branch already exists and rebuilding was not requested."""

    def __init__(self, instance: str) -> None:
        super().__init__(f"variant {instance} already exists")
        self.instance = instance


class VerificationFailed(Exception):
    """The derived tree failed verification; the variant ref was not moved."""

    def __init__(self, conflicts: list[Conflict], refname: str) -> None:
        super().__init__(f"verification failed — {refname} was not updated")
        self.conflicts = conflicts
        self.refname = refname


@dataclass
class Derivation:
    """Outcome of materializing a projection onto the variant branch."""

    sha: str
    manifest: DerivationManifest
    up_to_date: bool


def materialize_variant(
    repo: pygit2.Repository, store: Store, projection: Projection, *, refresh: bool
) -> Derivation:
    """Stages 3–4: build, commit, verify, and persist the variant for a clean projection."""
    if projection.conflicts:
        raise ProjectionConflicts(projection)

    instance = projection.instance
    refname = variant_ref(instance)
    current_tip = read_ref(repo, refname)
    manifest = projection.manifest()

    if current_tip is not None and _up_to_date(store, instance, manifest):
        return Derivation(sha=current_tip, manifest=manifest, up_to_date=True)
    if current_tip is not None and not refresh:
        raise VariantExists(instance)

    tree = materialize_tree(repo, projection)
    parents = [current_tip] if current_tip else []
    sha = create_commit(
        repo, tree, f"derive variant {instance} from {projection.base_sha[:12]}", parents
    )

    conflicts = verify_tree(repo, store, sha, projection.base_sha, projection.decisions)
    if conflicts:
        raise VerificationFailed(conflicts, refname)

    compare_and_swap_ref(repo, refname, sha, expected_old=current_tip)
    store.write_manifest(instance, manifest)
    store.commit(f"derive variant {instance}")
    return Derivation(sha=sha, manifest=manifest, up_to_date=False)


def _up_to_date(store: Store, instance: str, manifest: DerivationManifest) -> bool:
    existing = store.read_manifest(instance)
    if existing is None:
        return False
    return (
        existing.base_commit == manifest.base_commit
        and existing.assignment == manifest.assignment
        and [d.model_dump(exclude={"confidence"}) for d in existing.decisions]
        == [d.model_dump(exclude={"confidence"}) for d in manifest.decisions]
    )
