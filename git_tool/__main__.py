import typer

from git_tool.ci.subcommands.feature_add import feature_add_by_add
from git_tool.ci.subcommands.feature_add_from_staged import features_from_staging_area
from git_tool.ci.subcommands.feature_blame import feature_blame
from git_tool.ci.subcommands.feature_commit import feature_commit
from git_tool.ci.subcommands.feature_commit_msg import feature_commit_msg
from git_tool.ci.subcommands.feature_commits import app as feature_commits
from git_tool.ci.subcommands.feature_info import inspect_feature
from git_tool.ci.subcommands.feature_info_all import all_feature_info
from git_tool.ci.subcommands.feature_pre_commit import feature_pre_commit
from git_tool.ci.subcommands.feature_status import feature_status


app = typer.Typer(name="feature", no_args_is_help=True)   # "git feature --help" does not work, but "git-feature --help" does
app.command(name="add", help="Stage files and associate them with the provided features.")(feature_add_by_add)
app.command(name="add-from-staged", help="Associate staged files with features.")(features_from_staging_area)
app.command(name="blame", help="Display features associated with file lines.")(feature_blame)
app.command(name="commit", help="Associate an existing commit with one or more features.")(feature_commit)
app.command(name="commit-msg", help="Generate feature information for the commit message.")(feature_commit_msg)
app.add_typer(feature_commits, name="commits", help="Use with the subcommand 'list' or 'missing' to show commits with or without associated features.")
app.command(name="info", help="Show information of a specific feature.")(inspect_feature)
app.command(name="info-all", help="List all available features in the project.")(all_feature_info)
app.command(name="pre-commit", help="Check if all staged changes are properly associated with features.")(feature_pre_commit)
app.command(name="status", help="Display unstaged and staged changes with associated features.")(feature_status)


app()
