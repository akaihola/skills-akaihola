---
name: rebase-all
description: Rebase every branch of a repository onto its base branch (main/master), keeping stacked branches stacked and rewriting commit-hash references in documentation. Use when asked to rebase all branches, sync branches with main, bring every branch up to date, catch up a repo full of stale feature branches, or after the base branch has moved a long way ahead.
---

# Rebase all branches

Bring every local branch up onto the base branch in one pass, in an order that
keeps stacks intact, and fix the commit hashes that documents mention.

The mechanical parts live in `scripts/rebase_all.py`. Judgement — resolving a
conflict, rewording a commit whose meaning changed, deciding what to delete —
stays with you and the user.

## Before anything else

```bash
S=<skill-dir>/scripts/rebase_all.py
python3 $S --repo <repo> report
```

`report` prints every branch with its ahead/behind counts, the stack it belongs
to, and why it would be skipped. Read it out to the user and agree on scope
before touching a single ref.

Then snapshot, always:

```bash
python3 $S --repo <repo> snapshot --out /tmp/claude/rebase-all/refs.txt
```

`restore` puts every branch back from that file. It is the undo button for the
entire run, and it costs nothing to take.

## The order of operations

`plan` emits JSON with an `order` array. Follow it exactly; it is a topological
sort that guarantees a stack parent is rebased before its children.

For each branch in the order:

1. **Rebase it.**

   ```bash
   python3 $S --repo <repo> rebase <branch> --map /tmp/claude/rebase-all/map.txt
   ```

   For a branch stacked on another (`parent` is non-null in the plan), replay
   only its own commits onto the parent's *new* tip, cutting at the parent's
   *old* tip:

   ```bash
   python3 $S --repo <repo> rebase <branch> --map … --onto <new-parent-tip> --upstream <old-parent-tip>
   ```

   Capture the parent's old tip from the snapshot *before* rebasing it.

2. **Fix hash references, in the same branch, immediately.**

   ```bash
   python3 $S --repo <repo> rewrite-refs --map … --worktree <branch-worktree> --dry-run
   ```

   Review the dry run, then drop `--dry-run` to write and commit. This lands a
   separate trailing commit — never an amend, which would rewrite the very
   hashes just written into the documents.

3. **Only then rebase that branch's children**, using its post-fixup tip as
   `--onto`. A child rebased before the fixup exists will not contain it, and
   the stack silently diverges.

## Conflicts

`rebase` exits 2 and names the worktree and conflicted files. It leaves the
rebase in progress so it can be resolved in place; a temporary worktree is kept
alive for exactly this reason.

Do not resolve silently. For each conflict, work out *why* it happened and
propose a resolution to the user:

- **The base already contains an equivalent change.** Common after a fix landed
  upstream by another route. Either `git rebase --skip` the now-redundant
  commit, or keep whatever unique value remains (a comment, a test) and reword
  the commit so its message still describes its diff.
- **Both sides edited the same region for different reasons.** Merge by hand.
- **The branch is very old.** Consider whether rebasing is worth it at all
  versus abandoning the branch.

Resolve, `git add`, `git rebase --continue`, then run `rewrite-refs` for that
branch. If a repo has `rerere` enabled, each resolution is recorded and replayed
automatically on future runs — worth enabling before a big sweep.

## What the script deliberately will not do

- **Rebase the base branch, or anything in `--protected`.**
- **Rebase a branch with uncommitted tracked changes.** Untracked files are
  fine and do not block anything.
- **Touch ancient branches.** Anything more than `--ancient` commits behind the
  base (default 300) is skipped; rebasing those is usually all conflict and no
  value. Pass `--ancient 0` to disable.
- **Delete merged branches.** They are reported as cleanup candidates only.
  Deletion is a separate, deliberate act: most such branches are checked out in
  some worktree, git will refuse to delete them, and unlike a rebase it is not
  cleanly undoable. Offer the list; let the user decide.
- **Push anything.** Rebased branches diverge from their upstreams by
  construction. Say so in the summary and leave force-pushing to the user.

## Worktrees

Worktrees are the main practical obstacle, and the script handles all three
cases:

- A branch **checked out somewhere** is rebased in place, because git refuses to
  move a branch that is checked out elsewhere.
- A branch with **no worktree** gets a temporary one, so the caller's own
  checkout is never disturbed.
- A branch whose worktree is **dirty** is skipped and reported.

Two traps worth knowing:

- **All worktrees share one git directory**, usually inside the main checkout.
  In a sandbox that only grants write access to the current worktree, *every*
  ref update fails, including the rebase itself. If writes fail with "read-only
  file system" pointing at some other checkout's `.git`, that is the cause.
- **The set of worktrees changes under you.** In an agent-driven repo, other
  tasks create and remove worktrees and advance the base branch mid-run. Re-read
  state (`report`) if the run takes a while, and expect a branch to have been
  merged since the plan was made.

## Why the rewrite map comes from git

`rebase` installs a throwaway `post-rewrite` hook via `-c core.hooksPath=…`, and
git itself reports every `old-sha new-sha` pair. This is the only exact source
of commit identity across a rebase — pairing up commit lists from before and
after guesses wrong the moment a commit is dropped, skipped or squashed.

The map is **appended across the whole run** and collapsed transitively before
use. A rewording after a rebase produces `A→B` and then `B→C`; without
collapsing, documents get rewritten to `B`, a commit that no longer exists.

Mentions are matched as 7–40 standalone hex characters and replaced with an
abbreviation of the same length, lengthened by git if that would be ambiguous in
the new history. Hashes of commits that were *not* rewritten — the vast majority
in a documentation-heavy repo — are left untouched.

## Reporting back

Summarise: branches rebased, conflicts and how each was resolved, branches
skipped with the reason, merged branches offered as cleanup candidates, and
which branches now diverge from their upstream.
