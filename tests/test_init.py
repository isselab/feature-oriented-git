"""Tests for `git feature init`."""

import os
import stat
from collections.abc import Callable

import pygit2
import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.identity import ChangeIdMap
from git_feature.store import STORE_REF, GitRefStore
from tests.fixtures import RepoBuilder


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def builder(
    repo_builder: Callable[[str], RepoBuilder], monkeypatch: pytest.MonkeyPatch
) -> RepoBuilder:
    builder = repo_builder("repo")
    builder.commit("one", files={"a.txt": "a\n"})
    builder.commit("two", files={"a.txt": "a\nb\n"})
    monkeypatch.chdir(builder.path)
    return builder


def test_init_creates_store_model_and_hooks(runner: CliRunner, builder: RepoBuilder) -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert STORE_REF in builder.repo.references
    assert GitRefStore(builder.repo).read_meta() is not None
    assert (builder.path / "model.cfr").exists()
    hooks = builder.path / ".git" / "hooks"
    for name in ("post-commit", "post-rewrite"):
        assert (hooks / name).is_file()
        assert os.access(hooks / name, os.X_OK)
        assert (hooks / f"{name}.d" / "50-git-feature").is_file()


def test_init_is_lazy_by_default(runner: CliRunner, builder: RepoBuilder) -> None:
    runner.invoke(app, ["init"])
    cid_map = ChangeIdMap(GitRefStore(builder.repo))
    assert cid_map.get(str(builder.repo.head.target)) is None


def test_init_backfill_maps_all_history(runner: CliRunner, builder: RepoBuilder) -> None:
    result = runner.invoke(app, ["init", "--backfill"])
    assert result.exit_code == 0, result.output
    cid_map = ChangeIdMap(GitRefStore(builder.repo))
    for commit in builder.repo.walk(builder.repo.head.target):
        assert cid_map.get(str(commit.id)) is not None


def test_init_preserves_preexisting_hook(runner: CliRunner, builder: RepoBuilder) -> None:
    hooks = builder.path / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    planted = hooks / "post-commit"
    planted.write_text("#!/bin/sh\necho planted\n")
    planted.chmod(planted.stat().st_mode | stat.S_IXUSR)

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    preserved = hooks / "post-commit.d" / "00-preexisting"
    assert preserved.is_file()
    assert "echo planted" in preserved.read_text()
    assert "chained hook dispatcher" in (hooks / "post-commit").read_text()


def test_second_init_is_a_clean_noop(runner: CliRunner, builder: RepoBuilder) -> None:
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert "already initialized" in result.output
    repo = pygit2.Repository(str(builder.path))
    store_history = list(repo.walk(repo.references[STORE_REF].target))
    assert len(store_history) == 1


def test_second_init_repairs_missing_pieces(runner: CliRunner, builder: RepoBuilder) -> None:
    runner.invoke(app, ["init"])
    (builder.path / ".git" / "hooks" / "post-commit").unlink()
    (builder.path / "model.cfr").unlink()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (builder.path / ".git" / "hooks" / "post-commit").is_file()
    assert (builder.path / "model.cfr").exists()


def test_init_never_overwrites_model_cfr(runner: CliRunner, builder: RepoBuilder) -> None:
    (builder.path / "model.cfr").write_text("// mine\n")
    runner.invoke(app, ["init"])
    assert (builder.path / "model.cfr").read_text() == "// mine\n"


def test_init_outside_a_repo_fails(
    runner: CliRunner, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path_factory.mktemp("empty"))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 1
