"""Retro-annotate a repo that predates the tool; every query must agree with ground truth."""

import json
from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.identity import ChangeIdMap
from git_feature.store import GitRefStore
from tests.fixtures import RepoBuilder


def test_retroactive_annotation_and_queries(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    builder = repo_builder("repo")

    # history exists before the tool is ever installed
    core_sha = builder.commit("core", files={"src/core.py": "def core():\n    pass\n"})
    auth_sha = builder.commit("auth", files={"src/auth.py": "def login():\n    return check()\n"})
    ui_sha = builder.commit(
        "ui + docs",
        files={"src/ui.py": "def render():\n    pass\n", "docs/ui.md": "# ui\n"},
    )
    monkeypatch.chdir(builder.path)

    assert runner.invoke(app, ["init"]).exit_code == 0
    model_sha = builder.commit("add model.cfr")

    # retro-annotate: whole commit for auth; only src/* of the mixed commit for ui
    assert runner.invoke(app, ["annotate", auth_sha, "--feature", "auth"]).exit_code == 0
    assert (
        runner.invoke(app, ["annotate", ui_sha, "--feature", "ui", "--path", "src/*"]).exit_code
        == 0
    )

    # lazy minting: only the annotated commits got change-ids
    cid_map = ChangeIdMap(GitRefStore(builder.repo))
    assert cid_map.get(core_sha) is None
    assert cid_map.get(model_sha) is None
    assert cid_map.get(auth_sha) is not None
    assert cid_map.get(ui_sha) is not None

    # list
    result = runner.invoke(app, ["--json", "list"])
    rows = {row["name"]: row for row in json.loads(result.output)}
    assert rows["auth"] == {
        "name": "auth",
        "annotations": 1,
        "changes": 1,
        "auto_created": True,
        "description": "",
    }
    assert rows["ui"]["annotations"] == 1

    # info
    result = runner.invoke(app, ["--json", "info", "ui"])
    payload = json.loads(result.output)
    assert payload["files"] == ["src/ui.py"]  # docs/ui.md excluded by --path
    assert [c["sha"] for c in payload["commits"]] == [ui_sha]

    # whatfeature
    result = runner.invoke(app, ["--json", "whatfeature", auth_sha])
    assert [a["presence"] for a in json.loads(result.output)["annotations"]] == ["auth"]
    result = runner.invoke(app, ["whatfeature", core_sha])
    assert "no features recorded" in result.output

    # coverage: core + model unannotated, auth + ui annotated
    result = runner.invoke(app, ["--json", "coverage"])
    payload = json.loads(result.output)
    assert payload["total"] == 4
    assert payload["annotated"] == 2
    assert set(payload["unannotated"]) == {core_sha, model_sha}

    # blame: every line of src/auth.py belongs to auth
    result = runner.invoke(app, ["--json", "blame", "src/auth.py"])
    assert [row["presence"] for row in json.loads(result.output)] == ["auth", "auth"]

    # status: an edit inside the ui region is attributed to ui
    builder.write("src/ui.py", "def render():\n    return 'fast'\n")
    result = runner.invoke(app, ["--json", "status"])
    payload = json.loads(result.output)
    assert any("src/ui.py" in loc for loc in payload["features"]["ui"])
    assert payload["unassigned"] == []
