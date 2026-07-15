"""An annotation survives amend, rebase, and a foreign cherry-pick end to end."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from git_feature.cli import app
from git_feature.gitio import blob_lines, commit_diff
from git_feature.identity import ChangeIdMap, RegionResolver, anchor_from_hunk
from git_feature.store import Annotation, GitRefStore
from tests.fixtures import RepoBuilder

BASE = "import os\n\ndef main():\n    run()\n"
REGION = "def auth():\n    check()\n    return token()\n"
WITH_REGION = BASE + "\n" + REGION
MAIN_ADVANCED = "import sys\n" + BASE
REBASED = "import sys\n" + WITH_REGION


def test_annotation_survives_amend_rebase_and_cherry_pick(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    builder = repo_builder("repo")
    builder.commit("base", files={"a.py": BASE})
    monkeypatch.chdir(builder.path)

    # init (lazy: no backfill) and track the generated model.cfr
    assert runner.invoke(app, ["init"]).exit_code == 0
    builder.commit("track model.cfr")
    main = builder.default_branch

    # commit the region on a feature branch; the post-commit hook mints its change-id
    builder.branch("feature")
    builder.switch("feature")
    r1 = builder.commit("add auth region", files={"a.py": WITH_REGION})
    assert runner.invoke(app, ["hook-run", "post-commit"]).exit_code == 0
    store = GitRefStore(builder.repo)
    record = ChangeIdMap(store).get(r1)
    assert record is not None

    # annotate the region by hand through the store API (annotate command not built yet)
    (file_diff,) = [d for d in commit_diff(builder.repo, r1) if d.new_path == "a.py"]
    (hunk,) = file_diff.hunks
    anchor = anchor_from_hunk(record.change_id, "a.py", hunk)
    annotation = Annotation(anchor=anchor, presence="auth", author="test", ts=datetime.now(tz=UTC))
    store.write_annotations(record.change_id, [annotation])
    store.commit("annotate auth region")

    # amend: git would fire post-rewrite with the old/new pair
    r2 = builder.amend("add auth region (amended)")
    assert runner.invoke(app, ["hook-run", "post-rewrite"], input=f"{r1} {r2}\n").exit_code == 0

    # main advances; "rebase" the feature commit onto it (fixture-simulated) + post-rewrite
    builder.switch(main)
    builder.commit("advance main", files={"a.py": MAIN_ADVANCED})
    builder.branch("feature-rebased")
    builder.switch("feature-rebased")
    r3 = builder.commit("add auth region", files={"a.py": REBASED})
    assert runner.invoke(app, ["hook-run", "post-rewrite"], input=f"{r2} {r3}\n").exit_code == 0

    # cross-clone cherry-pick: same patch lands on a release branch with no hooks involved
    builder.switch(main)
    builder.branch("release")
    builder.switch("release")
    c4 = builder.commit("pick auth region", files={"a.py": REBASED})
    assert runner.invoke(app, ["reconcile"]).exit_code == 0

    # identity: every incarnation shares one change-id
    cid_map = ChangeIdMap(GitRefStore(builder.repo))
    shas = set(cid_map.shas_for(record.change_id))
    assert {r1, r2, r3, c4} <= shas

    # the stored annotation still resolves to the right lines everywhere
    stored = GitRefStore(builder.repo).read_annotations(record.change_id)
    assert stored == [annotation]
    resolver = RegionResolver(builder.repo, cid_map)
    for target in ("feature-rebased", "release"):
        resolution = resolver.resolve(anchor, target)
        assert resolution.confidence == "exact", target
        assert resolution.span is not None
        start, length = resolution.span
        assert start == anchor.new_span[0] + 1  # one line was inserted above during the rebase
        lines = blob_lines(builder.repo, target, "a.py")
        assert lines is not None
        region_lines = lines[start - 1 : start - 1 + length]
        assert region_lines[-3:] == ["def auth():", "    check()", "    return token()"]
