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

## Recovery outcome

Agents can now run the product search with Python alone. The unpublished
change removed a package dependency that current branches still required.
Its reviewed implementation is restored in [the search script], including
usable product data returned with HTTP 400. The saved staged change merely
reverted that improvement, so it adds nothing to preserve.

- **Saved commit:** `2f24303308692e717ce99046049198048fb7a6b7` is
  recovered as a reviewed patch, with explicit `urllib.error` import and
  response cleanup. Only the search script changed in that saved commit.
  Its source blob was `939eefe6760497c9f85ac8cace4f55058a3fe712`.
- **Staged change:** superseded. Its blob
  `4de086ebefad5e7f2ab1ebd07c6e540b5ff97385` exactly matches the saved
  commit's parent script: the entire staged diff undoes the stdlib change.
  Apart from the first line, it also matches all compared branch scripts.
- **Branch comparison:** local main `dbf2642de3e145b242bc1cbba8ae8469b23b29ea`,
  fetched origin/main `ed29af204f248978ca3147ef1c8e1134508ac7d7`, and
  local/fetched clasohlson `559f9a570225daa312d59c53b14d198e3fda41e1`
  still used `httpx`. Both GitHub branches were fetched on 2026-11-01.
- **Safety:** extracted into a fresh scratch directory outside this repository
  using Python's tarfile data filter. Archive Git commands disabled hooks
  with `-c core.hooksPath=/dev/null` and disabled filesystem monitoring;
  no archived scripts were executed. Only the reviewed script patch was
  transferred; no archived Git config, hooks, author metadata or other files
  were imported. The patch and new tests were reviewed for private data.
- **Tests:** the agent ran five offline unittest cases successfully:
  Unicode query encoding and pagination, successful JSON and timeout,
  HTTP 400 product extraction, propagation/closure of other HTTP errors,
  malformed JSON and connection errors, and JSON CLI output. Direct
  executable `--help` also succeeded. No live search was run, so current
  remote API availability remains unverified.
- **Cleanup:** scratch extraction, temporary script copies and tinni archive
  deleted after recording the outcome on 2026-11-01. The atom archive was
  untouched.
- **Transfer history:** archive absent on the first check; the user confirmed
  copying it and the agent verified its presence on 2026-11-01.
- **Thread:** only the [salvage thread] was used; no related threads exist.
  Implementation completion is separate from user acceptance.

[the search script]: ../../clasohlson/scripts/search.py
[salvage thread]: t3-thread://v1/ec83c40b-62c1-446c-a7dd-00b7fe584aeb

## Merged verification

The recovered stdlib change was merged into main at
`d75873d70ac57b440a0b2b21d74fb011a00271e2`; the staged inverse is superseded.
The previous main commit was `dbf2642de3e145b242bc1cbba8ae8469b23b29ea`.
The delivery consists of that single new commit. The task worktree remains
at the delivery commit, clean and available for rerunning checks.

The agent recorded two passing checks from that clean checkout in the
[evidence receipt]: `offline-search` ran five tests and executable help;
`outcomes-scope-cleanup` checked the literal delivery range, recorded outcomes,
whitespace and removal of the scratch extraction and tinni archive. Only the
search script, its skill instructions and its offline tests changed outside
tracker documentation. No archive secrets or unrelated files were imported.
The receipt contains the exact commands. Checks use only the standard library;
there is no applicable lockfile or editable package dependency.

The first attempted merge used a checkout path as the merge argument and was
rejected without changing main; merging the literal delivery commit then
succeeded. No acceptance check failed, was skipped or stopped. Live API
availability was deliberately not tested. Antti's acceptance is still pending:
only Antti settles the main thread. No supporting threads need settlement.

### Recording resource use

Each command below used a 180-second timeout and monitored available memory
and swap use, with termination thresholds of 1024 MiB available memory or
512 MiB swap growth. Each runs the evidence recorder with the declaration
outside the clean checkout and the stated check ID:

```bash
uv run /home/agent/my-knowledge/agents/steward/scripts/check-evidence.py record /home/agent/.local/state/kandev-pacer/t3/evidence/db0306bb9e4e955839005d416b14d607634cb97e81777f5ed6503d56da4e90cc.evidence.json 'skills-akaihola [33]' offline-search
uv run /home/agent/my-knowledge/agents/steward/scripts/check-evidence.py record /home/agent/.local/state/kandev-pacer/t3/evidence/db0306bb9e4e955839005d416b14d607634cb97e81777f5ed6503d56da4e90cc.evidence.json 'skills-akaihola [33]' outcomes-scope-cleanup
```

- **offline-search:** started at once; waited 0.0 seconds; admission 57200 MiB and final 57179 MiB available; starting swap 406 MiB; swap growth 0 MiB; elapsed 0.4 seconds; exit 0.
- **outcomes-scope-cleanup:** started at once; waited 0.0 seconds; admission 56898 MiB and final 56892 MiB available; starting swap 406 MiB; swap growth 0 MiB; elapsed 0.2 seconds; exit 0.

[evidence receipt]: 33-salvage-the-clas-ohlson-stdlib-commit-from-kuuskaks-old-workspace-clon.evidence.json
