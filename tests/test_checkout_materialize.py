"""Tests for full `git feature checkout`: materialize, verify, refresh, idempotence."""

from collections.abc import Callable
from dataclasses import dataclass

import pygit2
import pytest
from typer.testing import CliRunner

import git_feature.domain.derivation.pipeline as pipeline_module
from git_feature.cli import app
from git_feature.gitio import create_commit, read_ref, rewrite_tree, write_ref
from git_feature.identity import RegionResolver, Resolution
from git_feature.store import GitRefStore
from tests.fixtures import RepoBuilder
from tests.test_checkout_dryrun import BASE, MODEL, WITH_AUTH, WITH_BOTH


@dataclass
class VariantRepo:
    builder: RepoBuilder
    base_sha: str
    auth_sha: str
    ui_sha: str


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fixture(
    repo_builder: Callable[[str], RepoBuilder],
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> VariantRepo:
    builder = repo_builder("repo")
    base_sha = builder.commit("base", files={"model.cfr": MODEL, "shared.py": BASE})
    monkeypatch.chdir(builder.path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    auth_sha = builder.commit("auth block", files={"shared.py": WITH_AUTH})
    ui_sha = builder.commit("ui block", files={"shared.py": WITH_BOTH})
    assert runner.invoke(app, ["annotate", auth_sha, "--feature", "auth"]).exit_code == 0
    assert runner.invoke(app, ["annotate", ui_sha, "--feature", "ui"]).exit_code == 0
    return VariantRepo(builder, base_sha, auth_sha, ui_sha)


def _variant_blob(builder: RepoBuilder, instance: str, path: str) -> bytes:
    tip = builder.repo.references[f"refs/heads/variant/{instance}"].peel(pygit2.Commit)
    return bytes(builder.repo[tip.tree[path].id].data)


def test_derived_tree_matches_expected_bytes(runner: CliRunner, fixture: VariantRepo) -> None:
    result = runner.invoke(app, ["checkout", "Minimal", "--no-switch"])
    assert result.exit_code == 0, result.output
    assert _variant_blob(fixture.builder, "Minimal", "shared.py") == BASE.encode()

    result = runner.invoke(app, ["checkout", "AuthOnly", "--no-switch"])
    assert result.exit_code == 0, result.output
    assert _variant_blob(fixture.builder, "AuthOnly", "shared.py") == WITH_AUTH.encode()


def test_unaffected_blobs_share_oids_with_base(runner: CliRunner, fixture: VariantRepo) -> None:
    assert runner.invoke(app, ["checkout", "Minimal", "--no-switch"]).exit_code == 0
    repo = fixture.builder.repo
    variant_tip = repo.references["refs/heads/variant/Minimal"].peel(pygit2.Commit)
    head = repo.head.peel(pygit2.Commit)
    assert variant_tip.tree["model.cfr"].id == head.tree["model.cfr"].id
    assert variant_tip.tree["shared.py"].id != head.tree["shared.py"].id


def test_manifest_is_persisted(runner: CliRunner, fixture: VariantRepo) -> None:
    assert runner.invoke(app, ["checkout", "Minimal", "--no-switch"]).exit_code == 0
    manifest = GitRefStore(fixture.builder.repo).read_manifest("Minimal")
    assert manifest is not None
    assert manifest.base_commit == fixture.ui_sha
    assert manifest.assignment["auth"] is False


def test_default_switches_to_the_variant_branch(runner: CliRunner, fixture: VariantRepo) -> None:
    result = runner.invoke(app, ["checkout", "Minimal"])
    assert result.exit_code == 0, result.output
    assert "switched to variant/Minimal" in result.output
    assert fixture.builder.repo.head.shorthand == "variant/Minimal"
    assert (fixture.builder.path / "shared.py").read_text() == BASE


def test_existing_variant_requires_refresh(runner: CliRunner, fixture: VariantRepo) -> None:
    assert runner.invoke(app, ["checkout", "Minimal", "--no-switch"]).exit_code == 0
    fixture.builder.commit("advance", files={"other.txt": "x\n"})
    result = runner.invoke(app, ["checkout", "Minimal", "--no-switch"])
    assert result.exit_code == 1
    assert "--refresh" in result.output


def test_refresh_chains_onto_previous_variant_commit(
    runner: CliRunner, fixture: VariantRepo
) -> None:
    assert runner.invoke(app, ["checkout", "Minimal", "--no-switch"]).exit_code == 0
    first_tip = read_ref(fixture.builder.repo, "refs/heads/variant/Minimal")
    fixture.builder.commit("advance", files={"other.txt": "x\n"})
    result = runner.invoke(app, ["checkout", "Minimal", "--no-switch", "--refresh"])
    assert result.exit_code == 0, result.output
    repo = fixture.builder.repo
    tip = repo.references["refs/heads/variant/Minimal"].peel(pygit2.Commit)
    assert [str(p.id) for p in tip.parents] == [first_tip]
    assert "other.txt" in tip.tree  # rebuilt from the new base


def test_rederiving_at_same_base_is_a_noop(runner: CliRunner, fixture: VariantRepo) -> None:
    assert runner.invoke(app, ["checkout", "Minimal", "--no-switch"]).exit_code == 0
    result = runner.invoke(app, ["checkout", "Minimal", "--no-switch"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output
    repo = fixture.builder.repo
    tip = repo.references["refs/heads/variant/Minimal"].peel(pygit2.Commit)
    assert tip.parents == []  # still the single original variant commit


def test_misresolution_is_caught_by_verify_and_blocks_the_ref(
    runner: CliRunner,
    fixture: VariantRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RegionResolver.resolve

    def misresolved(self: RegionResolver, anchor: object, target: object) -> Resolution:
        resolution = original(self, anchor, target)  # type: ignore[arg-type]
        if resolution.span is None:
            return resolution
        # simulate a bad fuzzy match: the region is "found" at the top of the file
        return Resolution((1, resolution.span[1]), "fuzzy")

    monkeypatch.setattr(pipeline_module.RegionResolver, "resolve", misresolved)
    result = runner.invoke(app, ["checkout", "Minimal", "--no-switch"])
    assert result.exit_code == 1, result.output
    assert "verification failed" in result.output
    assert read_ref(fixture.builder.repo, "refs/heads/variant/Minimal") is None


def test_verify_only_passes_then_catches_tampering(runner: CliRunner, fixture: VariantRepo) -> None:
    assert runner.invoke(app, ["checkout", "Minimal", "--no-switch"]).exit_code == 0
    result = runner.invoke(app, ["checkout", "Minimal", "--verify-only"])
    assert result.exit_code == 0, result.output
    assert "verified ok" in result.output

    # tamper: put the removed ui/auth content back on the variant branch
    repo = fixture.builder.repo
    tip = read_ref(repo, "refs/heads/variant/Minimal")
    assert tip is not None
    tree = rewrite_tree(repo, tip, {"shared.py": WITH_BOTH.encode()})
    sha = create_commit(repo, tree, "tamper", [tip])
    write_ref(repo, "refs/heads/variant/Minimal", sha)

    result = runner.invoke(app, ["checkout", "Minimal", "--verify-only"])
    assert result.exit_code == 1
    assert "still present" in result.output


def test_verify_only_without_a_variant_fails(runner: CliRunner, fixture: VariantRepo) -> None:
    result = runner.invoke(app, ["checkout", "Minimal", "--verify-only"])
    assert result.exit_code == 1
    assert "never been derived" in result.output


def test_scattered_kept_region_does_not_false_overlap(
    runner: CliRunner, fixture: VariantRepo
) -> None:
    # a kept region whose lines are interleaved with a removed region must not
    # be treated as one big span covering the removed lines
    original = "def top():\n    return 1\n\ndef bottom():\n    return 2\n"
    with_auth_inside = (
        "def top():\n    return 1\n\ndef auth():\n    return check()\n\ndef bottom():\n"
        "    return 2\n"
    )
    core_sha = fixture.builder.commit("core pair", files={"core2.py": original})
    auth_sha = fixture.builder.commit("auth inserted", files={"core2.py": with_auth_inside})
    assert runner.invoke(app, ["annotate", core_sha, "--feature", "core"]).exit_code == 0
    assert runner.invoke(app, ["annotate", auth_sha, "--feature", "auth"]).exit_code == 0

    result = runner.invoke(app, ["checkout", "Minimal", "--no-switch"])
    assert result.exit_code == 0, result.output
    assert _variant_blob(fixture.builder, "Minimal", "core2.py") == original.encode()
