---
depends-on: [25]
---

Steward issue, 2026-10-22 08:54 refill (steward decisions D53 and D95: simplification that keeps behaviour). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Estimated 1 h.

This is draft D3 of [the 2026-10-22 t3-start-thread architecture review](../reviews/2026-10-22-t3-start-thread-architecture-review.md#draft-issues), filed as written there; read that draft and the finding it cites before starting. The review's line numbers refer to its baseline; recheck them on current `main`.

The helper is the steward's only route for follow-ups and settling threads, so keep its CLI, output shapes and refusals unchanged. Don't call a live T3 server: fake servers verify this work, and the steward runs a read-only `inspect` against hopeli's T3 after the merge.

## Work

Separate projection and message reads from shell-summary composition inside the existing server and reconciliation boundary. Reuse a shell already fetched for that observation, keep merge precedence and archived lookup, and fetch fresh summary state after a dispatch. No persistent connection or snapshot cache.

## Acceptance

- Fake request traces show five successful RPCs for a fresh V2 send and two for an already-visible V2 launch resume.
- Message-ID checks, summary output and archived recovery are unchanged; a fake state change after dispatch appears in the returned summary.
- Each settle target still gets its own fresh shell and its own refusal or error outcome; the helper suite passes with networking disabled.

## Ground rules

- Behaviour stays the same unless the acceptance says otherwise. Write the pinning test first where the draft asks for one.
- Run at most one focused test command at a time, under your launch prompt's memory rule; no full browser suite.
- Keep private paths and host names out of committed docs and code. The check receipt (`*.evidence.json`) is machine evidence and exempt.
- Handoff: a short outcome; details go in this task record.

Tracker: [the skills-akaihola tracker](../../TASKS.md).


## Outcome

Implemented F3 / D3. `Server.thread_projection()` now only reads a thread's
projection (`orchestration.subscribeThread`), which is all a message-ID check
needs. `submission_result()` returns the shell a launch read to find its
thread, the projection and the saved message. `submitted_thread()` is the one
place that composes the summary source: a launch uses its shell entry, a send
lays shell fields over the projection's thread, and both look up archived
threads. `submit()` reuses the observation's shell when it has one and reads a
fresh shell only for a send's summary. After a dispatch it observes again, so
the summary always reflects post-dispatch state. No connection reuse or
snapshot cache was added, and settlement is unchanged.

Successful RPCs per invocation (each RPC uses its own ticket and socket):

| Path                               | Before | After |
| ---------------------------------- | -----: | ----: |
| Fresh send                         |      6 |     5 |
| Fresh launch                       |      6 |     5 |
| Already-visible launch resume      |      3 |     2 |
| Already-visible send resume        |      2 |     2 |

The CLI, saved record format, output fields, refusal messages and exit codes
are unchanged. The two direct test fakes (`LostReplyServer`, `MessageServer`)
gained the narrower `thread_projection()` read and, for `MessageServer`, a
shell; their consolidation stays with D4.

## Verification

- **Pins first:** added the tests below before changing production code. On
  the unchanged script, the three RPC-count cases failed (6, 6 and 3 RPCs) and
  every behaviour pin passed:
  - `test_fresh_submission_reads` — exact method traces and ticket counts for
    a fresh send (shell, thread, dispatch, thread, shell) and a fresh launch
    (shell, shell, launch, shell, thread).
  - `test_visible_resume_reads` — an already-visible launch resume reads shell
    then thread; a send resume reads thread then shell.
  - `test_summary_reads_state_after_dispatch` — a fake state change made
    during dispatch (run finished, new branch) appears in the printed and
    saved summary, for launch and send.
  - `test_summary_merge_precedence` — the fake projection now carries a
    conflicting title and a projection-only `latestTurn`; the shell title wins
    for both operations, and only a send takes `latestTurn`.
  - `test_archived_result_stays_resumable` — now parametrized over launch and
    send; the summary status comes from the archived shell entry.
  - `test_settle_reads_a_fresh_shell_per_target` — a change after settling the
    first target makes the second one refused as active; the trace is shell,
    settle, shell.
- **Re-check on the baseline:** copied the baseline script beside the new test
  file in a temporary directory and ran the pins: 3 failed (the RPC counts),
  8 passed.
- **Helper suite:** 83 tests passed with networking disabled after the change,
  including message-ID checks, accepted-but-missing refusals, lost-reply
  recovery, archived recovery, settlement refusals and errors, and all five
  CLI actions. No live server was called.
- **Lint:** Ruff lint and format checks and `git diff --check` passed. `ty`
  reports only the environment's unresolved `websocket` import; the earlier
  optional-summary diagnostic in `submit()` is gone.

Commands (one test command at a time):

```bash
# Pins before implementation: expected exit 1, three RPC-count failures.
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider t3-start-thread/tests -q -k 'fresh_submission or visible_resume or after_dispatch or fresh_shell_per_target'
# All pins against a temporary copy of the baseline script: exit 1, 3 failed, 8 passed.
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider "$TMPDIR/head/tests" -q -k 'merge_precedence or archived_result or after_dispatch or fresh_shell_per_target or visible_resume or fresh_submission'
# Helper suite after implementation: exit 0.
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider t3-start-thread/tests -q
ruff check t3-start-thread/scripts/start_thread.py t3-start-thread/tests/test_start_thread.py
ruff format --check t3-start-thread/scripts/start_thread.py t3-start-thread/tests/test_start_thread.py
git diff --check
```

## Resource record

Every guarded command ran alone with a 300-second bound, memory/swap
monitoring and process-group cleanup. Measurements describe resources and
exit codes; test results are recorded above.

- **Pins before implementation — started at once:** wait 0.00 s; admission
  MemAvailable 3037.4 MiB; final 3016.8 MiB; starting swap 2170.2 MiB; swap
  growth 0.0 MiB (peak 0.0 MiB); elapsed 3.06 s; exit 1.
- **Pins on the baseline copy — started at once:** wait 0.00 s; admission
  MemAvailable 2731.7 MiB; final 2980.8 MiB; starting swap 2165.7 MiB; swap
  growth 0.0 MiB (peak 0.0 MiB); elapsed 4.42 s; exit 1.
- **Helper suite (83 tests) — started at once:** wait 0.00 s; admission
  MemAvailable 2976.8 MiB; final 2943.7 MiB; starting swap 2165.7 MiB; swap
  growth -2.2 MiB (peak 0.0 MiB); elapsed 2.88 s; exit 0.

## Merge and recorded evidence

Fast-forwarded `main` from `31cb01d7ead6fbe5b31e5cdcda3465a41baf676b` to
`40779b280e7d8163f0880ed80bf038d7de4480f1`. Delivery commits, oldest first:

- `40779b280e7d8163f0880ed80bf038d7de4480f1`

The task branch and worktree remain. The worktree is detached at that merged
commit for clean-checkout evidence recording; the shared checkout stays on
`main`. All three recorded checks passed (exit 0):

- **`rpc-trace-and-summary-pins`:** the 11 pin cases listed above, with
  networking disabled.
- **`helper-fake-suite`:** all 83 helper tests with networking disabled.
- **`lint-format-whitespace`:** Ruff lint and format checks on the helper and
  tests, plus whitespace validation of the delivery commit.

The [machine receipt](26-stop-the-t3-helper-re-reading-thread-shells-it-already-has.evidence.json)
holds the exact commands, tested commit and SHA-256 fingerprints for the
helper, tests, reference and lint configuration. No lockfile exists for this
helper; the test dependencies are pinned in the offline command. No editable
local package checkout is used.

- **Recorder `rpc-trace-and-summary-pins` — started at once:** wait 0.00 s;
  admission MemAvailable 2754.7 MiB; final 2949.5 MiB; starting swap
  2156.2 MiB; swap growth 0.0 MiB (peak 0.0 MiB); elapsed 4.89 s; exit 0.
- **Recorder `helper-fake-suite` — started at once:** wait 0.00 s; admission
  MemAvailable 3046.7 MiB; final 2941.9 MiB; starting swap 2156.2 MiB; swap
  growth 0.0 MiB (peak 0.0 MiB); elapsed 6.39 s; exit 0.
- **Recorder `lint-format-whitespace` — started at once:** wait 0.00 s;
  admission MemAvailable 2950.7 MiB; final 3026.8 MiB; starting swap
  2156.2 MiB; swap growth 0.0 MiB (peak 0.0 MiB); elapsed 0.80 s; exit 0.

No acceptance condition remains unmet. The steward's read-only `inspect`
against the deployed server after the merge is outside this fake-server scope.
Completion is recorded with `[ ]`; user acceptance remains separate.
