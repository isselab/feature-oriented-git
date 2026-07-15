"""`git feature variant list` — list derived variants and their staleness."""

import json

import pygit2
import typer

from ..gitio import read_ref
from .common import json_mode, require_repo, require_store


def run(ctx: typer.Context) -> None:
    repo = require_repo()
    store = require_store(repo)

    rows = []
    lines = []
    for name in store.list_variants():
        manifest = store.read_manifest(name)
        if manifest is None:
            continue
        tip = read_ref(repo, f"refs/heads/variant/{name}")
        disabled = sorted(f for f, on in manifest.assignment.items() if not on)
        branch = f"variant/{name}" if tip else None
        stale = _is_stale(repo, name, manifest.base_commit)
        rows.append(
            {
                "name": name,
                "base_commit": manifest.base_commit,
                "disabled": disabled,
                "branch": branch,
                "stale": stale,
            }
        )
        lines.append(
            f"{name}: {branch or 'branch missing!'} from {manifest.base_commit[:12]}"
            f" (disabled: {', '.join(disabled) or '(none)'}) [{'stale' if stale else 'current'}]"
        )

    if json_mode(ctx):
        typer.echo(json.dumps(rows))
        return
    if not lines:
        typer.echo("no variants derived yet (see 'git feature checkout')")
        return
    for line in lines:
        typer.echo(line)


def _is_stale(repo: pygit2.Repository, name: str, base_sha: str) -> bool:
    """Stale = the source moved past the base (HEAD on the variant branch doesn't count)."""
    if repo.head_is_unborn or repo.head.shorthand == f"variant/{name}":
        return False
    head = str(repo.head.target)
    if head == base_sha:
        return False
    try:
        return repo.descendant_of(head, base_sha)
    except (KeyError, pygit2.GitError):
        return False
