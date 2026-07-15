"""Store backend persisting to a dedicated git ref."""

import pygit2

from ..gitio import compare_and_swap_ref, read_ref
from .base import Store

STORE_REF = "refs/feature/store"


class GitRefStore(Store):
    """Store backend on an orphan commit history under `refs/feature/store`."""

    def __init__(self, repo: pygit2.Repository, ref_name: str = STORE_REF) -> None:
        self._repo = repo
        self._ref_name = ref_name
        self._base_sha = read_ref(repo, ref_name)
        self._files = self._load_files()
        self._pending: dict[str, bytes] = {}

    def _read(self, path: str) -> bytes | None:
        if path in self._pending:
            return self._pending[path]
        return self._files.get(path)

    def _write(self, path: str, data: bytes) -> None:
        self._pending[path] = data

    def _list(self, prefix: str) -> list[str]:
        paths = set(self._files) | set(self._pending)
        return sorted(p for p in paths if p.startswith(prefix))

    def commit(self, message: str) -> None:
        merged = {**self._files, **self._pending}
        tree_oid = _build_tree(self._repo, merged)
        sig = _signature(self._repo)
        parents = [self._base_sha] if self._base_sha else []
        new_oid = self._repo.create_commit(None, sig, sig, message, tree_oid, parents)
        compare_and_swap_ref(self._repo, self._ref_name, str(new_oid), expected_old=self._base_sha)
        self._base_sha = str(new_oid)
        self._files = merged
        self._pending = {}

    def _load_files(self) -> dict[str, bytes]:
        if self._base_sha is None:
            return {}
        commit = self._repo[self._base_sha].peel(pygit2.Commit)
        return _flatten_tree(self._repo, commit.tree)


def _flatten_tree(repo: pygit2.Repository, tree: pygit2.Tree, prefix: str = "") -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for entry in tree:
        obj = repo[entry.id]
        name = f"{prefix}{entry.name}"
        if isinstance(obj, pygit2.Tree):
            files.update(_flatten_tree(repo, obj, f"{name}/"))
        elif isinstance(obj, pygit2.Blob):
            files[name] = obj.data
    return files


def _build_tree(repo: pygit2.Repository, files: dict[str, bytes]) -> pygit2.Oid:
    builder = repo.TreeBuilder()
    subdirs: dict[str, dict[str, bytes]] = {}
    for path, data in files.items():
        if "/" in path:
            head, rest = path.split("/", 1)
            subdirs.setdefault(head, {})[rest] = data
        else:
            builder.insert(path, repo.create_blob(data), pygit2.enums.FileMode.BLOB)
    for name, sub in sorted(subdirs.items()):
        builder.insert(name, _build_tree(repo, sub), pygit2.enums.FileMode.TREE)
    return builder.write()


def _signature(repo: pygit2.Repository) -> pygit2.Signature:
    try:
        return repo.default_signature
    except (KeyError, pygit2.GitError):
        return pygit2.Signature("git-feature", "git-feature@localhost")
