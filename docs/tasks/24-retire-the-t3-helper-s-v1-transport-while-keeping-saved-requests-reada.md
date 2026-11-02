Steward issue, 2026-10-22 08:54 refill (steward decisions D53 and D95: simplification that keeps behaviour). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Estimated 1 h.

This is draft D1 of [the 2026-10-22 t3-start-thread architecture review](../reviews/2026-10-22-t3-start-thread-architecture-review.md#draft-issues), filed as written there; read that draft and the finding it cites before starting. The review's line numbers refer to its baseline; recheck them on current `main`.

The helper is the steward's only route for follow-ups and settling threads, so keep its CLI, output shapes and refusals unchanged. Don't call a live T3 server: fake servers verify this work, and the steward runs a read-only `inspect` against hopeli's T3 after the merge.

## Work

Connect with V2 at once; remove the V1 handshake fallback, V1 server-state decoding and protocol selection outside the transport. Keep the saved command shape and the V2 converter, summary compatibility keys, CLI, settings and settlement refusals. Collapse the live-server parametrization to V2, adapt the older direct fakes just enough to keep the suite passing, and update `t3-start-thread/references/helper.md` in the same change. Record migration and wholesale fixture consolidation are out of scope (draft D4 owns the fakes).

## Acceptance

- The first socket requests V2 with one ticket; a failed authentication or upgrade does not retry.
- The full helper suite passes with all five actions covered on V2, with networking disabled.
- Old start and send records keep their saved command, thread and message IDs; pending, acknowledged, archived and lost-reply recovery still pass.
- The reference distinguishes V2 server support from old-record support.

## Ground rules

- Behaviour stays the same unless the acceptance says otherwise. Write the pinning test first where the draft asks for one.
- Run at most one focused test command at a time, under your launch prompt's memory rule; no full browser suite.
- Keep private paths and host names out of committed docs and code. The check receipt (`*.evidence.json`) is machine evidence and exempt.
- Handoff: a short outcome; details go in this task record.

Tracker: [the skills-akaihola tracker](../../TASKS.md).

## Implementation and validation, 2026-10-22

The helper now connects with V2 at once. `Server.call()` adds
`orchestrationProtocol=2` to every socket URL, and the upgrade fallback, the
`protocol` attribute and the `V2` constant are gone, so `dispatch()` and
`submit()` no longer select a protocol. Also removed: V1 thread-snapshot
decoding, V1 activity interpretation in `thread_summary()` and the V1
`turnId` read for `messageTurnId`. The V2 shell contract makes `status`
required, and V2 messages carry `runId` without `turnId`; both were checked
against the upstream contracts at `v0.1.1-nightly.20261017.3238`. Kept
unchanged: the V1-shaped saved command and its V2 converter, the summary
keys (`latestTurn` and `session` still appear, as `null`), the CLI, the
settings validation and every settlement refusal. That includes the
`hasPendingUserInput` and `hasPendingApprovals` guards.

Tests:

- **Pinning tests first:** `test_first_socket_requests_v2_with_one_ticket`
  and `test_failed_upgrade_never_retries` failed on the unchanged helper
  (6 failed). The first socket lacked the V2 parameter, and a 426
  `orchestration_protocol_incompatible` retried with a second ticket.
  `test_failed_authentication_never_retries` pins existing behaviour: a
  refused ticket opens no socket.
- **Live-server parametrization:** `wire_server` is now V2 only, and its fake
  still rejects a socket without the V2 parameter with 426. Any action that
  opened a V1 socket would fail. Tests named "both protocols" or "either
  protocol" were renamed, and the V1 branches in the fakes and assertions
  were removed. Seven V1-only activity cases left `test_activity`.
- **Older direct fakes:** `LostReplyServer` now accepts
  `orchestration.launchThread` and serves the launched thread's initial
  message. `MessageServer` accepts `message.dispatch` and reports `runId`.
  Assertions about saved command and settings shape now read the request
  record; wire assertions read the V2 payload. Consolidating these fakes
  remains with draft D4.
- **Old records:** `test_resume_unsubmitted_old_record[start|send]` resumes
  a V1-shaped record. It checks that the saved command is unchanged and that
  the thread, command and message IDs are reused, that a forced duplicate
  dispatch is deduplicated, and that every socket requested V2.

Acceptance coverage (67 tests, all on V2):

- **First socket and no retry:** the pinning tests above.
- **All five actions on V2:** inspect (`test_inspect_summaries`,
  `test_inspect_settled_timestamp`), start (`test_start_and_resume`, four
  cases), send (`test_send_and_resume`, `test_paced_send_dry_run`), settle
  (the four `test_settle_*` functions) and resume (all of the resume tests).
- **Recovery:** pending (`test_resume_partial_launch`,
  `test_resume_send_before_acceptance_reuses_command_and_message_ids`),
  acknowledged (`test_accepted_missing_result_is_not_resent`,
  `test_resume_accepted_but_missing_message_does_not_resend`,
  `test_accepted_but_missing_thread_is_not_recreated`), archived
  (`test_archived_launch_stays_resumable`) and lost reply
  (`test_resume_after_lost_reply_does_not_submit_again`,
  `test_resume_send_after_lost_reply_does_not_duplicate_message`, and the
  start and send CLI tests).
- **Reference:** the [helper reference](../../t3-start-thread/references/helper.md#server-and-record-compatibility)
  has a new section on server and record compatibility. It separates V2-only
  server support from old-record support. It also drops the "either protocol"
  and handshake-detection claims and links the V2 contracts next to the V1
  record-format source.

Before this change the suite had 100 tests. The drop to 67 comes from removing
the V1 copies of each case and the V1-only activity cases. No distinct
refusal, persistence or recovery assertion was dropped.

Commands, run from the task worktree; the suite ran with networking disabled:

```bash
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider t3-start-thread/tests -q
ruff check t3-start-thread && ruff format --check t3-start-thread
```

No live T3 server was called. The steward's read-only `inspect` against the
deployed server after the merge confirms the V2-only premise.

## Resource record

- **Helper suite — started at once:** wait 0.00 s; admission MemAvailable
  2767.4 MiB; final 2579.3 MiB; starting swap 2156.2 MiB; swap growth
  0.0 MiB (peak 0.0 MiB); elapsed 4.51 s; exit 0. A 180-second bound and
  process-group cleanup applied; no other heavy command ran at the same time.

## Merge and recorded checks

Fast-forwarded `main` from `e4cace3560ab28b70304e7ece9c87b99e200ba79` to
delivery commit `222b80c555aaa5995049145aa8691009431be2a3`. The task branch
and worktree are kept. The evidence recorder ran four checks against the task
worktree, detached at the delivery commit, and all four passed (exit 0):

- **`v2-first-socket-no-retry`:** the handshake pins; 7 tests.
- **`helper-fake-suite`:** the full helper suite with networking disabled;
  67 tests.
- **`old-record-recovery`:** old-record, pending, acknowledged, archived and
  lost-reply recovery, plus the start and send CLI resume tests; 16 tests.
- **`reference-compatibility`:** checks that the reference separates V2-only
  server support from old-record support, and that the "either protocol" and
  handshake-detection claims are gone.

This helper has no lockfile. The receipt declares SHA-256 dependencies on the
helper script, its tests and the reference instead; no editable checkouts are
used. Ruff lint and format checks also passed before the merge; they are not
an acceptance criterion and are not in the receipt.

- **Recorder runs — all started at once:** wait 0.00 s each, one at a time,
  with a 300-second bound.
  - `v2-first-socket-no-retry`: admission MemAvailable 2685.5 MiB; final
    2565.2 MiB; starting swap 2142.7 MiB; growth 0.0 MiB; 4.05 s; exit 0.
  - `helper-fake-suite`: admission 2559.4 MiB; final 2759.9 MiB; starting
    swap 2142.7 MiB; growth 0.5 MiB; 5.01 s; exit 0.
  - `old-record-recovery`: admission 2680.6 MiB; final 2704.1 MiB; starting
    swap 2143.2 MiB; growth 0.0 MiB; 5.08 s; exit 0.
  - `reference-compatibility`: admission 2704.1 MiB; final 2665.9 MiB;
    starting swap 2143.2 MiB; growth 0.0 MiB; 1.00 s; exit 0.
