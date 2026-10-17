# Gather acceptance evidence for the 2 review-queue items

Steward issue, 2026-10-17 (decisions D7, D10 and D37 in
`/home/agent/my-knowledge/agents/steward/decisions.md`). It takes over
skills-akaihola's part of vault [17]. The vault's tracker is blocked, so this
check runs here, in the repository it checks. The verdicts feed the steward's
next digest, so that Antti can accept or reject these items with less checking
of his own.

## Items

These `- [ ]` items under `## Completed / Accepted`:

- [6], the `t3-start-thread` helper on T3's V2 protocol as well as V1.
- [7], its `settle` command. Steward runs have used it since 2026-10-17 20:08
  against gogo's V1 server; their logs under
  `/home/agent/my-knowledge/agents/steward/log/` are evidence too.

Items whose Hai metadata has no `updatedAt` (it starts with 1970 in `hai-tasks
read`) are legacy bullets that predate Hai timestamps. Judge them against
today's `main`: find the commits that delivered each one (`git log -S`,
`--grep`, its description under `docs/tasks/`) and check that the behaviour
still exists. An item superseded by later work is "would accept" only when the
later work covers its request; name the issue that superseded it.

## Work

Run the test suite that the README or AGENTS.md documents once on current
`main`, and a targeted test wherever an issue names one. Make no call to a live
T3 server. Check criterion 3 with `git revert --no-commit` of an item's merge
commits in a temporary worktree (`git worktree add --detach
"$TMPDIR/revert-check" main`, removed afterwards); conflicts only in `TASKS.md`
and `docs/tasks/` don't count.

For each item, record one line: issue, a one-line outcome, the evidence
(commits, files, test command with pass and fail counts) and a verdict under
`/home/agent/my-knowledge/agents/steward/acceptance-policy.md`:

- **would accept:** all four criteria hold; give the revert command;
- **left to Antti:** name the criterion or the "Always left to Antti" class;
- **not done:** say what is missing.

## Deliverable

A section `## Evidence, YYYY-MM-DD` in this description file, with the lines
grouped by verdict and the counts per verdict at the end.

## Ground rules

- Change no other issue's state or text, and never change `[ ]` to `[x]`: only
  Antti accepts.
- Don't push, deploy or restart services, and don't touch the vault or the
  running pacer.

## Acceptance

- Every listed item has a line with evidence and a verdict.
- Nothing outside this file and the issue's own tracker moves changed.

## Evidence, 2026-10-17

Checked on `main` at `e846843` in a detached `$TMPDIR/revert-check` worktree,
removed afterwards. Both items have Hai timestamps from 2026-10-17, so neither
is a legacy bullet. Neither `README.md` nor `AGENTS.md` documents a test suite,
so the checks were the helper's own tests and the suites the CI workflows run.
No live T3 server was called: the helper tests replace the ticket request and
the WebSocket with fakes, and they ran in an empty network namespace
(`unshare -rn`).

Results on `main`:

- Helper: `uv run --offline --no-project --with pytest --with
  'websocket-client>=1.8,<2' pytest t3-start-thread/tests -q`: 83 passed,
  0 failed. `ruff check t3-start-thread` passed. `ty check --python <venv>
  t3-start-thread` (ty 0.0.89, venv holding the helper's dependencies) passed.
  `git diff --check` of `2aadff5` and of `65fec29` is clean.
- CI suites, none of which touch `t3-start-thread/`: reflect-extensions 36
  passed, 0 failed. android-diagnostics 948 passed, 0 failed outside the
  sandbox. Inside it, 50 failed because the sandbox shows root-owned `/tmp` as
  uid 65534, which the capture-path ownership check rejects.
  himalaya-email-manager 31 passed, 1 failed inside the sandbox:
  `test_attachments_default_to_output_directory` creates `/tmp/saved-emails`,
  and the sandbox's `/tmp` is read-only. Not re-run outside, since that run
  would leave the directory behind.

### Would accept

- [6] V2 alongside V1 in the `t3-start-thread` helper. Outcome: the helper
  tries V1 and switches to V2 only when the WebSocket upgrade returns 426
  `orchestration_protocol_incompatible`; `inspect`, `start`, `send` and
  `resume` keep their CLI and output on both, and `inspect` adds `active`.
  Evidence: commit `2aadff5` (fast-forwarded, no merge commit) in
  `t3-start-thread/scripts/start_thread.py`, `SKILL.md` (the `...`/`…` parking
  warning) and `tests/test_start_thread.py`, whose `wire_server` fixture runs
  every action on protocols 1 and 2, including old V1 records and repeated
  command IDs. 83 passed, 0 failed, as above. The live V1 `inspect`, `tick
  --dry-run` and isolated V2 runs are the worker's, in this issue's
  description. No functionality is removed and V1 still works. One line goes
  beyond the requirements: `main()` sets `SHELL` to Bash for the helper's
  subprocesses. It follows the user's standing rule for agent subprocess
  environments and changes no CLI or output. Revert: `git revert 65fec29
  2aadff5`. [7] builds on [6], so reverting `2aadff5` alone conflicts in
  `tests/test_start_thread.py`. The pair reverts without conflicts and restores
  `t3-start-thread/` exactly as it was at `2aadff5^`.
- [7] `settle` command. Outcome: `settle --thread ID [--thread ID …]` sends
  `thread.settle` with a fresh `commandId` per target on both protocols. It
  refuses archived threads, active threads and threads waiting for an answer,
  an approval or runtime input before dispatch, and carries on with the rest.
  `--dry-run` dispatches nothing. It prints one JSON line per target and exits
  1 on any refusal or error. `inspect` shows `settledAt`. Evidence: commit
  `65fec29` (fast-forwarded) with `test_settle_batch`,
  `test_settle_refuses_and_continues` (every refusal, with and without
  `--dry-run`, on both protocols), `test_settle_archived_collection_and_missing`,
  `test_settle_server_error_continues` and `test_inspect_settled_timestamp`,
  all within the 83 passed, 0 failed. The steward's
  `agents/steward/log/2026-10-17.md` records four runs that settled nine idle
  steward run threads on gogo's V1 server (six at 14:16 UTC, then one each at
  18:42, 20:08 and 23:11 local), with no refusal or error. Threads holding the
  user's messages were left alone. Settling deletes nothing. Revert:
  `git revert 65fec29`, which has no conflicts and restores `t3-start-thread/`
  exactly as it was at `65fec29^`.

### Left to Antti

None. No "Always left to Antti" class applies: neither item handles new
secrets, deploys, publishes, sends messages, deletes data or fixes a security
issue, and neither worker reported anything blocked, partial or unverified.

### Not done

None.

Counts: would accept 2, left to Antti 0, not done 0.
