"""Tests for round-trip editing: `git feature view` and `git feature putback`."""

from collections.abc import Callable
from dataclasses import dataclass

import pygit2
import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.gitio import create_commit, read_ref, rewrite_tree, write_ref
from git_feature.identity import ChangeIdMap
from git_feature.store import GitRefStore
from tests.fixtures import RepoBuilder
from tests.test_checkout_dryrun import MODEL

CORE = "def top():\n    return 1\n\ndef bottom():\n    return 2\n"
WITH_AUTH = (
    "def top():\n    return 1\n\ndef auth():\n    return check()\n\ndef bottom():\n    return 2\n"
)


@dataclass
class ViewRepo:
    builder: RepoBuilder
    base_sha: str
    auth_sha: str
    source_branch: str


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fixture(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> ViewRepo:
    builder = repo_builder("repo")
    base_sha = builder.commit("base", files={"model.cfr": MODEL, "app.py": CORE})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    auth_sha = builder.commit("auth block", files={"app.py": WITH_AUTH})
    assert runner.invoke(app, ["annotate", auth_sha, "--feature", "auth"]).exit_code == 0
    return ViewRepo(builder, base_sha, auth_sha, builder.default_branch)


def _source_blob(fixture: ViewRepo, path: str) -> str:
    tip = fixture.builder.repo.references[f"refs/heads/{fixture.source_branch}"].peel(pygit2.Commit)
    return bytes(fixture.builder.repo[tip.tree[path].id].data).decode()


def test_view_switches_and_records_the_session(runner: CliRunner, fixture: ViewRepo) -> None:
    result = runner.invoke(app, ["view", "Minimal"])
    assert result.exit_code == 0, result.output
    repo = fixture.builder.repo
    assert repo.head.shorthand == "variant/Minimal"
    assert (fixture.builder.path / "app.py").read_text() == CORE

    session = GitRefStore(repo).read_view("Minimal")
    assert session is not None
    assert session.source_branch == fixture.source_branch
    assert session.base_commit == fixture.auth_sha
    assert session.variant_commit == read_ref(repo, "refs/heads/variant/Minimal")


def test_putback_of_an_unedited_view_changes_nothing(runner: CliRunner, fixture: ViewRepo) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 0, result.output
    assert "nothing to put back" in result.output
    tip = read_ref(fixture.builder.repo, f"refs/heads/{fixture.source_branch}")
    assert tip == fixture.auth_sha


def test_putback_lands_an_edit_past_a_removed_region(runner: CliRunner, fixture: ViewRepo) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    # `bottom` sits below the removed auth block: view line 5, source line 7
    edited = CORE.replace("return 2", "return 99")
    fixture.builder.write("app.py", edited)

    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 0, result.output
    assert _source_blob(fixture, "app.py") == WITH_AUTH.replace("return 2", "return 99")


def test_putback_refreshes_the_view_onto_the_new_source_commit(
    runner: CliRunner, fixture: ViewRepo
) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    edited = CORE.replace("return 2", "return 99")
    fixture.builder.write("app.py", edited)
    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 0, result.output
    assert "refreshed" in result.output

    repo = fixture.builder.repo
    assert repo.head.shorthand == "variant/Minimal"
    # the refreshed view equals the edited view: nothing gained, nothing lost
    assert (fixture.builder.path / "app.py").read_text() == edited
    session = GitRefStore(repo).read_view("Minimal")
    assert session is not None
    assert session.base_commit == read_ref(repo, f"refs/heads/{fixture.source_branch}")

    # a second putback right away has nothing left to transplant
    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 0, result.output
    assert "nothing to put back" in result.output


def test_putback_insertion_is_anchored_before_the_removed_region(
    runner: CliRunner, fixture: ViewRepo
) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    edited = CORE.replace(
        "def top():\n    return 1\n", "def top():\n    return 1\n\ndef extra():\n    pass\n"
    )
    fixture.builder.write("app.py", edited)

    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 0, result.output
    expected = WITH_AUTH.replace(
        "def top():\n    return 1\n", "def top():\n    return 1\n\ndef extra():\n    pass\n"
    )
    assert _source_blob(fixture, "app.py") == expected


def test_putback_transplants_a_new_file(runner: CliRunner, fixture: ViewRepo) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    fixture.builder.write("src/util.py", "def helper():\n    return 3\n")

    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 0, result.output
    assert _source_blob(fixture, "src/util.py") == "def helper():\n    return 3\n"


def test_putback_mints_a_change_id_for_the_source_commit(
    runner: CliRunner, fixture: ViewRepo
) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    fixture.builder.write("app.py", CORE.replace("return 2", "return 99"))
    assert runner.invoke(app, ["putback"]).exit_code == 0

    repo = fixture.builder.repo
    tip = read_ref(repo, f"refs/heads/{fixture.source_branch}")
    assert tip is not None
    assert ChangeIdMap(GitRefStore(repo)).get(tip) is not None


def test_putback_refuses_an_edit_crossing_a_removed_region(
    runner: CliRunner, fixture: ViewRepo
) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    # rewrite view lines 2-4 (return 1, blank, def bottom) into one line: in the
    # source those lines straddle the removed auth block
    edited = "def top():\n    return bottom_inline()\n    return 2\n"
    fixture.builder.write("app.py", edited)

    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 1
    assert "crosses a region removed from this variant" in result.output
    assert read_ref(fixture.builder.repo, f"refs/heads/{fixture.source_branch}") == (
        fixture.auth_sha
    )


def test_putback_refuses_when_the_source_branch_moved(runner: CliRunner, fixture: ViewRepo) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    repo = fixture.builder.repo
    tree = rewrite_tree(repo, fixture.auth_sha, {"other.txt": b"x\n"})
    sha = create_commit(repo, tree, "advance", [fixture.auth_sha])
    write_ref(repo, f"refs/heads/{fixture.source_branch}", sha)

    fixture.builder.write("app.py", CORE.replace("return 2", "return 99"))
    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 1
    assert "has moved" in result.output


def test_putback_refuses_a_deleted_file(runner: CliRunner, fixture: ViewRepo) -> None:
    fixture.builder.commit("second file", files={"doomed.py": "gone = True\n"})
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    (fixture.builder.path / "doomed.py").unlink()

    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 1
    assert "only edits and new files" in result.output


def test_putback_requires_a_view_branch(runner: CliRunner, fixture: ViewRepo) -> None:
    result = runner.invoke(app, ["putback"])
    assert result.exit_code == 1
    assert "not on a view branch" in result.output


def test_putback_dry_run_reports_the_mapping_without_committing(
    runner: CliRunner, fixture: ViewRepo
) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    fixture.builder.write("app.py", CORE.replace("return 2", "return 99"))

    result = runner.invoke(app, ["putback", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "view lines 5 -> source lines 8" in result.output
    assert read_ref(fixture.builder.repo, f"refs/heads/{fixture.source_branch}") == (
        fixture.auth_sha
    )


def test_view_reopened_from_the_view_branch_refreshes_from_the_source_tip(
    runner: CliRunner, fixture: ViewRepo
) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    repo = fixture.builder.repo
    tree = rewrite_tree(repo, fixture.auth_sha, {"other.txt": b"x\n"})
    sha = create_commit(repo, tree, "advance", [fixture.auth_sha])
    write_ref(repo, f"refs/heads/{fixture.source_branch}", sha)

    result = runner.invoke(app, ["view", "Minimal"])
    assert result.exit_code == 0, result.output
    session = GitRefStore(repo).read_view("Minimal")
    assert session is not None
    assert session.base_commit == sha
    assert (fixture.builder.path / "other.txt").read_text() == "x\n"


def test_view_refresh_refuses_with_uncommitted_edits(runner: CliRunner, fixture: ViewRepo) -> None:
    assert runner.invoke(app, ["view", "Minimal"]).exit_code == 0
    fixture.builder.write("app.py", CORE.replace("return 2", "return 99"))
    result = runner.invoke(app, ["view", "Minimal"])
    assert result.exit_code == 1
    assert "uncommitted edits" in result.output
