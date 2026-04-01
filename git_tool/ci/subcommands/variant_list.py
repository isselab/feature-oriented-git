from git_tool.feature_data.models_and_context.repo_context import repo_context


def list_variant():
    """List all the variants present in the repo"""

    with repo_context() as repo:
        for ref in repo.refs:
            if ref.path.startswith("refs/heads/variant/"):
                variant = ref.path.replace("refs/heads/variant/", "")
                print(variant)
