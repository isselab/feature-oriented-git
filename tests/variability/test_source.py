"""Tests for reading model.cfr from worktree vs a commit tree."""

from collections.abc import Callable

from git_feature.domain.variability import model_text, parse_model
from tests.fixtures import RepoBuilder

OLD_MODEL = "abstract App {\n    a ?\n}\n\nOnlyA : App {\n    [ a ]\n}\n"
NEW_MODEL = "abstract App {\n    a ?\n    b ?\n}\n\nBoth : App {\n    [ a ]\n    [ b ]\n}\n"


def test_model_reads_from_worktree_and_from_a_commit(
    repo_builder: Callable[[str], RepoBuilder],
) -> None:
    builder = repo_builder("repo")
    old_sha = builder.commit("old model", files={"model.cfr": OLD_MODEL})
    builder.commit("new model", files={"model.cfr": NEW_MODEL})
    builder.write("model.cfr", NEW_MODEL + "// dirty edit\n")

    worktree = model_text(builder.repo)
    assert worktree is not None and "dirty edit" in worktree

    at_old = model_text(builder.repo, old_sha)
    assert at_old is not None
    module = parse_model(at_old)
    assert [c.name for c in module.clafers] == ["App", "OnlyA"]

    at_head = model_text(builder.repo, "HEAD")
    assert at_head is not None and "Both" in at_head


def test_missing_model_returns_none(repo_builder: Callable[[str], RepoBuilder]) -> None:
    builder = repo_builder("bare")
    builder.commit("no model here", files={"a.txt": "a\n"})
    assert model_text(builder.repo) is None
    assert model_text(builder.repo, "HEAD") is None
