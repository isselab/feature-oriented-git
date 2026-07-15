"""Shared pytest fixtures."""

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.fixtures import RepoBuilder


@pytest.fixture
def repo_builder(tmp_path: Path) -> Callable[[str], RepoBuilder]:
    """Factory creating named throwaway repositories under tmp_path."""

    def make(name: str = "repo") -> RepoBuilder:
        path = tmp_path / name
        path.mkdir()
        return RepoBuilder(path)

    return make
