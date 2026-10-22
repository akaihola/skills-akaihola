---
depends-on: [24]
---

Steward issue, 2026-10-22 08:54 refill (steward decisions D53 and D95: simplification that keeps behaviour). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Estimated 1 h.

This is draft D2 of [the 2026-10-22 t3-start-thread architecture review][architecture-review], filed as written there; read that draft and the finding it cites before starting. The review's line numbers refer to its baseline; recheck them on current `main`.

The helper is the steward's only route for follow-ups and settling threads, so keep its CLI, output shapes and refusals unchanged. Don't call a live T3 server: fake servers verify this work, and the steward runs a read-only `inspect` against the deployed T3 server after the merge.

## Work

Use one record-oriented submission path for saved IDs, acknowledgement writes, the accepted-but-missing refusal and final persistence. Keep operation-specific dispatch and output small and explicit. Check the V2 launch's initial message after dispatch as well as on resume.

## Acceptance

- Fake loss before and after acceptance keeps the IDs and never creates a second message; an acknowledged missing result never redispatches.
- A newly acknowledged launch whose thread is visible but whose first message is not reports incomplete visibility and keeps its record; once visible, resume finishes without replay.
- Archived launch recovery, private record handling and both successful CLI output shapes stay covered; the helper suite passes with networking disabled.

## Ground rules

- Behaviour stays the same unless the acceptance says otherwise. Write the pinning test first where the draft asks for one.
- Run at most one focused test command at a time, under your launch prompt's memory rule; no full browser suite.
- Keep private paths and host names out of committed docs and code. The check receipt (`*.evidence.json`) is machine evidence and exempt.
- Handoff: a short outcome; details go in this task record.

Tracker: [the skills-akaihola tracker][tracker].


## Outcome

Implemented F2 / D2 after the V2 transport prerequisite. One `submit()` path
now owns reconciliation by saved IDs, acknowledgement persistence, refusal to
replay acknowledged missing results, final record writes and output. A small
`submission_result()` observation helper keeps launch and send explicit.
Launch summaries still come from the shell; send summaries still come from
the thread snapshot. The CLI, saved command format, successful output fields
and order, archived recovery and existing refusal messages remain unchanged.

The intended correction is that a newly acknowledged launch must expose its
initial message as well as its thread before reporting success. It retains
its private acknowledged record when visibility is incomplete. Resume refuses
to dispatch while that acknowledged message is absent, then finishes without
replay once the exact saved message ID appears. See the [helper reference].

## Verification

- **Regression first:** added `test_newly_accepted_message_must_be_visible`
  for launch and send before changing production code. Launch failed with
  “DID NOT RAISE”; send passed. The test hides the accepted message while the
  thread stays visible, checks saved acknowledgement and private permissions,
  confirms missing-result resume leaves the record unchanged, then restores
  visibility and checks both successful output shapes and exactly one dispatch.
- **Loss recovery:** expanded `test_resume_unsubmitted_old_record` for both
  operations with loss before and after acceptance. Before acceptance, resume
  reuses the exact wire command; after acceptance it reconciles without another
  dispatch. Saved command, thread and message IDs remain unchanged, and a forced
  duplicate dispatch still creates only one message.
- **Helper suite:** 73 tests passed with networking disabled, including
  archived launch recovery, accepted-but-missing refusals, settings and target
  checks, private records and all five CLI actions. An intermediate run passed
  69 tests before adding the four extra loss cases. No live server was called.
- **Review:** inspected the complete implementation diff and existing recovery
  tests; no record-schema change, callback workflow, retry loop, persistent
  cache or unrelated fixture consolidation was introduced. Lint, formatting
  and whitespace checks passed. The steward owns the later read-only deployed
  server inspection; it is outside this fake-server acceptance scope.

Commands (one test command at a time):

```bash
# Pinning test before implementation: expected exit 1, launch fails.
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider t3-start-thread/tests -q -k newly_accepted_message
# Helper suite after implementation: exit 0.
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider t3-start-thread/tests -q
ruff check t3-start-thread/scripts/start_thread.py t3-start-thread/tests/test_start_thread.py
ruff format --check t3-start-thread/scripts/start_thread.py t3-start-thread/tests/test_start_thread.py
git diff --check
```

## Resource record

Every guarded command ran alone with a 300-second bound, memory/swap monitoring
and process-group cleanup. Measurements below describe resources and exit codes;
test results are recorded separately above.

- **Pinning test before implementation — started at once:** wait 0.00 s; admission
  MemAvailable 2494.0 MiB; final 2494.4 MiB; starting
  swap 2127.2 MiB; swap growth 0.5 MiB
  (peak 0.5 MiB); elapsed 6.38 s; exit 1.

- **Intermediate helper suite (69 tests) — started at once:** wait 0.00 s; admission
  MemAvailable 2319.1 MiB; final 2377.4 MiB; starting
  swap 2127.7 MiB; swap growth -3.5 MiB
  (peak 0.0 MiB); elapsed 3.21 s; exit 0.

- **Final helper suite (73 tests) — started at once:** wait 0.00 s; admission
  MemAvailable 2345.6 MiB; final 2420.2 MiB; starting
  swap 2122.2 MiB; swap growth 0.0 MiB
  (peak 0.0 MiB); elapsed 5.49 s; exit 0.

## Merge and recorded evidence

Fast-forwarded `main` from `564d595960de81d0dd99915acebdaece99e233b0` to
`b293300736421f230f0c2ee0c9c7c525f1d29cb7`. Delivery commits, oldest first:

- `b293300736421f230f0c2ee0c9c7c525f1d29cb7`

The task branch and worktree remain. The worktree is detached at that merged
commit for clean-checkout evidence recording; the shared checkout stays on
`main`. Both recorded checks passed (exit 0):

- **`helper-fake-suite`:** all 73 tests with networking disabled, including
  every recovery and output acceptance condition listed above.
- **`lint-format-whitespace`:** Ruff lint and format checks on the helper and
  tests, plus whitespace validation of the delivery commit.

The [machine receipt] contains exact check commands, tested commit and SHA-256
fingerprints for the helper, tests, reference and lint configuration. No lockfile
exists for this helper; the third-party test dependencies were pinned explicitly
in the offline command. No editable local package checkout is used.

- **Recorder `helper-fake-suite` — started at once:** wait 0.00 s; admission
  MemAvailable 2441.0 MiB; final 2507.3 MiB; starting
  swap 2127.7 MiB; swap growth 4.8 MiB
  (peak 4.8 MiB); elapsed 10.60 s; exit 0.

- **Recorder `lint-format-whitespace` — started at once:** wait 0.00 s; admission
  MemAvailable 2419.3 MiB; final 2388.9 MiB; starting
  swap 2132.5 MiB; swap growth 0.0 MiB
  (peak 0.0 MiB); elapsed 1.01 s; exit 0.

No acceptance condition remains unmet. Completion is recorded with `[ ]`;
user acceptance remains separate. No owner action is required.

[architecture-review]: ../reviews/2026-10-22-t3-start-thread-architecture-review.md#draft-issues
[tracker]: ../../TASKS.md
[helper reference]: ../../t3-start-thread/references/helper.md
[machine receipt]: 25-bring-the-t3-helper-s-launch-and-send-recovery-under-one-record-path.evidence.json
