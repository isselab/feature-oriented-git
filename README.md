# git-feature

Feature-oriented version control on top of git: label code changes with the
features they implement, keep those labels accurate through rebases and
cherry-picks, query feature history, and derive product variants containing
only a chosen set of features.

## Development setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync            # create venv + install deps
uv run git-feature --help
make check         # format check + lint + types + tests
```

## Quickstart

**0. Build the tool and put it on `PATH`.** Run this once, from a clone of
this repository:

```sh
uv sync
export PATH="$PWD/.venv/bin:$PATH"
git-feature --version
```

**1. Create a throwaway sandbox and start an ordinary repo there.**
Everything below happens in a scratch directory. Nothing here touches this
repository, and you can delete the sandbox when you're done:

```sh
cd "$(mktemp -d)"
mkdir myapp && cd myapp
git init
cat > app.py <<'EOF'
def hello():
    print("hi")
EOF
git add app.py && git commit -m "add hello"
```

**2. Adopt the tool retroactively.** `init` never touches existing history.
It creates the metadata store on its own ref, installs chained git hooks, and
drops a starter `model.cfr` for you to edit:

```sh
git feature init
```

```text
created feature store at refs/feature/store
created starter model.cfr
installed post-commit dispatcher
installed post-commit.d/50-git-feature
installed post-rewrite dispatcher
installed post-rewrite.d/50-git-feature
```

`git feature doctor` re-checks this at any point (store readable, hooks
chained, every annotation's change-id still known).

<details>
<summary>Peek inside: what <code>init</code> actually created</summary>

Nothing above touched `main`'s history. `init` wrote one commit onto its own
ref, `refs/feature/store`. It's a real, ordinary commit history; plain git
plumbing sees it like any other:

```sh
git log refs/feature/store --oneline
git ls-tree -r --name-only refs/feature/store
git cat-file -p refs/feature/store:meta.json
```

```text
ee2ad46 initialize feature store

meta.json

{
  "schema_version": 1,
  "tool_version": "0.1.0"
}
```

That's the entire store so far: a schema version, nothing else yet.
`git branch`/`git log`/`git status` on `main` never show any of this.

</details>

**3. Describe an initial feature model, and commit it like any other file.**
`model.cfr` (a small [Clafer](https://www.clafer.org/) subset) starts with
just the one feature that exists so far:

```
abstract App {
    core
}

Minimal : App {}
```

```sh
git add model.cfr && git commit -m "describe the feature model"
```

<details>
<summary>Peek inside: this ordinary commit just changed the store too</summary>

This commit landed *after* `init`, so the chained `post-commit` hook fired
and minted it a change-id right away, before anything has even been
annotated. That's the difference between this commit and the `add hello`
one from step 1, which predates the hooks entirely:

```sh
git log refs/feature/store --oneline
git ls-tree -r --name-only refs/feature/store
git cat-file -p refs/feature/store:changeids/map-21.json
```

```text
3b99706 mint change-id for 217f6ca05f87
ee2ad46 initialize feature store

changeids/map-21.json
meta.json

{
  "217f6ca05f87aaabaa03b944e2089bb92f5a2035": {
    "sha": "217f6ca05f87aaabaa03b944e2089bb92f5a2035",
    "change_id": "01KYPVNRPKW5BNQPEERY2PP86V",
    "patch_id": "7289c31690c6a128d4f54cfe274e56806f93214e"
  }
}
```

The map is sharded by the first two hex characters of the commit sha
(`changeids/map-<xx>.json`) so no single file grows without bound as history
grows. No annotation exists yet, just an id, ready for one.

</details>

**4. Annotate the pre-existing commit.** This is the retroactive part: the
`add hello` commit predates `git feature init`, but it can still be annotated.
A new change-id is minted for it lazily, the moment you run:

```sh
git feature annotate <commit_id> --feature core
```

```text
annotated 1 region(s) across 1 commit(s)
minted 1 change-id(s) for older commits
created feature 'core' (auto)
```

<details>
<summary>Peek inside: the annotation itself, in the store</summary>

In the run these snippets are captured from, `add hello` was `d3523422b41d`.
This one command both minted its change-id (lazily, since it predates the
hooks) and wrote the annotation, in a single store commit:

```sh
git log refs/feature/store --oneline
git ls-tree -r --name-only refs/feature/store
git cat-file -p refs/feature/store:features/core.json
git cat-file -p refs/feature/store:annotations/01KYPVPA4NRNNSEJA951YEEHM0.json
```

```text
27b3c8a annotate 1 regions
3b99706 mint change-id for 217f6ca05f87
ee2ad46 initialize feature store

annotations/01KYPVPA4NRNNSEJA951YEEHM0.json
changeids/map-21.json
changeids/map-d3.json
features/core.json
meta.json

{
  "name": "core",
  "description": "",
  "owners": [],
  "tags": [],
  "links": [],
  "auto_created": true
}

[
  {
    "anchor": {
      "change_id": "01KYPVPA4NRNNSEJA951YEEHM0",
      "path": "app.py",
      "old_span": [0, 0],
      "new_span": [1, 2],
      "fingerprint": "7fa8eae0365e947e"
    },
    "presence": "core",
    "author": "Dev",
    "ts": "2026-07-29T11:55:51.829972Z",
    "note": null
  }
]
```

`features/core.json` is the auto-created feature definition. It's bare-bones
since it was never described in `model.cfr` by hand. The annotation is filed
under `annotations/<change_id>.json`, keyed by the change-id from the map,
never by the sha directly. That's what lets it survive a rebase or amend of
this commit later on.

</details>

**5. Keep developing: new commits, annotated as they land.** This is the
steady-state workflow from here on: write code, commit normally, annotate
right after:

```sh
cat >> app.py <<'EOF'

def auth():
    return "token"
EOF
git commit -am "auth: add auth"
git feature annotate HEAD --feature auth
```

```sh
cat >> app.py <<'EOF'

def stats():
    return {"calls": 0}
EOF
git commit -am "stats: add stats"
git feature annotate HEAD --feature stats
```

`git feature list` shows the catalog built up so far, `git feature blame
<file>` the per-line result:

```sh
git feature list
```

```text
FEATURE  ANNOTATIONS  CHANGES
auth             1        1  (auto)
core             1        1  (auto)
stats            1        1  (auto)
```

```sh
git feature blame app.py
```

```text
   1  core   def hello():
   2  core       print("hi")
   3  auth   
   4  auth   def auth():
   5  auth       return "token"
   6  stats  
   7  stats  def stats():
   8  stats      return {"calls": 0}
```

<details>
<summary>Peek inside: the store after two more rounds of commit + annotate</summary>

Each `git commit` above triggered the hook's automatic mint; each
`git feature annotate` added one more store commit on top of that. The
store's own history now has one entry per write, in order:

```sh
git log refs/feature/store --oneline
git ls-tree -r --name-only refs/feature/store
```

```text
8e35c15 annotate 1 regions
e3ccbd7 mint change-id for 2e8f75a886b1
55aef20 annotate 1 regions
a5ef64b mint change-id for f204a9a5b5a2
27b3c8a annotate 1 regions
3b99706 mint change-id for 217f6ca05f87
ee2ad46 initialize feature store

annotations/01KYPVPA4NRNNSEJA951YEEHM0.json
annotations/01KYPVPGCTC80RZBCYT2BDBMBM.json
annotations/01KYPVPGRW2VXHWEFYQBVE8C43.json
changeids/map-21.json
changeids/map-2e.json
changeids/map-d3.json
changeids/map-f2.json
features/auth.json
features/core.json
features/stats.json
meta.json
```

One `annotations/<change_id>.json` file per annotated commit, one
`features/<name>.json` per feature, `changeids/` sharded by sha prefix.
`model.cfr` itself is never in here. It's a normal file, versioned in `main`
like any other; the store only ever holds the tool's own metadata.

</details>

**6. Not every change needs annotating.** A region that's never annotated is
simply never tracked. It survives every future derivation untouched, no
matter which features are on or off. Here's a commit that's deliberately
left alone, followed by one that isn't:

```sh
sed -i '/^def stats():/i # --- stats extras ---' app.py
git commit -am "stats: add a helper comment"
# left unannotated on purpose
```

```sh
cat >> app.py <<'EOF'

def reset_stats():
    return {"calls": 0}
EOF
git commit -am "stats: add reset_stats"
git feature annotate HEAD --feature stats
```

```sh
git feature blame app.py
```

```text
   1  core   def hello():
   2  core       print("hi")
   3  auth   
   4  auth   def auth():
   5  auth       return "token"
   6  stats  
   7  -      # --- stats extras ---
   8  stats  def stats():
   9  stats      return {"calls": 0}
  10  stats  
  11  stats  def reset_stats():
  12  stats      return {"calls": 0}
```

Line 7's `-` is the never-annotated comment commit. `blame` correctly shows
it as unowned by any feature rather than silently attaching it to whatever
surrounds it. It also landed in the middle of the previously-annotated
`stats()` region, which matters again in step 9.

**7. Attach a presence *condition*, not just a feature.** `--feature` is
shorthand for "present when this one feature is on." `--presence` accepts a
full boolean expression over existing features, useful when a region only
makes sense with several features together:

```sh
cat >> app.py <<'EOF'

def report():
    return {"user": auth(), "usage": stats()}
EOF
git commit -am "add combined report"
git feature annotate HEAD --presence 'auth & stats'
```

```text
annotated 1 region(s) across 1 commit(s)
```

`git feature list` now counts this annotation against *both* features it
mentions, and `git feature blame` prints the expression itself for those
lines:

```sh
git feature list
```

```text
FEATURE  ANNOTATIONS  CHANGES
auth             2        2  (auto)
core             1        1  (auto)
stats            3        3  (auto)
```

```sh
git feature blame app.py
```

```text
   1  core          def hello():
   2  core              print("hi")
   3  auth          
   4  auth          def auth():
   5  auth              return "token"
   6  stats         
   7  -             # --- stats extras ---
   8  stats         def stats():
   9  stats             return {"calls": 0}
  10  stats         
  11  stats         def reset_stats():
  12  stats             return {"calls": 0}
  13  auth & stats  
  14  auth & stats  def report():
  15  auth & stats      return {"user": auth(), "usage": stats()}
```

**8. Extend the model now that `auth` and `stats` are real, and add named
configurations.** These are the variant specs `checkout` reads by name:

```
abstract App {
    core
    auth ?
    stats ?
}

Minimal : App {
    [ no auth ]
    [ no stats ]
}

Full : App {
    [ auth ]
    [ stats ]
}
```

```sh
git add model.cfr && git commit -m "extend the feature model with auth and stats"
git feature model validate
```

```text
model ok
```

**9. Derive variants.** `checkout <instance>` resolves the model, removes
every region whose presence condition evaluates to false, and refuses to move
the branch unless the derived tree verifies. `--dry-run` shows the plan
first:

```sh
git feature checkout Minimal --dry-run
```

```text
variant Minimal from 93c626a252ef (dry run)
disabled features: auth, stats
would remove:
  app.py: lines 3-5  [auth] (exact)
  app.py: lines 6-6, lines 8-9  [stats] (moved)
  app.py: lines 10-12  [stats] (exact)
  app.py: lines 13-15  [auth & stats] (exact)
kept regions: 1
no conflicts
```

The `stats` region shows `(moved)`, split across two line runs. That's the
never-annotated comment from step 6 sitting in the middle of what used to be
one contiguous block. Blame-forward still finds all of it (nothing was
lost), but not as a single unbroken window, so the resolver honestly reports
lower confidence instead of claiming `exact`. Line 13's `[auth & stats]` is
the presence condition from step 7: with both `auth` and `stats` disabled,
the expression evaluates false, so the region is removed here too. A
presence condition doesn't need a feature of its own to gate a derivation.

```sh
git feature checkout Full --dry-run
```

```text
variant Full from 93c626a252ef (dry run)
disabled features: (none)
would remove: nothing
kept regions: 5
no conflicts
```

With every feature enabled, `auth & stats` evaluates true and every region,
including the presence-conditioned one, stays. Then derive both for real:

```sh
git feature checkout Minimal
cat app.py
```

```text
variant Minimal: refs/heads/variant/Minimal -> 5b7ae588223d (4 region(s) removed, verified)
switched to variant/Minimal

def hello():
    print("hi")
# --- stats extras ---
```

That leftover `# --- stats extras ---` comment is the honest consequence of
step 6: it was never annotated, so `checkout` has no basis to remove it.
Leaving a change unannotated really does mean "leave this alone forever,"
not "figure it out later."

```sh
git checkout main
git feature checkout Full
git feature variant list
```

```text
variant Full: refs/heads/variant/Full -> e35379915600 (0 region(s) removed, verified)
switched to variant/Full

Full: variant/Full from 93c626a252ef (disabled: (none)) [current]
Minimal: variant/Minimal from 93c626a252ef (disabled: auth, stats) [current]
```

<details>
<summary>Peek inside: the derivation manifest and the variant branches</summary>

Unlike everything above, `variant/Minimal` and `variant/Full` are ordinary
branches (`refs/heads/variant/<name>`). They show up in `git branch` and can
be inspected with plain git. What's *not* ordinary is that each derivation
also records a manifest in the store: the resolved feature assignment plus a
decision (included/excluded, resolved position, confidence) for every region
it considered, including *why* the `auth & stats` region was excluded, not
just that it was:

```sh
git for-each-ref refs/heads/variant
git cat-file -p refs/feature/store:variants/Minimal.json
```

```text
e3537991560003ae47d1e66c06124f4591b1d501 commit	refs/heads/variant/Full
5b7ae588223dc54f27099477ed97f44fb079aa35 commit	refs/heads/variant/Minimal

{
  "instance": "Minimal",
  "base_commit": "93c626a252efcadfa6e85f28a754d7f4e3e0f8cd",
  "assignment": { "auth": false, "core": true, "stats": false, "App": true },
  "decisions": [
    {
      "anchor": { "change_id": "01KYPVPA4NRNNSEJA951YEEHM0", "path": "app.py",
                  "old_span": [0, 0], "new_span": [1, 2],
                  "fingerprint": "7fa8eae0365e947e" },
      "presence": "core", "included": true,
      "resolved_span": [1, 2], "resolved_runs": null,
      "resolved_path": null, "confidence": "exact"
    },
    {
      "anchor": { "change_id": "01KYPVPGCTC80RZBCYT2BDBMBM", "path": "app.py",
                  "old_span": [2, 0], "new_span": [3, 3],
                  "fingerprint": "f0dba3d7bc95b14b" },
      "presence": "auth", "included": false,
      "resolved_span": [3, 3], "resolved_runs": null,
      "resolved_path": null, "confidence": "exact"
    },
    {
      "anchor": { "change_id": "01KYPVPGRW2VXHWEFYQBVE8C43", "path": "app.py",
                  "old_span": [5, 0], "new_span": [6, 3],
                  "fingerprint": "26a897eb2dd8f5a2" },
      "presence": "stats", "included": false,
      "resolved_span": [6, 4], "resolved_runs": [[6, 1], [8, 2]],
      "resolved_path": null, "confidence": "moved"
    },
    {
      "anchor": { "change_id": "01KYPVPXDSHJVJ085PT5SVJ1V8", "path": "app.py",
                  "old_span": [9, 0], "new_span": [10, 3],
                  "fingerprint": "73ebc2e1bf5f77c8" },
      "presence": "stats", "included": false,
      "resolved_span": [10, 3], "resolved_runs": null,
      "resolved_path": null, "confidence": "exact"
    },
    {
      "anchor": { "change_id": "01KYPVQ40H5G6D8ETW9M3EKS0C", "path": "app.py",
                  "old_span": [12, 0], "new_span": [13, 3],
                  "fingerprint": "08445be43edadfc4" },
      "presence": "auth & stats", "included": false,
      "resolved_span": [13, 3], "resolved_runs": null,
      "resolved_path": null, "confidence": "exact"
    }
  ],
  "created_at": "2026-07-29T11:56:41.641428Z"
}
```

That `"moved"` decision is the one from the dry-run above. Notice
`resolved_runs: [[6, 1], [8, 2]]` records the *exact* two surviving pieces
(1 line, then 2 lines), while `resolved_span: [6, 4]` is just their overall
outer extent. The last decision is the `auth & stats` region: `presence`
records the raw expression, not a feature name, and `included: false` is
what evaluating that expression against `assignment` actually produced.
This is the same record whether a region's presence is one feature or a full
boolean condition. `checkout --refresh`/`variant list` read this back later
to know what a variant actually contains and whether its base has gone
stale. The branch's tree alone wouldn't say *why* a region was removed or
how confidently it was located.

</details>

**10. Edit a variant directly, then put the edit back onto the branch it came
from.** `view <instance>` derives the variant like `checkout` does, but also
opens a session that `putback` later reads to map your edits back through
the derivation — translating line numbers from the stripped-down variant
back onto the original file:

```sh
git checkout main
git feature view Full
```

```text
view of Full: editing 8014fe9076c8 (from main @ e62c9133c0cc) — put edits back with 'git feature putback'
switched to variant/Full
```

Add a new function right there in the view, as an ordinary uncommitted edit:

```sh
cat >> app.py <<'EOF'

def version():
    return "1.0"
EOF
git feature putback
```

```text
main -> 43a9e6a7b52f (1 file(s) transplanted)
view of Full refreshed onto the new source commit
```

`putback` created one new commit on `main`, containing just that addition,
and fast-forwarded `main` onto it. It also refreshed the `Full` view in
place so it stays usable for further edits without re-running `view` by
hand.

```sh
git checkout main
git feature blame app.py
```

```text
   1  core          def hello():
   2  core              print("hi")
   3  auth          
   4  auth          def auth():
   5  auth              return "token"
   6  stats         
   7  -             # --- stats extras ---
   8  stats         def stats():
   9  stats             return {"calls": 0}
  10  stats         
  11  stats         def reset_stats():
  12  stats             return {"calls": 0}
  13  auth & stats  
  14  auth & stats  def report():
  15  auth & stats      return {"user": auth(), "usage": stats()}
  16  -             
  17  -             def version():
  18  -                 return "1.0"
```

`version()` lands on `main` unannotated, same `-` as the step 6 comment:
`putback` transplants code, it doesn't guess a presence condition for it.
Annotate it the normal way (step 5) if it should belong to a feature.
