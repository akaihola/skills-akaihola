# Salvage the Clas Ohlson stdlib commit from kuuskaks' old workspace clone

The retired moltbot workspace on the kuuskaks phone held a clone of this
repository with work that never reached GitHub. Before the workspace was
deleted on 2026-11-01 for nixos-config's
[moltbot removal task](http://tinni/repos/nixos-config/docs/tasks/132-remove-moltbot-and-all-remaining-files-and-configuration.md?f),
Antti saved the whole clone to atom. Requested by Antti on 2026-11-01 as a
low-priority task.

## What was saved

- **Archive:** `akaihola@atom:~/skills-akaihola-from-kuuskaks-2026-11-01.tar.gz`,
  412 entries: the clone's working tree with its `.git`.
- **Branch:** `fix/clasohlson-stdlib`.
- **Commit missing from GitHub:** `2f24303`, 2026-01-31, "clasohlson:
  replace httpx with stdlib urllib.request". Moltbot made it.
- **Staged, uncommitted change:** `clasohlson/scripts/search.py`.
- GitHub has the branches `main` and `clasohlson`. Whether either already
  contains this fix is unknown.

## Prerequisite (Antti)

The agent account cannot reach atom. Antti copies the archive to tinni,
on akaihola@atom:

```bash
scp ~/skills-akaihola-from-kuuskaks-2026-11-01.tar.gz agent@tinni:tmp/
```

If `agent@tinni:~/tmp/skills-akaihola-from-kuuskaks-2026-11-01.tar.gz`
is missing when work starts, mark the issue waiting for Antti with that
command instead of searching elsewhere.

## Work

1. Treat the archive as untrusted data, because moltbot wrote part of it.
   Extract it into a new empty scratch directory outside this
   repository, and run Git there with `-c core.hooksPath=/dev/null`. Run
   none of its scripts.
2. Compare `2f24303` and the staged diff with `clasohlson/scripts/search.py`
   on `main` and on `clasohlson`.
3. If either still adds something, bring it onto a branch here by
   cherry-pick or patch. Review it, and test the Clas Ohlson search script
   without network-heavy runs. Otherwise record why it is superseded.
4. Delete the scratch extraction and tinni's copy of the archive once the
   outcome is recorded. The atom copy is Antti's: ask before suggesting
   its removal.

## Acceptance

- The commit and the staged change each have a recorded outcome: merged,
  kept on a named branch, or superseded, with the reason.
- No secret from the archive enters a commit, record or thread.
- Implementation completion and Antti's acceptance are recorded separately.

## Waiting for archive transfer

Antti must copy the saved clone before the agent can recover the unpublished
search changes. On 2026-11-01, the agent checked the required [tinni archive]
with `test -f`; it was missing. No archive was opened, no saved code was run,
and no recovery or search tests were possible. The issue remains In Progress;
implementation completion and user acceptance have not been recorded.

On akaihola@atom, from any working directory, run:

```bash
scp ~/skills-akaihola-from-kuuskaks-2026-11-01.tar.gz agent@tinni:tmp/
```

After the transfer succeeds, reply “archive copied” in the [salvage thread].
The agent will check the destination and continue the comparison, recovery,
tests and cleanup. This main thread stays open awaiting that reply. No related
threads were created.

[tinni archive]: http://tinni/tmp/skills-akaihola-from-kuuskaks-2026-11-01.tar.gz?f
[salvage thread]: t3-thread://v1/ec83c40b-62c1-446c-a7dd-00b7fe584aeb
