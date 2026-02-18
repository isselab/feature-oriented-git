from pathlib import Path

from git_tool import finding_features

TESTSTRING = """
    Hier ist etwas Code &begin[FEATURE1]
    Code für FEATURE1
    weiterer Code für FEATURE1
    &end[FEATURE1]
    &begin[FEATURE2]
    Code für FEATURE2
    &end[FEATURE2]
    """


def test_extract_features():
    features = finding_features.extract_features_from_annotation(TESTSTRING)
    feature_names = list(map(lambda x: x.name, features))
    assert feature_names == ["FEATURE1", "FEATURE2"]


def test_git_features(git_repo):
    # Dateipfad im Repository
    repo_path = Path(git_repo.working_tree_dir)
    file_path = repo_path / "test.py"
    file_path.write_text("# Initial commit\n")
    git_repo.index.add([str(file_path)])
    git_repo.index.commit("Initial commit")

    # Schreibe in die Datei mit Feature Annotationen
    file_path.write_text(
        file_path.read_text()
        + "# &begin[Feature1]\n"
        + "print('Hello, Feature1!')\n"
        + "# &end[Feature1]\n"
    )
    head_commit = git_repo.head.commit
    diff = head_commit.diff(None, create_patch=True)
    assert len(diff) == 1, "Exactly one diff should be created here"
    mapped_to_feature = [
        (finding_features.get_features_for_diff(d), d.a_path) for d in diff
    ]
    found_features = mapped_to_feature[0][0]
    assert len(found_features) == 1, (
        "Expecting one Feature that is not committed"
    )
    assert found_features[0].name == "Feature1", (
        "Expecting to find the correct name for feature"
    )
