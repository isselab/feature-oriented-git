"""Tests for the hook runtime: post-commit minting and post-rewrite migration."""

from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.identity import ChangeIdMap
from git_feature.store import STORE_REF, GitRefStore, StoreMeta
from tests.fixtures import RepoBuilder


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def builder(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> RepoBuilder:
    builder = repo_builder("repo")
    builder.commit("base", files={"a.txt": "a\n"})
    monkeypatch.chdir(builder.path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    return builder


def _cid_map(builder: RepoBuilder) -> ChangeIdMap:
    return ChangeIdMap(GitRefStore(builder.repo))


class TestPostCommit:
    def test_mints_change_id_for_head(self, runner: CliRunner, builder: RepoBuilder) -> None:
        sha = builder.commit("work", files={"a.txt": "a\nb\n"})
        result = runner.invoke(app, ["hook-run", "post-commit"])
        assert result.exit_code == 0, result.output
        record = _cid_map(builder).get(sha)
        assert record is not None
        assert record.patch_id is not None

    def test_rerun_is_a_noop(self, runner: CliRunner, builder: RepoBuilder) -> None:
        builder.commit("work", files={"a.txt": "a\nb\n"})
        runner.invoke(app, ["hook-run", "post-commit"])
        history_before = _store_history_len(builder)
        runner.invoke(app, ["hook-run", "post-commit"])
        assert _store_history_len(builder) == history_before

    def test_without_initialized_store_does_nothing(
        self,
        repo_builder: Callable[[str], RepoBuilder],
        monkeypatch: pytest.MonkeyPatch,
        runner: CliRunner,
    ) -> None:
        builder = repo_builder("bare")
        builder.commit("base", files={"a.txt": "a\n"})
        monkeypatch.chdir(builder.path)
        result = runner.invoke(app, ["hook-run", "post-commit"])
        assert result.exit_code == 0
        assert STORE_REF not in builder.repo.references


class TestPostRewrite:
    def test_amend_migrates_change_id(self, runner: CliRunner, builder: RepoBuilder) -> None:
        old_sha = builder.commit("work", files={"a.txt": "a\nb\n"})
        runner.invoke(app, ["hook-run", "post-commit"])
        old_record = _cid_map(builder).get(old_sha)
        assert old_record is not None

        new_sha = builder.amend("work, amended", files={"a.txt": "a\nb\nc\n"})
        result = runner.invoke(app, ["hook-run", "post-rewrite"], input=f"{old_sha} {new_sha}\n")
        assert result.exit_code == 0, result.output
        new_record = _cid_map(builder).get(new_sha)
        assert new_record is not None
        assert new_record.change_id == old_record.change_id

    def test_rebase_migrates_all_pairs(self, runner: CliRunner, builder: RepoBuilder) -> None:
        builder.branch("feature")
        builder.switch("feature")
        old_one = builder.commit("one", files={"f.txt": "one\n"})
        runner.invoke(app, ["hook-run", "post-commit"])
        old_two = builder.commit("two", files={"f.txt": "one\ntwo\n"})
        runner.invoke(app, ["hook-run", "post-commit"])
        cid_map = _cid_map(builder)
        cid_one = cid_map.get(old_one)
        cid_two = cid_map.get(old_two)
        assert cid_one is not None and cid_two is not None

        builder.switch(builder.default_branch)
        builder.commit("moved on", files={"a.txt": "a\nmoved\n"})
        new_one = builder.commit("one", files={"f.txt": "one\n"})
        new_two = builder.commit("two", files={"f.txt": "one\ntwo\n"})
        pairs = f"{old_one} {new_one}\n{old_two} {new_two}\n"
        result = runner.invoke(app, ["hook-run", "post-rewrite"], input=pairs)
        assert result.exit_code == 0, result.output

        cid_map = _cid_map(builder)
        migrated_one = cid_map.get(new_one)
        migrated_two = cid_map.get(new_two)
        assert migrated_one is not None and migrated_one.change_id == cid_one.change_id
        assert migrated_two is not None and migrated_two.change_id == cid_two.change_id

    def test_pair_for_unmapped_commit_is_skipped(
        self, runner: CliRunner, builder: RepoBuilder
    ) -> None:
        old_sha = builder.commit("never minted", files={"a.txt": "a\nx\n"})
        new_sha = builder.amend("never minted, amended", files={"a.txt": "a\ny\n"})
        result = runner.invoke(app, ["hook-run", "post-rewrite"], input=f"{old_sha} {new_sha}\n")
        assert result.exit_code == 0, result.output
        assert _cid_map(builder).get(new_sha) is None


def test_hook_errors_never_block(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    builder = repo_builder("empty")  # unborn HEAD: post-commit has nothing to resolve
    monkeypatch.chdir(builder.path)
    store = GitRefStore(builder.repo)
    store.write_meta(StoreMeta())
    store.commit("init store")
    result = runner.invoke(app, ["hook-run", "post-commit"])
    assert result.exit_code == 0
    assert "skipped" in result.output


def _store_history_len(builder: RepoBuilder) -> int:
    repo = builder.repo
    return sum(1 for _ in repo.walk(repo.references[STORE_REF].target))
