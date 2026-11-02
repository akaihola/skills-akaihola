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

- **The third party's record:** `fonecta-lookup/references/fonecta-api.md` lines 96–119, added in `b479cf6`.
- **Antti's data in the tree** (finding P1):
  - `fonecta-lookup/scripts/fonecta_lookup.py` line 103: his first name, used as the login-success check.
  - `kuluttaja/references/api.md` line 92: his personal email address, added in `35e6224`.
  - `email-mailbox-analyzer/README.md` line 28: a personal email address and the mail provider's host.
  - `email-mailbox-analyzer/README.md` line 52 and `email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh` line 80: his mail-client profile ID.
  - `jmap/SKILL.md` lines 12 and 33, and `jmap/sync_emails.py` line 22: his surname as the JMAP account ID.
  - `himalaya-email-manager/references/scripts.md` lines 32–34: real inbox subjects and sender organisations.
  - `himalaya-email-manager/references/troubleshooting.md` lines 67 and 86: the mail provider's host.
  - `jmap/sync_emails.py` lines 42 and 44: a real-looking correspondent's name and domain.
- **Data left only in older commits:**
  - a sender organisation's domain, added to `jmap/SKILL.md` in `c66c1ff` and removed in `f888119`;
  - his email address in `email-mailbox-analyzer/SKILL.md`, in `b71cce9` and `d54d81d`;
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

## Work record, 2026-11-02

**Who is affected:** the private person whose directory record was published,
the correspondents in the mail examples, and Antti. **The problem:** their data
sat in this public repository's files and in every earlier commit and clone.
**What changed:** the files now carry made-up values, the whole history has
been rewritten without the real values, and the clones on the agent account
have been moved onto the rewritten history with the old objects deleted.
**What is different:** once Antti force-pushes the rewritten branches and
GitHub Support removes the four pull-request references, the data can no
longer be read from GitHub or from the cleaned clones. Until then it remains
on GitHub, in the clones on his other accounts and in the clones listed under
"Pending" below.

Values were read into private files with mode 0600 under the session's
`$TMPDIR` and never printed; this record gives counts only. Those files are
deleted at the end of the session. One exception: while locating the receipt
example (below), one `grep` read unmasked text, and the transport company's
business ID, a public company registry number rather than a private
person's, appeared once in the agent's session transcript. It was not
committed.

### Step 1: the skills without the real values

Commit `70f7c21` (merged to `main`):

- [fonecta-api.md](../../fonecta-lookup/references/fonecta-api.md) shows a
  made-up record ("Example Person", "Esimerkki Oy", business ID `12345678`).
- [fonecta_lookup.py](../../fonecta-lookup/scripts/fonecta_lookup.py) treats
  the login as successful once the login dialog's password field is hidden,
  instead of looking for a first name on the page.
- [email-mailbox-analyzer.sh](../../email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh)
  takes the Thunderbird profile from its argument or `$THUNDERBIRD_PROFILE`,
  or uses the first `~/.thunderbird/*.default-release` directory, and has
  `--help`.
- [sync_emails.py](../../jmap/sync_emails.py) requires the account ID from
  `--account` or `$JMAP_ACCOUNT_ID`.
- The kuluttaja, analyzer, jmap and pi-session-logs examples use RFC 2606
  domains and placeholders.

Offline checks, run by the agent in the task worktree: `bash -n` and `--help`
of the analyzer script (exit 0), its missing-profile error (exit 1) and profile
detection with a fake profile; `sync_emails.py --help` (exit 0) and its
missing-account error (exit 2); `uv run fonecta_lookup.py --help` (exit 0).

### Values found

The private lists hold 41 values plus 8 from the receipt. Beyond the
locations above, the history search found four more kinds, all now replaced:

- the first version of the JMAP skill used two company names in personal
  folder paths, a correspondent's address fragment and two example comments
  naming the organisations;
- an older Himalaya test used a personal folder name in 14 paths;
- `pi-session-logs/SKILL.md` contained the surname in a misspelt repository
  name, now corrected to `skills-akaihola`;
- on Antti's decision ("include receipt", 2026-11-02), a second pass replaced
  a real receipt in older versions of `processing-scanned-receipts/SKILL.md`:
  a transport company's name and business ID, a date and time, a trip's start
  and destination addresses and distance, and an example file name built
  from the same trip. They now read "Esimerkkiyritys Oy", `1234567-8`,
  "Esimerkkikatu" and "Testitie".

Antti's first name, the city and the operator name also occur in unrelated
text, so their replacements were limited to the login check and the record's
`cityName` and `operatorName` fields. A scan for e-mail addresses, Finnish
mobile numbers, business IDs and personal identity codes over all history
found no other personal values; all other phone numbers are placeholders.

### Step 3: rewriting the history

A fresh mirror of GitHub plus every local ref of the main checkout (36
branches, 7 remote-tracking refs, 87 T3 checkpoint refs and one detached
worktree HEAD) was rewritten with `git filter-repo --replace-text`,
`--replace-message` and `--mailmap`, keeping empty commits so that no commit
disappears. Results:

- No object reachable in the rewritten mirror (2643 objects) and no author or
  committer field matches any value.
- Of 500 commits, every rewritten tree equals the original tree with the
  replacement rules applied, path by path, and the two changed commit messages
  equal the rules applied to the old ones. Only 14 files changed.
- The old `main` and the new `main` have identical trees: step 1 had already
  removed every value from the tip.
- Antti's older personal address (one author and one committer entry) now
  reads `13725+akaihola@users.noreply.github.com`. The 27 author entries and
  one committer entry of the OpenClaw agent keep its `.local` address, which
  names no person; changing it needs Antti's decision.

The second pass, for the receipt, ran `git filter-repo --replace-text` and
`--replace-message` over the 503 commits of the first rewrite. It changed
345 commits; only `processing-scanned-receipts/SKILL.md` changed content.
No receipt value remains in the 2687 objects, none of the 47 objects found
earlier and no old commit is present, and every changed file equals the
previous one with only the receipt rules applied. GitHub's 4 pull-request
refs reach none of the receipt objects.

### Step 4: commit references

Commit `8c2e96e` rewrites 178 commit-hash mentions in 33 reviews, task
records and evidence receipts with rebase-all's `rewrite-refs`. Commit
messages were translated by filter-repo itself. After the second pass,
commit `7602f05` rewrote 172 mentions in the same 33 files. The commit maps
(old to final, and first rewrite to final), the list of the 49 objects that
held a value, the rewritten bundles and the resync script are kept privately
in
[agent@tinni:~/.local/state/skills-akaihola-history-rewrite/2026-11-02/](http://tinni/.local/state/skills-akaihola-history-rewrite/2026-11-02/?f).
Other repositories that cite this repository's commits are unchanged.

### Step 6: what GitHub keeps

GitHub reports no forks. The four merged pull requests #12, #19, #20 and #22
keep read-only `refs/pull/N/head` refs that reach 8, 19, 19 and 28 objects
with a value. A force push cannot change them, so the old commits stay
reachable by hash until GitHub Support dereferences the pull requests and
collects the garbage. The first changed commit on GitHub's history is
`35215f1e3c4ffbf7ef0a09e642de799610d20ddd`.

### Step 7: clones on the agent account

Local work was recorded before anything changed. Each clone's record is in
its git directory as `skills-rewrite-record-*.json`.

- **Main checkout `~/prg/skills-akaihola`:** six worktrees, none with staged,
  unstaged or untracked changes; no stash entries; 259 commits missing from
  GitHub (`main`'s 172 plus task branches and T3 checkpoints). All 129 refs
  were moved to their rewritten commits, every worktree was reset to its
  rewritten HEAD, reflogs were expired and `git gc --prune=now` ran.
- **Plugin-marketplace clone:** no local work; 2 refs moved.
- **Scratch clone `~/tmp/hai261-review/skills-akaihola`:** no local work; 2
  refs moved.

Between the two passes, old objects came back into the main checkout twice:
T3 Code's background fetch of `origin/main` from GitHub, and a push from
Antti's laptop clone into this checkout's remote-tracking refs for that
laptop. The second resync moved 128 refs to the final history and deleted
the old objects again. Both sources will bring the old history back until
GitHub has the rewritten branches and the laptop clone is resynced, so the
cleanup is repeated after those steps.

After the first resync's `gc`, a scan of every object left in the three
databases (2681, 1627 and 2465 objects) found no value; after the second,
none of the 49 objects, no old commit and no receipt value remained (2725,
1627 and 2465 objects). Their working trees, including ignored
files, hold no value either. The only matches are in installed third-party
packages under `.venv` (authors who share the third party's first name, and a
brand name), which are not this repository's data.

### Pending

- **Force push:** Antti pushes the rewritten `main` and `clasohlson`.
- **GitHub Support:** Antti asks Support to dereference the four pull
  requests, run garbage collection and remove cached views.
- **Antti's other accounts:** the five other accounts in the fleet
  definition run the resync script after the push.
- **The pre-migration backup clone on this account** and **the fallback copy
  of the agent home:** left unchanged; they need Antti's decision.
- **The powered-off closet laptop's accounts:** pending until it is powered
  on.
- **Verification of a fresh GitHub clone:** after the push, by comparing
  GitHub's branch tips with the verified hashes.

### Guarded heavy commands

| Command | Outcome | MemAvailable at admission, final | Swap start, growth | Time | Exit |
| --- | --- | --- | --- | --- | --- |
| `git filter-repo` on the working mirror | started at once (no wait) | 54435, 54437 MiB | 413, 0 MiB | 4 s | 0 |
| `verify_mirror.py` (value checks, per-commit equivalence) | started at once (no wait) | 54436, 54463 MiB | 413, 0 MiB | 9 s | 0 |
| `refcheck.py` (values reachable from GitHub refs) | started at once (no wait) | 54299, 54289 MiB | 413, 0 MiB | 2 s | 0 |
| `resync.py --apply` on the three agent clones | started at once (no wait) | 54761, 54761 MiB | 413, 0 MiB | 3 s | 0 |
| `git filter-repo`, receipt pass | started at once (no wait) | 55874, 55853 MiB | 412, 0 MiB | 1 s | 0 |
| `verify2.py` (receipt checks, per-commit equivalence) | started at once (no wait) | 55912, 55841 MiB | 412, 0 MiB | 4 s | 0 |
| `resync.py --apply`, second pass, three agent clones | started at once (no wait) | 54930, 55827 MiB | 412, 0 MiB | 2 s | 0 |

The first history scans (value counts with `git log --all -p` over the 8 MiB
repository) ran before the guard existed, without an admission check. The
first reading after them showed 54 GiB available and 413 MiB of swap in use.
