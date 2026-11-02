Requested by Antti on 2026-11-01 in the thread of [15] (T3 thread `f8abbf09-403c-4daf-a936-1da906caaf2a`), after the [security review](../reviews/2026-10-21-security-review.md#p1-personal-data-in-the-public-tree-and-history) found the data. On 2026-11-02 he widened it from the third party's directory record to his own personal data. He authorised rewriting the public history for both.

- **Who is affected:**
  - a private person whose directory record (full name, mobile number, employer and business ID) is published in this public repository;
  - correspondents whose names and domains appear in mail examples;
  - Antti, whose email addresses, surname, mail provider, mail-client profile ID and real inbox subjects are published, and whose clones all carry them.
- **The problem:** the review's finding P1 lists these values in skill references, scripts and READMEs, and some survive only in older commits. All of it is on GitHub, so editing the files alone leaves it in every earlier commit and every clone.
- **What changes:**
  - Each value becomes made-up data, and the skills that used the real values keep working.
  - Every commit, including its author and committer addresses, is rewritten so that the real values appear nowhere in the history, on GitHub or in any of Antti's clones.
  - The old objects are removed from each clone.
- **What is different:** nobody can read this data from the repository, its history or Antti's copies of it.

## What to purge

Read the values from these places into the private files of step 2, never into a command line, log or commit. Line numbers are from 2026-10-21.

- **The third party's record:** `fonecta-lookup/references/fonecta-api.md` lines 96–119, added in `07368a8`.
- **Antti's data in the tree** (finding P1):
  - `fonecta-lookup/scripts/fonecta_lookup.py` line 103: his first name, used as the login-success check.
  - `kuluttaja/references/api.md` line 92: his personal email address, added in `cbcec65`.
  - `email-mailbox-analyzer/README.md` line 28: a personal email address and the mail provider's host.
  - `email-mailbox-analyzer/README.md` line 52 and `email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh` line 80: his mail-client profile ID.
  - `jmap/SKILL.md` lines 12 and 33, and `jmap/sync_emails.py` line 22: his surname as the JMAP account ID.
  - `himalaya-email-manager/references/scripts.md` lines 32–34: real inbox subjects and sender organisations.
  - `himalaya-email-manager/references/troubleshooting.md` lines 67 and 86: the mail provider's host.
  - `jmap/sync_emails.py` lines 42 and 44: a real-looking correspondent's name and domain.
- **Data left only in older commits:**
  - a sender organisation's domain, added to `jmap/SKILL.md` in `68943c4` and removed in `0caf1d1`;
  - his email address in `email-mailbox-analyzer/SKILL.md`, in `8eb0a53` and `39236b2`;
  - local paths in older tests that name his personal folders.
- **Commit metadata:** on 2026-11-02, 28 author entries and 2 committer entries used 2 distinct addresses that are not GitHub noreply addresses. Map Antti's to `13725+akaihola@users.noreply.github.com`, the address the repository's recent commits use, with filter-repo's mailmap, and keep the author names. If an address belongs to someone else, ask Antti before changing it.
- **Not purged:** Antti's name in copyright lines (`himalaya-email-manager/scripts/email_save.py` line 2, `ecb-rates/fetch_ecb_rates.py` line 1) and as commit author name. Both are his chosen public attribution. Change them only if Antti adds them to this record.

Then count each value's occurrences per commit and file with `git log --all -S`, printing no matching lines, to find further copies.

## Work

1. **Keep the skills working without the real values.** Make these changes in an ordinary commit, merged to `main` before the rewrite:
   - Take the mail-client profile path as an argument, or detect it.
   - Require the JMAP account ID from an argument or environment variable.
   - Make the Fonecta login check look for a page element that names no one.
   - Replace the examples with RFC 2606 domains and obviously made-up names, subjects, numbers and IDs, such as "Example Person", "Esimerkki Oy" and `1234567-8`.

   Follow the pre-commit checklist in `AGENTS.md`.
2. **Prepare privately.** Write the `git filter-repo --replace-text` expressions file and the mailmap with mode 0600 under `$TMPDIR`. Never print or commit them, and delete them at the end. Map each value to a made-up replacement in every spelling the history uses: with and without separators, and in plus-addressed forms.
3. **Rewrite a fresh mirror clone** of `origin` on agent@tinni with `git filter-repo --replace-text` and `--mailmap`, over all refs. Confirm three things, and keep filter-repo's commit map:
   - `git log --all -p` of the mirror matches none of the values.
   - `git log --all --format='%ae %ce'` shows no mapped address.
   - The new tip differs from the old `main` only in the replaced values.
4. **Update commit references.** Reviews, task records and evidence files in this repository cite commit hashes. Rewrite them with the commit map in one ordinary commit on top of the rewritten `main`, for example with `rebase-all`'s `rewrite-refs`. Leave other repositories that cite skills-akaihola commits, such as the steward's logs, unchanged, and record where the commit map is kept.
5. **Force-push to GitHub.** Agent accounts cannot push `main`. If `ghpp` is available on the agent account (it was not on agent@tinni's PATH on 2026-11-01), queue the push with `ghpp queue add --force --expected-old FULL_ORIGIN_HASH` as `~/.config/coding-agents/sandbox.md` describes. Otherwise give Antti one command block for akaihola@atom that pushes every rewritten branch and tag with `--force-with-lease=REF:OLD_HASH`. Antti runs the push.
6. **Check what GitHub still keeps.** A force push does not delete the old commits: they stay reachable by hash, and pull-request refs and forks keep them. List forks and pull requests read-only with `gh`, and check whether an old commit with any value still resolves. If one does, give Antti the steps for a GitHub Support request to remove cached views and unreachable commits.
7. **Resynchronise every clone.** In each clone, first record its unpushed commits, uncommitted changes and stash entries. Preserve them by rebasing onto the rewritten history (`git rebase --onto`); never discard local work. Then replace the old refs, expire the reflogs and run `git gc --prune=now` so the old objects are deleted. The clones and copies:
   - **The fleet:** every account in `~/.config/coding-agents/fleet.toml`, six on 2026-11-01. Only akaihola@atom reaches all of them over SSH, and agent accounts cannot reach atom, so give Antti one command block per account and do agent@tinni's clones directly.
   - **agent@tinni:** the canonical checkout `~/prg/skills-akaihola` with all its pacer worktrees under `~/.t3/worktrees/skills-akaihola/`, T3's checkpoint refs under `refs/t3/` and the shared stash. Keep every worktree and branch, rewriting their branches instead of deleting them. Also Claude Code's plugin-marketplace clone at `~/.claude/plugins/marketplaces/skills-akaihola/`; check every account for the same clone.
   - **Copies outside Git:** any copied skill directories that the fleet audit reports. Antti reported on 2026-11-02 that he had removed the kuuskaks archive on atom, so nothing remains to do there.
   - **Fallback copies:** agent@hopeli's copy of agent's home is never to be deleted, so ask Antti before updating its clone. The gogo accounts are powered off and nothing may be started there. List their clones as pending until Antti powers gogo on, and ask him how to handle them.
8. **Verify** in every reachable clone and in a fresh clone from GitHub. No value may occur in `git log --all -p`, in author or committer addresses, in the working tree or among the objects left after `gc`. Report counts only.

## Constraints

- Never print, log, commit or send a real value. Report counts, files and commits only.
- Start the rewrite only when no other skills-akaihola task is Scheduled or In Progress. Their worktrees would have to be rebased onto the new history mid-task.
- Force pushes, reflog expiry, `gc` and branch rewrites in other worktrees come only after step 7 has recorded and preserved each clone's local work.
- Antti runs every step on atom; agent accounts make no SSH attempts to atom.

## Acceptance

- Every location under "What to purge" shows only made-up values.
- Offline checks of the changed scripts pass: their tests or `--help` runs.
- A fresh clone from GitHub has no match for any real value in `git log --all -p` or in author and committer addresses.
- Forks and pull-request refs have been checked, and any remaining exposure has gone to Antti with the GitHub Support steps.
- Every clone and copy in step 7 is on the rewritten history with no match after `gc`, or is listed as pending with its reason.
- The result lists the local work found and preserved in each clone.
- This repository's commit-hash references are updated, and the commit map's location is recorded.
