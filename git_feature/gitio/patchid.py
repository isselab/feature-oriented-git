"""Stable patch-id: hash of a commit's diff with offsets and whitespace normalized."""

import hashlib

import pygit2

from .diff import commit_diff


def patch_id(repo: pygit2.Repository, rev: str | pygit2.Commit) -> str:
    """Return a hex id identifying a commit's diff regardless of position or whitespace."""
    digest = hashlib.sha1(usedforsecurity=False)
    for file_diff in commit_diff(repo, rev):
        header = f"{file_diff.old_path}\0{file_diff.new_path}\0{file_diff.status}\0"
        digest.update(header.encode("utf-8"))
        for hunk in file_diff.hunks:
            for line in hunk.removed_lines:
                digest.update(b"-" + _normalize(line) + b"\0")
            for line in hunk.added_lines:
                digest.update(b"+" + _normalize(line) + b"\0")
    return digest.hexdigest()


def _normalize(line: str) -> bytes:
    return "".join(line.split()).encode("utf-8")
