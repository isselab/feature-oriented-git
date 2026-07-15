"""Shared pytest fixtures."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.identity import ChangeIdMap
from git_feature.store import GitRefStore
from tests.fixtures import RepoBuilder


@pytest.fixture
def repo_builder(tmp_path: Path) -> Callable[[str], RepoBuilder]:
    """Factory creating named throwaway repositories under tmp_path."""

    def make(name: str = "repo") -> RepoBuilder:
        path = tmp_path / name
        path.mkdir()
        return RepoBuilder(path)

    return make


@dataclass
class AnnotatedRepo:
    """Initialized repo with two annotated feature commits and a release branch."""

    builder: RepoBuilder
    base_sha: str
    auth_sha: str
    ui_sha: str
    auth_cid: str
    ui_cid: str


@pytest.fixture
def annotated_repo(
    repo_builder: Callable[[str], RepoBuilder], monkeypatch: pytest.MonkeyPatch
) -> AnnotatedRepo:
    """Fixture repo: base → init → auth commit (annotated) → ui commit (annotated).

    A 'release' branch contains the auth commit but not the ui commit.
    """
    runner = CliRunner()
    builder = repo_builder("annotated")
    builder.commit("base", files={"src/core.py": "def core():\n    pass\n"})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    base_sha = builder.commit("add model.cfr")

    auth_sha = builder.commit(
        "add login", files={"src/auth/login.py": "def login():\n    return check()\n"}
    )
    builder.branch("release")
    ui_sha = builder.commit(
        "add render", files={"src/ui/render.py": "def render():\n    return draw()\n"}
    )
    assert runner.invoke(app, ["annotate", auth_sha, "--feature", "auth"]).exit_code == 0
    assert runner.invoke(app, ["annotate", ui_sha, "--feature", "ui"]).exit_code == 0

    cid_map = ChangeIdMap(GitRefStore(builder.repo))
    auth_record = cid_map.get(auth_sha)
    ui_record = cid_map.get(ui_sha)
    assert auth_record is not None and ui_record is not None
    return AnnotatedRepo(
        builder=builder,
        base_sha=base_sha,
        auth_sha=auth_sha,
        ui_sha=ui_sha,
        auth_cid=auth_record.change_id,
        ui_cid=ui_record.change_id,
    )
