"""`git feature reconcile` — re-link commits that arrived outside the hooks."""

import json

import typer

from ..gitio import RepositoryNotFound, open_repository
from ..identity import ChangeIdMap
from ..identity.reconcile import Ambiguity, Link, apply_links, plan_reconcile
from ..store import GitRefStore


def run(ctx: typer.Context, *, dry_run: bool, interactive: bool) -> None:
    try:
        repo = open_repository()
    except RepositoryNotFound as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    store = GitRefStore(repo)
    if store.read_meta() is None:
        typer.echo("error: not initialized (run 'git feature init')", err=True)
        raise typer.Exit(1)

    cid_map = ChangeIdMap(store)
    plan = plan_reconcile(repo, cid_map)
    if interactive and plan.ambiguous:
        plan.links.extend(_resolve_interactively(plan.ambiguous))
        plan.ambiguous = []

    if ctx.obj.get("json"):
        typer.echo(json.dumps(_as_json(plan.links, plan.ambiguous, plan.unmatched, dry_run)))
    else:
        _print_report(plan.links, plan.ambiguous, plan.unmatched, dry_run)

    if not dry_run and plan.links:
        apply_links(cid_map, plan.links)
        store.commit(f"reconcile {len(plan.links)} commits")


def _resolve_interactively(ambiguous: list[Ambiguity]) -> list[Link]:
    links = []
    for item in ambiguous:
        typer.echo(f"commit {item.sha[:12]} matches several changes:")
        for i, (change_id, score) in enumerate(item.candidates, start=1):
            typer.echo(f"  [{i}] {change_id} (score {score:.2f})")
        choice = typer.prompt("link to which change-id? (0 = skip)", type=int, default=0)
        if 1 <= choice <= len(item.candidates):
            change_id, score = item.candidates[choice - 1]
            links.append(
                Link(item.sha, change_id, via="interactive", score=score, patch_id=item.patch_id)
            )
    return links


def _print_report(
    links: list[Link], ambiguous: list[Ambiguity], unmatched: list[str], dry_run: bool
) -> None:
    verb = "would link" if dry_run else "linked"
    for link in links:
        typer.echo(f"{verb} {link.sha[:12]} -> {link.change_id} ({link.via}, {link.score:.2f})")
    for item in ambiguous:
        names = ", ".join(cid for cid, _ in item.candidates)
        typer.echo(f"ambiguous {item.sha[:12]}: candidates {names} (use --interactive)")
    if unmatched:
        typer.echo(f"{len(unmatched)} commits have no counterpart (left unmapped)")
    if not links and not ambiguous:
        typer.echo("nothing to reconcile")


def _as_json(
    links: list[Link], ambiguous: list[Ambiguity], unmatched: list[str], dry_run: bool
) -> dict[str, object]:
    return {
        "dry_run": dry_run,
        "links": [
            {"sha": x.sha, "change_id": x.change_id, "via": x.via, "score": x.score} for x in links
        ],
        "ambiguous": [
            {"sha": x.sha, "candidates": [{"change_id": c, "score": s} for c, s in x.candidates]}
            for x in ambiguous
        ],
        "unmatched": unmatched,
    }
