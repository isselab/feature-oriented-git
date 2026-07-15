"""`git feature doctor` — health check for store, hooks, and change-id map."""

import json
from dataclasses import dataclass

import pygit2
import typer

from ..gitio import RepositoryNotFound, iter_all_commits, open_repository, read_ref
from ..gitio.hooks import hooks_installed
from ..identity import ChangeIdMap
from ..store import STORE_REF, GitRefStore
from ..store.types import SCHEMA_VERSION


@dataclass(frozen=True)
class Check:
    """One doctor finding: ok, info (fine under lazy minting), or problem."""

    level: str  # "ok" | "info" | "problem"
    name: str
    detail: str
    hint: str | None = None


def run(ctx: typer.Context) -> None:
    try:
        repo = open_repository()
    except RepositoryNotFound as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    checks = _run_checks(repo)
    problems = [c for c in checks if c.level == "problem"]

    if ctx.obj.get("json"):
        payload = {
            "healthy": not problems,
            "checks": [
                {"level": c.level, "name": c.name, "detail": c.detail, "hint": c.hint}
                for c in checks
            ],
        }
        typer.echo(json.dumps(payload))
    else:
        for check in checks:
            marker = {"ok": "ok", "info": "--", "problem": "!!"}[check.level]
            typer.echo(f"{marker} {check.name}: {check.detail}")
            if check.hint and check.level != "ok":
                typer.echo(f"     hint: {check.hint}")
        typer.echo("healthy" if not problems else f"{len(problems)} problem(s) found")
    if problems:
        raise typer.Exit(1)


def _run_checks(repo: pygit2.Repository) -> list[Check]:
    checks = []
    if read_ref(repo, STORE_REF) is None:
        checks.append(
            Check("problem", "store", "refs/feature/store missing", "run 'git feature init'")
        )
        return checks

    store = GitRefStore(repo)
    meta = store.read_meta()
    if meta is None:
        checks.append(
            Check("problem", "store", "meta.json missing or unreadable", "run 'git feature init'")
        )
        return checks
    if meta.schema_version > SCHEMA_VERSION:
        checks.append(
            Check(
                "problem",
                "store",
                f"schema version {meta.schema_version} is newer than supported {SCHEMA_VERSION}",
                "upgrade git-feature",
            )
        )
    else:
        checks.append(Check("ok", "store", f"readable, schema version {meta.schema_version}"))

    for name, installed in hooks_installed(repo).items():
        if installed:
            checks.append(Check("ok", f"hook {name}", "installed and chained"))
        else:
            checks.append(
                Check(
                    "problem",
                    f"hook {name}",
                    "missing or not chained",
                    "run 'git feature init' to reinstall hooks",
                )
            )

    cid_map = ChangeIdMap(store)
    mapped = {record.change_id for record in cid_map.iter_records()}
    dangling = [cid for cid in store.list_annotated_changes() if cid not in mapped]
    if dangling:
        checks.append(
            Check(
                "problem",
                "annotations",
                f"{len(dangling)} annotation file(s) reference unknown change-ids",
                "run 'git feature reconcile'",
            )
        )
    else:
        checks.append(Check("ok", "annotations", "all reference known change-ids"))

    unmapped = sum(1 for c in iter_all_commits(repo) if cid_map.get(str(c.id)) is None)
    if unmapped:
        checks.append(
            Check(
                "info",
                "change-id map",
                f"{unmapped} commit(s) without change-ids (normal with lazy minting)",
                "run 'git feature reconcile' to link imports, or 'init --backfill' to mint all",
            )
        )
    else:
        checks.append(Check("ok", "change-id map", "every reachable commit is mapped"))
    return checks
