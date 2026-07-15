"""Chained git hook installation: a dispatcher per hook plus a hook.d directory."""

import shlex
import shutil
from pathlib import Path

import pygit2

HOOK_NAMES = ("post-commit", "post-rewrite")
_DISPATCHER_MARKER = "# git-feature chained hook dispatcher"
_HOOK_SCRIPT_MARKER = "# installed by git-feature"

_DISPATCHER = f"""#!/bin/sh
{_DISPATCHER_MARKER}
# Runs every executable in <hook-name>.d/, feeding each the hook's stdin.
hook_name=$(basename "$0")
hook_dir="$(dirname "$0")/$hook_name.d"
[ -d "$hook_dir" ] || exit 0
stdin_file=$(mktemp)
trap 'rm -f "$stdin_file"' EXIT
if [ ! -t 0 ]; then cat >"$stdin_file"; fi
status=0
for hook in "$hook_dir"/*; do
    [ -x "$hook" ] || continue
    "$hook" "$@" <"$stdin_file" || status=$?
done
exit $status
"""

_HOOK_SCRIPT = f"""#!/bin/sh
{_HOOK_SCRIPT_MARKER}; safe to delete, reinstalled by 'git feature init'.
# The absolute path is baked in so an unrelated 'git-feature' on PATH is never run.
GIT_FEATURE_BIN={{binary}}
[ -x "$GIT_FEATURE_BIN" ] || GIT_FEATURE_BIN=git-feature
command -v "$GIT_FEATURE_BIN" >/dev/null 2>&1 || exit 0
"$GIT_FEATURE_BIN" hook-run {{name}} || echo "git-feature: {{name}} hook failed (ignored)" >&2
exit 0
"""


def hooks_dir(repo: pygit2.Repository) -> Path:
    """Return the repository's hooks directory."""
    return Path(repo.path) / "hooks"


def install_hooks(repo: pygit2.Repository) -> list[str]:
    """Install chained dispatchers + our hook scripts; returns the actions taken."""
    actions = []
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    for name in HOOK_NAMES:
        hook_path = directory / name
        chain_dir = directory / f"{name}.d"
        chain_dir.mkdir(exist_ok=True)
        if hook_path.exists() and _DISPATCHER_MARKER not in hook_path.read_text():
            preserved = chain_dir / "00-preexisting"
            hook_path.rename(preserved)
            preserved.chmod(0o755)
            actions.append(f"preserved existing {name} hook as {name}.d/00-preexisting")
        if not hook_path.exists():
            hook_path.write_text(_DISPATCHER)
            hook_path.chmod(0o755)
            actions.append(f"installed {name} dispatcher")
        our_hook = chain_dir / "50-git-feature"
        script = _HOOK_SCRIPT.format(name=name, binary=shlex.quote(_own_binary()))
        if not our_hook.exists() or our_hook.read_text() != script:
            our_hook.write_text(script)
            our_hook.chmod(0o755)
            actions.append(f"installed {name}.d/50-git-feature")
    return actions


def _own_binary() -> str:
    """The git-feature executable installing the hooks (PATH lookup as fallback)."""
    return shutil.which("git-feature") or "git-feature"


def hooks_installed(repo: pygit2.Repository) -> dict[str, bool]:
    """Report per hook name whether the dispatcher and our chained script are in place."""
    directory = hooks_dir(repo)
    status = {}
    for name in HOOK_NAMES:
        hook_path = directory / name
        our_hook = directory / f"{name}.d" / "50-git-feature"
        status[name] = (
            hook_path.is_file()
            and _DISPATCHER_MARKER in hook_path.read_text()
            and our_hook.is_file()
        )
    return status
