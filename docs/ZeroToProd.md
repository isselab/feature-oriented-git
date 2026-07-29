# Git with Feature

The general idea: attach additional metadata to a git commit of which lines
of code belong to which feature in a way that survives rebases, amends, and
cherry-picks, without ever touching the user's actual commits. On top of that,
use the metadata to derive product variants (a build containing only a chosen
subset of features) directly from history.

# Git concepts needed for the project

## Extending git with git-command binaries

`git` is a dispatcher. When you run `git foo args...`, git checks its table of
built-in subcommands (`commit`, `diff`, `rebase`, ...); if `foo` isn't one of
them, it searches `PATH` for an executable literally named `git-foo` and
execs it, forwarding the remaining arguments and environment. This is how
third-party tooling (`git-lfs`, `git-flow`, and this project) gets `git`-native
UX without patching git itself. `git foo` and `git-foo` are the same call.

This project's entry point is declared in `pyproject.toml`:

```toml
[project.scripts]
git-feature = "git_feature.cli:app"
```

`uv sync` / `pip install` turns that into a real `git-feature` executable
(installed via `pipx install git-feature` or `uv tool install git-feature`
for end users). Once `git-feature` is anywhere on `PATH`, both of these are
identical:

```sh
git-feature list
git feature list      # git found git-feature on PATH and executed it
```

During development there's no installed package on `PATH`, so either run
through `uv` directly or put the dev build there yourself:

```sh
uv run git-feature --help
export PATH="$(pwd)/.venv/bin:$PATH"   # now `git feature …` works too
```

Inside the binary, `git_feature/cli.py` is a `typer` app; each `git feature
<sub>` maps to one `@app.command()` that thin-wraps a module in `commands/`:

```python
# git_feature/cli.py
app = typer.Typer(name="git-feature", no_args_is_help=True)

@app.command()
def init(ctx: typer.Context, backfill: bool = False, hooks: bool = True) -> None:
    """Initialize the feature store, hooks, and a starter model.cfr."""
    init_cmd.run(ctx, backfill=backfill, hooks=hooks)
```

One command is deliberately `hidden=True` as it is not meant for users, only
for the git hooks installed below, which invoke the very same binary as a
private subcommand rather than shelling out to anything else:

```python
@app.command(name="hook-run", hidden=True)
def hook_run(ctx: typer.Context, hook: Annotated[HookName, typer.Argument()]) -> None:
    """Internal: entry point invoked by the installed git hooks."""
    hook_run_cmd.run(ctx, hook=hook.value)
```

(See the [Git hooks](#git-hooks) section. The installed hook scripts run
`git-feature hook-run post-commit`, exercising this exact mechanism.)

## Git object storage

Everything git tracks, meaning file contents, directory listings, and
commits, is stored as one of a handful of object types in `.git/objects`,
addressed by the SHA hash of their own content. Objects are immutable:
change one byte and you get a new object at a new address; nothing is ever
edited in place.

- **blob**: raw file contents, no filename, no metadata attached to it.
- **tree**: a directory listing: a sorted list of `(mode, name, oid)`
  entries, each pointing at a blob (a file) or another tree (a subdirectory).
- **commit**: a pointer to one tree (the full snapshot at that point) plus
  parent commit(s), author/committer, and a message.

You can inspect any object with the plumbing command `git cat-file -p
<oid>` (`-t` prints just its type):

```sh
git cat-file -t HEAD                # -> commit
git cat-file -p HEAD                # tree <oid>, parent <oid>, author, message
git cat-file -p HEAD^{tree}          # the root tree: mode/type/oid/name per entry
git ls-tree -r HEAD                  # same info, recursively, one line per blob
```

This project builds its entire metadata store this way through
`pygit2` (the libgit2 binding), never through the working directory or index.
`git_feature/store/gitref.py` writes the store's tree from a flat
`path → bytes` mapping, bottom-up, exactly like the object model above:

```python
def _build_tree(repo: pygit2.Repository, files: dict[str, bytes]) -> pygit2.Oid:
    builder = repo.TreeBuilder()
    subdirs: dict[str, dict[str, bytes]] = {}
    for path, data in files.items():
        if "/" in path:
            head, rest = path.split("/", 1)
            subdirs.setdefault(head, {})[rest] = data
        else:
            builder.insert(path, repo.create_blob(data), pygit2.enums.FileMode.BLOB)
    for name, sub in sorted(subdirs.items()):
        builder.insert(name, _build_tree(repo, sub), pygit2.enums.FileMode.TREE)
    return builder.write()
```

`repo.create_blob(data)` writes a blob object and returns its oid;
`TreeBuilder.insert` adds an entry for a blob or a nested tree; `.write()`
writes the tree object. The commit is created the same deliberate way.
Notice the first argument to `create_commit` is `None`: this writes a commit
*object* without moving any ref, so the caller decides separately, and
atomically, when (and whether) to point a reference at it:

```python
new_oid = self._repo.create_commit(None, sig, sig, message, tree_oid, parents)
compare_and_swap_ref(self._repo, self._ref_name, str(new_oid), expected_old=self._base_sha)
```

The upshot: the feature store (`refs/feature/store`, see next section) is a
normal, inspectable commit history that you can run the same plumbing commands
against it that you'd run against any branch:

```sh
git cat-file -p refs/feature/store              # tree + parent + message
git ls-tree -r --name-only refs/feature/store    # meta.json, features/auth.json, ...
git cat-file -p refs/feature/store:meta.json     # the JSON blob's raw content
git log refs/feature/store --oneline             # the store's own audit history
```

Content-addressing also means unrelated writes share storage for free:
`materialize.py`'s tree rewriting (building a variant with some regions
removed) reuses the *same blob oid* for every file it doesn't touch. No
copy, no duplication, git's usual deduplication just applies.

## Git references

A **reference** ("ref") is nothing but a name pointing at an object id,
typically a commit. Concretely it's either a small file under `.git/refs/...`
containing the target oid (or another ref, for symbolic refs like `HEAD`), or
a line in `.git/packed-refs` once git compacts them. That's the whole
mechanism: `refs/heads/main` *is* your `main` branch; there is no other branch
object. Deleting the ref deletes the branch; nothing under it is touched.

```sh
cat .git/refs/heads/main          # a single line: the commit oid
git symbolic-ref HEAD             # -> refs/heads/main
git for-each-ref                  # every ref, its oid, and its type
git update-ref -d refs/heads/foo  # delete a branch by deleting its ref, no different from git branch -d
```

Git only treats a few namespaces specially by convention:
`refs/heads/*` (local branches), `refs/tags/*`, `refs/remotes/<r>/*`
(remote-tracking branches). Nothing stops you from inventing your own
namespace. Most git commands that iterate refs either don't look outside the
conventional ones, or need to be told explicitly to. That's exactly what this
project does: `refs/feature/store` holds the entire metadata history, but it
never shows up in `git branch`, is never checked out, and is invisible unless
you ask for it by name.

`git_feature/gitio/refio.py` wraps the two operations everything else needs:

```python
def read_ref(repo: pygit2.Repository, name: str) -> str | None:
    ref = repo.references.get(name)
    return None if ref is None else str(ref.peel(pygit2.Commit).id)

def compare_and_swap_ref(repo, name, target, expected_old) -> None:
    """Update a ref only if it currently points at `expected_old`."""
    current = read_ref(repo, name)
    if current != expected_old:
        raise RefUpdateConflict(f"{name}: expected {expected_old}, found {current}")
    ...
```

`compare_and_swap_ref` is the same idea as `git push --force-with-lease`: read
the current target, only move the ref if it's still what you last saw. Every
write to the store (or a variant branch) goes through this, so two processes
racing to update the same ref fail loudly instead of silently clobbering each
other. The caller (e.g. `store fetch`, see below) decides how to recover.

**Custom refs must be synced manually.** The default fetch/push refspec
(`+refs/heads/*:refs/remotes/origin/*`) only mirrors branches, so
`refs/feature/store` is invisible to a plain `git push` / `git fetch` unless
something tells git about it explicitly. This project does that in two ways:

1. `git feature store push` / `store fetch` move the ref by name directly, via
   the same push/fetch APIs git itself uses:

   ```python
   # git_feature/commands/store.py
   remote.push([f"{STORE_REF}:{STORE_REF}"], callbacks=status)
   ...
   remote.fetch([f"+{STORE_REF}:{incoming_ref(remote_name)}"])
   ```

   Fetch lands the remote's copy on a side ref
   (`refs/feature/incoming/<remote>`) rather than overwriting the local store
   outright, so a diverged store can be three-way merged before anything is
   swapped in (`store/merge.py`). The fetch side only ever fast-forwards or
   merges the *local* `refs/feature/store` after that's decided.

2. `init` additionally registers a standing fetch refspec on the remote
   config, so a plain `git fetch` also keeps a local mirror of the remote's
   store current, the same way `refs/remotes/origin/*` stays current:

   ```python
   # git_feature/commands/init.py
   refspec = f"+{STORE_REF}:{incoming_ref(remote.name)}"
   repo.remotes.add_fetch(remote.name, refspec)
   ```

Because it's just a ref, walking away from the tool is just deleting one:
`git update-ref -d refs/feature/store` plus removing the hook files below
leaves zero trace in the actual commit history.

## Git hooks

Hooks are scripts git invokes at specific points in its own workflow, such as
before or after a commit, rebase, push, or merge. They live as plain
executable files under `.git/hooks/<hook-name>` (no extension, no
registration; git just checks whether the file exists and is executable,
then runs it with hook-specific arguments/stdin). Nothing about hooks is
versioned or cloned: `.git/hooks` is local per-clone state, so a fresh `git
clone` or a teammate's machine starts with none of your hooks installed.

That local-only nature is a real design constraint here, not a footnote: it's
exactly why this project can't rely on hooks alone to track identity, and
needs `git feature reconcile` as a fallback for commits hooks never saw
(imported patches, cherry-picks made on another clone, or a repo where hooks
were never installed).

Two hooks are used:

- **`post-commit`**: fires after a commit object is created and `HEAD` moves.
  No arguments; you inspect the new commit via `HEAD` yourself. Used here to
  mint a change-id for the commit that was just made.
- **`post-rewrite`**: fires after a command that replaces commits with new
  ones (`commit --amend`, `rebase`; notably *not* `reset`). Git feeds it
  `<old-sha> <new-sha>` pairs, one per line, on **stdin**. Used here to carry
  a commit's change-id forward from its old sha to its new one, so metadata
  keyed by change-id survives the rewrite untouched.

```python
# git_feature/commands/hook_run.py
def _post_commit(repo, store, cid_map) -> None:
    sha = str(repo.head.target)
    _, minted = cid_map.get_or_mint(sha, patch_id=patch_id(repo, sha))
    if minted:
        store.commit(f"mint change-id for {sha[:12]}")

def _post_rewrite(repo, store, cid_map) -> None:
    migrated = 0
    for line in sys.stdin:          # git writes "<old-sha> <new-sha>\n" per rewritten commit
        old_sha, new_sha = line.split()[:2]
        if cid_map.migrate(old_sha, new_sha, patch_id=patch_id(repo, new_sha)):
            migrated += 1
    if migrated:
        store.commit(f"migrate {migrated} change-ids after rewrite")
```

You can trigger `post-rewrite` by hand to see the contract for yourself:

```sh
printf 'old-sha new-sha\n' | .git/hooks/post-rewrite amend
```

**Installation doesn't clobber.** A repo might already have its own
`post-commit` hook (from another tool, or the team's own convention), so
naively overwriting `.git/hooks/post-commit` would silently destroy it. This
project installs a small **chained dispatcher** as the actual hook file
instead: it runs every executable in a companion `post-commit.d/` directory,
in order, feeding each the same stdin the real hook received. Any hook that
existed before `git feature init` is preserved as `post-commit.d/00-preexisting`
so it still runs; this project's own logic lives alongside it as
`post-commit.d/50-git-feature`:

```python
# git_feature/gitio/hooks.py
_DISPATCHER = """#!/bin/sh
# Runs every executable in <hook-name>.d/, feeding each the hook's stdin.
hook_name=$(basename "$0")
hook_dir="$(dirname "$0")/$hook_name.d"
...
for hook in "$hook_dir"/*; do
    [ -x "$hook" ] || continue
    "$hook" "$@" <"$stdin_file" || status=$?
done
exit $status
"""
```

`post-commit.d/50-git-feature` itself is a tiny shim that calls back into the
same `git-feature` binary from the [git-command binaries](#extending-git-with-git-command-binaries)
section, with the binary's absolute path baked in so an unrelated
`git-feature` elsewhere on `PATH` can never be invoked by mistake:

```sh
"$GIT_FEATURE_BIN" hook-run post-commit || echo "git-feature: post-commit hook failed (ignored)" >&2
```

That final `|| echo ... (ignored)` matters too: hooks must never block the
user's actual `git commit`/`git rebase`. `hook_run.py`'s `run()` wraps
everything in a catch-all and reports failures to stderr rather than raising.
Losing the mint/migrate step is recoverable (`reconcile`); breaking someone's
commit is not.

You can check what's currently installed at any time:

```sh
cat .git/hooks/post-commit           # the dispatcher
ls .git/hooks/post-commit.d/         # 00-preexisting (if any), 50-git-feature
git feature doctor                   # reports whether both hooks are installed and chained
```

# Feature modeling and variant derivation

Everything above is about storing and preserving metadata. This section is
about what that metadata is *for*: describing which features exist and what
combinations of them are legal (the model), tying code to those features (the
annotation), and turning a chosen combination into an actual reduced codebase
(derivation).

## The feature model: a Clafer subset

[Clafer](https://www.clafer.org/) is a modeling language purpose-built for
describing product-line feature models: a tree of features, cardinalities
saying how many of a group can be active together, boolean constraints
between features, and named configurations. Full Clafer is much bigger than
that (references, arithmetic, quantifiers, structural joins). This project
only ever needed the feature-modeling core, so `model.cfr`'s grammar
(`git_feature/domain/variability/clafer.lark`) is a deliberately small
subset, and says so up front:

```
// Clafer feature-modeling subset: feature tree, cardinalities, group
// cardinalities, abstract models + instances, boolean constraints.
// Anything beyond this (enums, references, arithmetic, quantifiers, joins)
// is deliberately not in the grammar and fails to parse.
```

That restraint is the point: a smaller grammar is easier to keep correct and
port later, and nothing beyond "which features exist, how they relate, which
combinations are valid" is needed to annotate code and derive variants.

A `model.cfr` has two kinds of top-level declarations. First, **clafers**,
the feature tree itself, usually rooted in one `abstract` block:

```
abstract Demo {
    core
    auth ?
}
```

Each child has a **cardinality**: no marker means mandatory (must be on
whenever its parent is), `?` means optional (0 or 1), `+` means one-or-more,
`*` zero-or-more, and a **group cardinality** keyword placed before a set of
children (`xor`, `or`, `mux`, `opt`, or an explicit `m..n` range) constrains
how many of *those* children can be active together. For example, an `xor`
group means exactly one child may be selected.

Second, **instances**: named, concrete configurations of an abstract tree,
with `[ ... ]` constraints selecting or excluding specific features. These
*are* the variant specifications the derivation pipeline reads by name:

```
Minimal : Demo {
    [ no auth ]
}

Full : Demo {
    [ auth ]
}
```

Constraint expressions support `!`/`no`/`not`, `&&`, `||`, `=>`, `<=>`, and
the `xor` keyword between two expressions. Because a model can leave some
features undetermined until constraints are propagated, resolution is
**three-valued** (`True | False | None`) rather than plain boolean.
`git_feature/domain/variability/evaluator.py` propagates mandatory children,
group-cardinality bounds, and every constraint to a fixed point, and only
then collapses whatever is still unknown to excluded. Anything that can't be
made consistent (a violated constraint, a feature required both on and off,
a broken group cardinality) is rejected with the specific reason, never
silently guessed:

```sh
git feature model validate            # model well-formed? annotations reference real features?
git feature model validate Minimal
```

```text
instance Minimal: legal configuration
  included: core
  excluded: auth
```

## Presence conditions and region anchors

A **presence condition** is the boolean expression attached to an annotated
region, e.g. `auth`, or `payments & premium`. It reuses feature names from
`model.cfr`, but is parsed by a smaller, separate grammar
(`domain/variability/presence.py`): just `name`, `!`, `&`/`&&`, `|`/`||`, and
parentheses. No `=>`/`<=>`/`xor`. A presence condition only ever needs to say
"on/off combinations", never the structural relationships a model expresses,
so the smaller language is a deliberate match to the smaller job.

Presence conditions are attached to **regions**, not line numbers. A region
is a hunk *anchored to the immutable diff of the change that introduced it*.
The actual persisted record (captured by running `git feature annotate` on a
real commit) looks like this:

```json
{
  "anchor": {
    "change_id": "01KY1TCY6275J5K9Q03H7P8EGS",
    "path": "app.py",
    "old_span": [0, 0],
    "new_span": [1, 2],
    "fingerprint": "7fa8eae0365e947e"
  },
  "presence": "core",
  "author": "Tester",
  "ts": "2026-07-21T07:49:13.026296Z",
  "note": null
}
```

The anchor's `change_id` is exactly the stable identity from the identity
layer (survives rebase/amend, see the git-hooks section above); `old_span`/
`new_span` are the hunk's position *in that one historical diff*; `fingerprint`
is a whitespace-insensitive hash of the added lines. None of that ever needs
updating: it describes a historical fact, and history doesn't change.

"Where does this region live *right now*?" is answered on demand by
`RegionResolver` (`git_feature/identity/region.py`), in tiers, and it always
reports a confidence rather than guessing silently:

```python
def resolve(self, anchor: RegionAnchor, target) -> Resolution:
    return (
        self._blame_forward(anchor, commit)      # exact | moved
        or self._fingerprint_search(anchor, commit)  # fuzzy
        or Resolution(None, "lost")
    )
```

1. **Blame-forward**: blame the target file, translate each line's
   originating commit to a change-id, and take the lines whose change-id
   matches the anchor. If the exact fingerprinted window is found among
   them, confidence is `exact`; if the change's lines are present but
   shuffled/partial, `moved`.
2. **Fingerprint / similarity search**: if blame finds nothing (heavy
   rename, squash, reformat), search file contents for a window matching the
   anchor's normalized fingerprint, falling back to best-effort text
   similarity. Confidence `fuzzy`.
3. Otherwise: `lost`.

Every consumer (queries, derivation) surfaces this confidence instead of
hiding it. `git feature blame` is the direct view of the resolver's answer,
line by line:

```sh
git feature blame app.py
```

```text
   1  core  def hello():
   2  core      print("hi")
   3  auth  
   4  auth  def auth():
   5  auth      return "token"
```

## Variant derivation

A **variant** is "this codebase, minus every region whose presence condition
evaluates to false under a chosen configuration": a disposable, derived
branch (`refs/heads/variant/<name>`), never the codebase's real branches.
Derivation is a pipeline of four stages (`domain/derivation/pipeline.py` +
`materialize.py`), each with a checkable contract; `--dry-run` runs the first
two and just prints the report.

**1. Configure**: resolve the requested instance against `model.cfr` **read
from the base commit's tree**, not the working directory, so deriving from an
old commit uses the model as it was back then:

```python
def configure(repo, instance: str, base_rev: str) -> tuple[dict[str, bool], str]:
    base_sha = str(resolve_commit(repo, base_rev).id)
    text = model_text(repo, base_sha)          # model.cfr from that commit's tree
    module = parse_model(text)
    assignment = Evaluator(module).resolve_assignment(instance)
    return assignment, base_sha
```

Output: a total `feature → bool` assignment. An illegal instance is rejected
here, before anything else is touched.

**2. Project**: for every stored annotation whose change is part of the base
commit's history, evaluate its presence condition under the assignment to get
included/excluded, and resolve the region against the base commit with
`RegionResolver`. Then run consistency checks that turn contradictions into
named `Conflict`s instead of resolving them silently: **overlap** (an
included and an excluded region cover the same lines), **dangling
dependency** (an included region sits inside a region that's about to be
removed), **lost region** (a region that must be removed can't be located,
confidence `lost`). `--dry-run` stops here:

```sh
git feature checkout Minimal --dry-run
```

```text
variant Minimal from 0df2ee6707e6 (dry run)
disabled features: auth
would remove:
  app.py: lines 3-5  [auth] (exact)
kept regions: 1
no conflicts
```

**3. Materialize**: build the reduced tree *in memory*: for every file with
removed regions, splice the disabled line runs out byte-exact
(`materialize.splice_out`); every untouched file keeps its original blob oid
(shared, not copied: the object-storage dedup from earlier applies for
free). Commit the result onto `refs/heads/variant/<name>`.

**4. Verify**: before the branch ref is allowed to move, re-check the
*derived tree by content*: recover each region's original salient lines (from
the frozen diff, not from trusting the resolver) and confirm a kept region's
content survived and a removed region's content is actually gone. A mismatch
aborts, and the ref never moves, so a bad derivation never becomes visible:

```sh
git feature checkout Minimal
```

```text
variant Minimal: refs/heads/variant/Minimal -> 50b3c06f3faa (1 region(s) removed, verified)
switched to variant/Minimal
```

```sh
cat app.py   # the auth block is simply gone, no markers, valid code
```

## Round-trip editing: `view` and `putback`

A plain `checkout` variant is meant to be *read*, not committed to. It's a
disposable projection, and commits made on it would be stranded the moment
the variant is rebuilt. `view` is the editable counterpart: the exact same
derivation pipeline, plus a recorded session that `putback` later uses to map
edits back to where they really belong on the source branch.

```sh
git feature view Minimal
```

```text
view of Minimal: editing 7e723e87f0de (from auth-work @ 43478d8d3392) — put edits back with 'git feature putback'
switched to variant/Minimal
```

`view.py` runs `configure` → `project` → `materialize_variant`, stages 1-4
from the pipeline above, unchanged, and then persists one extra record, a
`ViewSession`, to the store:

```python
class ViewSession(BaseModel):
    instance: str
    source_branch: str      # putback's target
    base_commit: str        # source commit the view was derived from
    variant_commit: str     # the materialized variant tree
    manifest: DerivationManifest   # exactly what checkout would have produced
    created_at: datetime
```

The manifest is the part that matters: it already records, per file, which
1-based line runs of the *source* were removed to produce the *view*. That's
enough information to translate a position in one file into a position in
the other, in both directions: the same relationship a lens's `get`/`put`
maintain between a whole structure and a projected view of it.

**Editing the view** works like editing any checked-out branch: the reduced
file is just sitting in the working tree:

```sh
cat -n app.py
```

```text
1  def hello():
2      print("hi")
3
4  def goodbye():
5      print("bye")
```

(The `auth` block that was on lines 3-5 of the *source* is gone; what was
source line 8 is now view line 5.) Edit it as if the hidden feature didn't
exist:

```sh
sed -i 's/print("bye")/print("bye for now")/' app.py
git feature putback --dry-run
```

```text
would apply to auth-work @ 43478d8d3392:
  app.py: view lines 5 -> source lines 8
```

That `5 -> 8` is the whole point of `putback`. `domain/derivation/putback.py`
diffs the working tree against the unedited `variant_commit` to get the
edit's hunks in *view* coordinates, then remaps each hunk through the
manifest's removed runs:

```python
# kept[k-1] = the base (source) line number that appears as view line k
removed: set[int] = set()
for start, count in runs:
    removed.update(range(start, start + count))
kept = [number for number in range(1, len(base_lines) + 1) if number not in removed]
...
positions = kept[old_start - 1 : old_start - 1 + old_count]
```

`kept` is the view-to-source line mapping implied by the manifest. Build it
once per file, then every hunk's view-space span is just an index into it.
An edit below a 3-line removed block lands 3 lines lower in the source, which
is exactly what happened above (view line 5 → source line 8). If the source
and view positions happen to coincide (an edit above every removed region,
or a variant with nothing removed from that file), the mapping is a no-op.

Applying it plays out as a normal commit on the *source* branch: the full,
unreduced tree, with the mapped edit spliced in:

```sh
git feature putback -m "friendlier goodbye"
```

```text
auth-work -> a836107bf02c (1 file(s) transplanted)
view of Minimal refreshed onto the new source commit
```

```sh
git show auth-work:app.py
```

```text
def hello():
    print("hi")

def auth():
    return "token"

def goodbye():
    print("bye for now")
```

The `auth` block, never visible in the view, is untouched, and the edit
landed in the right place in the full file. Mechanically: `rewrite_tree`
splices the mapped replacement into the *base* commit's tree (not the
view's), a normal commit is created on `source_ref` with `compare_and_swap_ref`
guarding the move, and the new commit is minted a change-id immediately.
From here on it's an ordinary commit, annotatable like any other. `putback`
then re-runs the same three pipeline stages on top of that new commit and
rewrites the `ViewSession` in place (`_refresh_view`), so the view stays open
against the branch's new tip and the edit/putback loop can repeat.

**Refusing instead of guessing.** Several situations abort the whole putback
with nothing written, rather than applying a partial or wrong result:

- an edit whose hunk doesn't fit inside one contiguous run of `kept` lines,
  meaning it **crosses a removed region**, is rejected as a `removed-region`
  conflict (there's no single source position that edit could map to);
- the changed file wasn't a plain edit (`status != "M"`, e.g. deletion,
  binary, mode change): `unsupported-change`;
- the **source branch moved** since the view was opened (`source_tip !=
  session.base_commit`): putback would otherwise silently discard whatever
  happened on the source branch meanwhile, so it asks for `git feature view
  <instance>` to be re-opened instead;
- putback is attempted from **anywhere other than an open view's branch**, or
  the view's session and the branch's actual tip have drifted apart.

`--dry-run` always reports the mapped plan (or the conflicts) without
touching anything, exactly like `checkout --dry-run` does for the derivation
itself.

## Beyond this document

`git feature sync` builds on the same identity layer covered earlier: it can
"propagate a feature's missing commits from one branch to another,
recognizing what's already present by change-id rather than SHA," but
doesn't touch the model/derivation machinery from this section. `--help` on
it (and on any other command) is a reasonable next stop.
