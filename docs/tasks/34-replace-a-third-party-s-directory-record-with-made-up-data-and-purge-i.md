Requested by Antti on 2026-11-01 in the thread of [15] (T3 thread `f8abbf09-403c-4daf-a936-1da906caaf2a`), after the [security review](../reviews/2026-10-21-security-review.md#p1-personal-data-in-the-public-tree-and-history) found the record. Antti authorised rewriting the public history for it in the same request.

- **Who is affected:** a private person whose directory record (full name, mobile number, employer and business ID) is published in this public repository; and Antti, whose clones of the repository all carry it.
- **The problem:** [`fonecta-lookup/references/fonecta-api.md`](../../fonecta-lookup/references/fonecta-api.md) uses what looks like a real Fonecta lookup result as its example of the API's result shape (lines 96–119 on 2026-10-21). It has been on GitHub since the skill was added in commit `07368a8`, so editing the file alone leaves it in every earlier commit and every clone.
- **What changes:** the example becomes made-up data. Every commit is rewritten so that the real values appear nowhere in the history, on GitHub or in any of Antti's clones, and the old objects are removed from each clone.
- **What is different:** nobody can read the record from the repository, its history or Antti's copies of it.

Scope: this one record, wherever its values occur in the history. Finding P1's other items, Antti's own personal data, are not included. If Antti wants them purged too, he adds them before this task starts, so that every clone is resynchronised only once.

## Work

1. **Prepare privately.** Read the real values from the file into a private `git filter-repo --replace-text` expressions file: mode 0600, under `$TMPDIR`, never printed or committed, deleted at the end. Map each value to an obviously made-up one, in every spelling the history uses: name parts, the mobile number with and without separators, company name, business ID and record IDs. Examples are "Example Person", "Esimerkki Oy" and `1234567-8`. Count each value's occurrences per commit and file with `git log --all -S`, printing no matching lines, so that copies outside the reference file are found too.
2. **Rewrite a fresh mirror clone** of `origin` on agent@tinni with `git filter-repo --replace-text`, over all refs. Confirm that `git log --all -p` of the mirror matches none of the values, and that the new tip differs from the old `main` only in the replaced values. Keep filter-repo's commit map.
3. **Update commit references.** Reviews, task records and evidence files in this repository cite commit hashes. Rewrite them with the commit map in one ordinary commit on top of the rewritten `main`, for example with `rebase-all`'s `rewrite-refs`. Leave other repositories that cite skills-akaihola commits, such as the steward's logs, unchanged, and record where the commit map is kept.
4. **Force-push to GitHub.** Agent accounts cannot push `main`. If `ghpp` is available on the agent account (it was not on agent@tinni's PATH on 2026-11-01), queue the push with `ghpp queue add --force --expected-old FULL_ORIGIN_HASH` as `~/.config/coding-agents/sandbox.md` describes. Otherwise give Antti one command block for akaihola@atom that pushes every rewritten branch and tag with `--force-with-lease=REF:OLD_HASH`. Antti runs the push.
5. **Check what GitHub still keeps.** A force push does not delete the old commits: they stay reachable by hash, and pull-request refs and forks keep them. List forks and pull requests read-only with `gh`, and check whether an old commit with the record still resolves. If it does, give Antti the steps for a GitHub Support request to remove cached views and unreachable commits.
6. **Resynchronise every clone.** In each clone, first record its unpushed commits, uncommitted changes and stash entries. Preserve them by rebasing onto the rewritten history (`git rebase --onto`); never discard local work. Then replace the old refs, expire the reflogs and run `git gc --prune=now` so the old objects are deleted. The clones and copies:
   - **The fleet:** every account in `~/.config/coding-agents/fleet.toml`, six on 2026-11-01. Only akaihola@atom reaches all of them over SSH, and agent accounts cannot reach atom, so give Antti one command block per account and do agent@tinni's clones directly.
   - **agent@tinni:** the canonical checkout `~/prg/skills-akaihola` with all its pacer worktrees under `~/.t3/worktrees/skills-akaihola/`, T3's checkpoint refs under `refs/t3/` and the shared stash. Keep every worktree and branch, rewriting their branches instead of deleting them. Also Claude Code's plugin-marketplace clone at `~/.claude/plugins/marketplaces/skills-akaihola/`; check every account for the same clone.
   - **Copies outside Git:** the kuuskaks archive `akaihola@atom:~/skills-akaihola-from-kuuskaks-2026-11-01.tar.gz` (Antti's: ask whether to rebuild or delete it), and any copied skill directories that the fleet audit reports.
   - **Fallback copies:** agent@hopeli's copy of agent's home is never to be deleted, so ask Antti before updating its clone. The gogo accounts are powered off and nothing may be started there. List their clones as pending until Antti powers gogo on, and ask him how to handle them.
7. **Verify** in every reachable clone and in a fresh clone from GitHub: no value occurs in `git log --all -p`, in the working tree or among the objects left after `gc`. Report counts only.

## Constraints

- Never print, log, commit or send a real value. Report counts, files and commits only.
- Start the rewrite only when no other skills-akaihola task is Scheduled or In Progress. Their worktrees would have to be rebased onto the new history mid-task.
- Force pushes, reflog expiry, `gc` and branch rewrites in other worktrees come only after step 6 has recorded and preserved each clone's local work.
- Antti runs every step on atom; agent accounts make no SSH attempts to atom.

## Acceptance

- `fonecta-lookup/references/fonecta-api.md` shows only made-up values and still documents the result shape.
- A fresh clone from GitHub has no match for any real value in `git log --all -p`. Forks and pull-request refs have been checked, and any remaining exposure has gone to Antti with the GitHub Support steps.
- Every clone and copy in step 6 is on the rewritten history with no match after `gc`, or is listed as pending with its reason.
- The result lists the local work found and preserved in each clone.
- This repository's commit-hash references are updated, and the commit map's location is recorded.
