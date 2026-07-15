"""Integration tests for the gitio layer against real throwaway repositories."""

from collections.abc import Callable
from pathlib import Path

import pytest

from git_feature import gitio
from tests.fixtures import RepoBuilder

Factory = Callable[[str], RepoBuilder]


@pytest.fixture
def three_commit_repo(repo_builder: Factory) -> tuple[RepoBuilder, list[str]]:
    builder = repo_builder("three")
    c1 = builder.commit(
        "add a and sub/b",
        files={"a.txt": "line1\nline2\n", "sub/b.txt": "b1\n"},
    )
    c2 = builder.commit(
        "modify a",
        files={"a.txt": "line1\nline2-modified\nline3\n"},
    )
    c3 = builder.commit(
        "add c, remove sub/b",
        files={"c.txt": "c1\nc2\n"},
        remove=["sub/b.txt"],
    )
    return builder, [c1, c2, c3]


class TestOpenRepository:
    def test_discovers_from_subdirectory(self, repo_builder: Factory) -> None:
        builder = repo_builder("discover")
        builder.commit("root", files={"sub/deep/x.txt": "x\n"})
        repo = gitio.open_repository(builder.path / "sub" / "deep")
        assert Path(repo.path).resolve() == (builder.path / ".git").resolve()

    def test_raises_outside_a_repository(self, tmp_path: Path) -> None:
        outside = tmp_path / "plain"
        outside.mkdir()
        with pytest.raises(gitio.RepositoryNotFound):
            gitio.open_repository(outside)


class TestCommitDiff:
    def test_root_commit_is_all_additions(
        self, three_commit_repo: tuple[RepoBuilder, list[str]]
    ) -> None:
        builder, (c1, _, _) = three_commit_repo
        files = {f.new_path: f for f in gitio.commit_diff(builder.repo, c1)}
        assert set(files) == {"a.txt", "sub/b.txt"}
        a = files["a.txt"]
        assert a.status == "A"
        assert a.old_path is None
        assert a.hunks == (
            gitio.Hunk(
                old_span=(0, 0),
                new_span=(1, 2),
                header="@@ -0,0 +1,2 @@",
                added_lines=("line1", "line2"),
                removed_lines=(),
            ),
        )

    def test_modification_has_tight_spans(
        self, three_commit_repo: tuple[RepoBuilder, list[str]]
    ) -> None:
        builder, (_, c2, _) = three_commit_repo
        (file,) = gitio.commit_diff(builder.repo, c2)
        assert (file.old_path, file.new_path, file.status) == ("a.txt", "a.txt", "M")
        (hunk,) = file.hunks
        assert hunk.old_span == (2, 1)
        assert hunk.new_span == (2, 2)
        assert hunk.removed_lines == ("line2",)
        assert hunk.added_lines == ("line2-modified", "line3")

    def test_deletion_and_addition(self, three_commit_repo: tuple[RepoBuilder, list[str]]) -> None:
        builder, (_, _, c3) = three_commit_repo
        files = {(f.old_path, f.new_path): f for f in gitio.commit_diff(builder.repo, c3)}
        added = files[(None, "c.txt")]
        assert added.status == "A"
        assert added.hunks[0].added_lines == ("c1", "c2")
        deleted = files[("sub/b.txt", None)]
        assert deleted.status == "D"
        assert deleted.hunks[0].removed_lines == ("b1",)
        assert deleted.hunks[0].new_span == (0, 0)


class TestHistory:
    def test_iter_commits_newest_first(
        self, three_commit_repo: tuple[RepoBuilder, list[str]]
    ) -> None:
        builder, shas = three_commit_repo
        walked = [str(c.id) for c in gitio.iter_commits(builder.repo)]
        assert walked == list(reversed(shas))

    def test_iter_range(self, three_commit_repo: tuple[RepoBuilder, list[str]]) -> None:
        builder, (c1, c2, c3) = three_commit_repo
        walked = [str(c.id) for c in gitio.iter_range(builder.repo, f"{c1}..{c3}")]
        assert walked == [c3, c2]

    def test_iter_range_rejects_non_range(
        self, three_commit_repo: tuple[RepoBuilder, list[str]]
    ) -> None:
        builder, _ = three_commit_repo
        with pytest.raises(ValueError, match="expected 'base..tip'"):
            list(gitio.iter_range(builder.repo, "HEAD"))

    def test_iter_all_commits_covers_unmerged_branches(self, repo_builder: Factory) -> None:
        builder = repo_builder("branches")
        c1 = builder.commit("root", files={"a.txt": "a\n"})
        builder.branch("side")
        c2 = builder.commit("on main", files={"b.txt": "b\n"})
        builder.switch("side")
        c3 = builder.commit("on side", files={"s.txt": "s\n"})
        walked = {str(c.id) for c in gitio.iter_all_commits(builder.repo)}
        assert walked == {c1, c2, c3}

    def test_merge_commit_has_two_parents(self, repo_builder: Factory) -> None:
        builder = repo_builder("merging")
        builder.commit("root", files={"a.txt": "a\n"})
        main = builder.default_branch
        builder.branch("side")
        builder.commit("on main", files={"b.txt": "b\n"})
        builder.switch("side")
        builder.commit("on side", files={"s.txt": "s\n"})
        builder.switch(main)
        merge_sha = builder.merge("side", "merge side")
        merge_commit = gitio.resolve_commit(builder.repo, merge_sha)
        assert len(merge_commit.parents) == 2


class TestRefIo:
    def test_read_missing_ref_returns_none(self, repo_builder: Factory) -> None:
        builder = repo_builder("refs")
        builder.commit("root", files={"a.txt": "a\n"})
        assert gitio.read_ref(builder.repo, "refs/feature/store") is None

    def test_write_and_read_roundtrip(self, repo_builder: Factory) -> None:
        builder = repo_builder("refs")
        c1 = builder.commit("root", files={"a.txt": "a\n"})
        gitio.write_ref(builder.repo, "refs/feature/store", c1)
        assert gitio.read_ref(builder.repo, "refs/feature/store") == c1

    def test_compare_and_swap_success_chain(self, repo_builder: Factory) -> None:
        builder = repo_builder("refs")
        c1 = builder.commit("root", files={"a.txt": "a\n"})
        c2 = builder.commit("second", files={"a.txt": "a2\n"})
        gitio.compare_and_swap_ref(builder.repo, "refs/feature/store", c1, expected_old=None)
        gitio.compare_and_swap_ref(builder.repo, "refs/feature/store", c2, expected_old=c1)
        assert gitio.read_ref(builder.repo, "refs/feature/store") == c2

    def test_compare_and_swap_conflict(self, repo_builder: Factory) -> None:
        builder = repo_builder("refs")
        c1 = builder.commit("root", files={"a.txt": "a\n"})
        c2 = builder.commit("second", files={"a.txt": "a2\n"})
        gitio.write_ref(builder.repo, "refs/feature/store", c2)
        with pytest.raises(gitio.RefUpdateConflict):
            gitio.compare_and_swap_ref(builder.repo, "refs/feature/store", c1, expected_old=c1)
