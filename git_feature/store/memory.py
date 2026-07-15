"""In-memory store backend for tests."""

from .base import Store


class MemoryStore(Store):
    """Store backend holding everything in a dict; `commits` records messages."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self.commits: list[str] = []

    def _read(self, path: str) -> bytes | None:
        return self._files.get(path)

    def _write(self, path: str, data: bytes) -> None:
        self._files[path] = data

    def _list(self, prefix: str) -> list[str]:
        return sorted(p for p in self._files if p.startswith(prefix))

    def commit(self, message: str) -> None:
        self.commits.append(message)
