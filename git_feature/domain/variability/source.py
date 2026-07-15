"""Reading model.cfr from the working tree or from a commit's tree."""

from pathlib import Path

import pygit2

from ...gitio import blob_lines

MODEL_FILE = "model.cfr"


def model_text(repo: pygit2.Repository, rev: str | None = None) -> str | None:
    """model.cfr content at a revision (None = working tree); None if absent."""
    if rev is None:
        if repo.workdir is None:
            return None
        path = Path(repo.workdir) / MODEL_FILE
        return path.read_text("utf-8") if path.exists() else None
    lines = blob_lines(repo, rev, MODEL_FILE)
    return None if lines is None else "\n".join(lines) + "\n"
