# Design

This project has three parts: describing what features exist and which
combinations of them are valid (**modeling**), recording which code belongs
to which feature (**storage**), and producing a working build that contains
only a chosen set of features (**derivation**). The sections below cover
each in turn: what it does, and why it is built the way it is.

Where useful, this is compared against the original tool on the `main`
branch. Some of this project is a direct evolution of that tool (storage, in
particular, is), and some of it, modeling and derivation, did not exist in
the original at all and is new here, so those sections explain the reasoning
on their own rather than forcing a comparison that would not mean anything.

## Modeling: describing what features exist

Before code can be tagged with a feature, there has to be somewhere to say
what features exist in the first place, how they relate to each other, and
which combinations actually make sense as a product. This project uses a
small feature-modeling file at the root of the project, written in a
deliberately small subset of a modeling language called Clafer, popular in
software product line research. It lets you describe a tree of features
(some mandatory, some optional, some mutually exclusive), rules between
them ("feature B requires feature A"), and named, concrete configurations,
e.g. "Minimal" or "Full", that later commands can refer to by name.

This did not exist in the original tool at all: it only ever recorded a flat
feature name per commit, with no concept of how features relate to each
other or which combinations were legal. The closest thing to this idea was
explored in the Rust rewrite, but only as an internal detail of producing a
build, not as something a user described up front. Making it an explicit,
separate file was a deliberate choice: a feature model is a design decision
about the product, independent of any specific line of code, and it is
useful on its own (to validate that a requested combination is even legal)
before any code is involved at all.

Because a partially specified configuration can leave some features
undetermined until its constraints are worked through, resolving a named
configuration is not a simple lookup: the model may need to propagate
mandatory features, group rules ("exactly one of these three"), and boolean
constraints until everything is settled one way or the other, and refuses
early with a specific reason if it cannot be made consistent.

## Storage: recording which code belongs to which feature

This is where the project is most directly a response to the original tool,
which kept a second, ordinary git branch purely for feature records, with
each record filed under the hash of the commit it described. That worked,
and importantly it let you retroactively tag commits that already existed
before the tool was installed. But keying a record to a commit's hash is
fragile: rebasing, amending, or cherry-picking a commit produces a new hash,
and the original design had no way to notice or fix that. The record just
silently stops meaning anything. The branch was also an ordinary, visible
branch, sitting in `git branch` next to real work.

This project keeps the part that worked (metadata kept separate from real
history, and retroactive tagging of pre-existing commits) and tries to fix
the rest:

- The records live on a git ref outside the normal branch namespace, so
  they do not show up in `git branch` or clutter everyday git commands. It
  behaves more like a build artifact than a branch someone might check out
  by mistake.
- A commit's feature record is no longer tied to its hash. The first time a
  commit is tagged, it is given its own separate, small identifier, and a
  pair of git hooks carries that identifier forward automatically whenever
  the commit is rebased, amended, or cherry-picked. The tag is attached to
  that identifier, not to the hash, so it survives the exact operations
  that broke the original scheme. (If the hooks were not installed at the
  time a commit was made, elsewhere on another clone, for instance, there
  is a fallback that recovers the identifier after the fact by comparing
  the commit's content.)
- A tag is not limited to naming a single feature. It can be a full
  condition over several features at once (for example, "feature A and
  feature B, but not C"), and it is attached to a specific region of a
  change rather than to the whole commit, so two unrelated edits landing in
  the same commit can belong to different features.

One consequence of moving records off the normal branch namespace is that
they no longer travel automatically with a plain `git push` or `git fetch`
the way an ordinary branch would. That had to be built deliberately:
explicit commands to share just the metadata, and a way to combine two
people's independently added records without a person having to resolve
conflicts by hand. This is a real cost of the design, not a side benefit,
worth stating plainly alongside its advantages.

## Derivation: building a product from a chosen configuration

This is the payoff of tagging code with features in the first place, and it
did not exist in the original tool at all, so this section is about the
reasoning behind this design on its own terms.

Given a named configuration from the feature model, derivation works out
which tagged regions of code should be present and which should be removed,
and produces an actual, working build containing only the result, as a real
git branch. A few decisions shape how this happens:

- **It is computed fresh from history each time, not maintained as a
  standing branch.** A permanently maintained "Minimal" branch would drift
  out of sync the moment anything upstream changed, and someone would have
  to remember to update it. Deriving it on demand from the current history
  means it can never be stale; it simply reflects whatever the tagged
  history says right now.
- **The result is checked before it is allowed to become visible.** Rather
  than trusting that the derivation logic did the right thing, the tool
  independently re-examines the produced code and confirms that everything
  meant to stay is actually there and everything meant to go is actually
  gone. If anything looks wrong, the derived branch is refused rather than
  handed over in a possibly broken state.
- **A derived build can be edited, and the edits mapped back.** A reduced
  build is not only useful for shipping; it is also a smaller, simpler
  place to notice and fix a bug that would be harder to spot in the full
  codebase. Rather than requiring that fix to be found and reapplied by
  hand in the original source, an edit made on the reduced build can be
  translated back automatically to the corresponding place in the full
  history and committed there, keeping the two in sync.

## Reading feature history back

Everything above exists in service of being able to ask questions about a
project's history: which features touch a given file or line, which commits
implement a given feature, how much of the recent history has been tagged
at all, and whether the project's own hooks and records are still healthy.
These are all read-only views over the same stored records described above,
so they did not need separate design decisions of their own; they exist
mainly to make the stored information actually usable day to day, rather
than write-only bookkeeping nobody looks at again.
