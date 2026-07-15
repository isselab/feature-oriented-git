"""Tree rewriting and commit creation for derived variants."""

import pygit2

from .diff import resolve_commit


def blob_data(repo: pygit2.Repository, rev: str | pygit2.Commit, path: str) -> bytes | None:
    """Raw bytes of a file at a revision, or None if absent or not a blob."""
    commit = resolve_commit(repo, rev)
    try:
        entry = commit.tree[path]
    except KeyError:
        return None
    obj = repo[entry.id]
    return bytes(obj.data) if isinstance(obj, pygit2.Blob) else None


def rewrite_tree(
    repo: pygit2.Repository, rev: str | pygit2.Commit, replacements: dict[str, bytes]
) -> pygit2.Oid:
    """A copy of a commit's tree with the given files replaced; all else shared by OID."""
    commit = resolve_commit(repo, rev)
    return _rewrite(repo, commit.tree, replacements)


def _rewrite(
    repo: pygit2.Repository, tree: pygit2.Tree, replacements: dict[str, bytes]
) -> pygit2.Oid:
    nested: dict[str, dict[str, bytes]] = {}
    direct: dict[str, bytes] = {}
    for path, data in replacements.items():
        head, sep, rest = path.partition("/")
        if sep:
            nested.setdefault(head, {})[rest] = data
        else:
            direct[head] = data

    builder = repo.TreeBuilder(tree)
    for name, data in direct.items():
        builder.insert(name, repo.create_blob(data), pygit2.enums.FileMode.BLOB)
    for name, sub in nested.items():
        entry = tree[name]
        subtree = repo[entry.id]
        if not isinstance(subtree, pygit2.Tree):
            raise KeyError(f"'{name}' is not a directory")
        builder.insert(name, _rewrite(repo, subtree, sub), pygit2.enums.FileMode.TREE)
    return builder.write()


def create_commit(
    repo: pygit2.Repository, tree: pygit2.Oid, message: str, parents: list[str]
) -> str:
    """Create a commit object (no ref updated); returns its sha."""
    try:
        signature = repo.default_signature
    except (KeyError, pygit2.GitError):
        signature = pygit2.Signature("git-feature", "git-feature@localhost")
    oid = repo.create_commit(None, signature, signature, message, tree, parents)
    return str(oid)


def checkout_branch(repo: pygit2.Repository, refname: str) -> None:
    """Switch the working tree and HEAD to a branch (safe strategy: no overwrites)."""
    repo.checkout(refname)
