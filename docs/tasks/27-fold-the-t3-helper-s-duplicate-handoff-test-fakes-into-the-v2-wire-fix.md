---
depends-on: [24, 25]
---

Steward issue, 2026-10-22 08:54 refill (steward decisions D53 and D95: simplification that keeps behaviour). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Estimated 45 min.

This is draft D4 of [the architecture review][architecture-review], filed as written there; read that draft and the finding it cites before starting. The review's line numbers refer to its baseline; recheck them on current `main`.

The helper is the steward's only route for follow-ups and settling threads, so keep its CLI, output shapes and refusals unchanged. Don't call a live T3 server: fake servers verify this work, and the steward runs a read-only `inspect` against the deployed T3 server after the merge.

## Work

Move the distinct assertions from the `LostReplyServer` and `MessageServer` tests into the existing V2 wire fixture and delete the duplicated classes and setup. Keep failure controls local to their scenarios; no fixture inheritance or general transport simulator. Skip whatever D1's migration already removed.

## Acceptance

- The change lists every migrated assertion; pre- and post-acceptance loss, exact message identity, settings rejection, workspace checks, private records and dry-run behaviour are still covered.
- No live V1 fake remains, and old-record-on-V2 tests still exist; the suite passes with networking disabled.

## Ground rules

- Behaviour stays the same unless the acceptance says otherwise. Write the pinning test first where the draft asks for one.
- Run at most one focused test command at a time, under your launch prompt's memory rule; no full browser suite.
- Keep private paths and host names out of committed docs and code. The check receipt (`*.evidence.json`) is machine evidence and exempt.
- Handoff: a short outcome; details go in this task record.

Tracker: [the skills-akaihola tracker][tracker].


## Assertion migration

Only [the helper tests][tests] change; production CLI, output and refusal
logic stay unchanged. The two direct fakes, their setup and unused imports
are deleted. The V2 wire fixture remains the only server implementation;
failure injection is local to each recovery scenario. No inheritance or
transport simulator was introduced. D4 asks for consolidation, not a new
behavior pinning test; D2's visibility pinning tests remain intact.

Every assertion from the removed tests maps as follows:

- **Lost launch reply:** `test_start_and_resume` still raises on transport
  loss after acceptance, resumes without a second dispatch, and returns an
  active thread. Added record mode `0600`, absence of a token, exact inherited
  settings (including model options) in both saved command and bootstrap,
  and `requireWorktree` for an isolated launch.
- **Explicit settings:** the same parent/settings and shared/worktree matrix
  verifies exact settings and root workspace strategy, plus absence of
  worktree preparation for a shared checkout.
  `test_settings_file_rejects_incomplete_settings` preserves rejection of
  incomplete settings with no launch, receipt or private request record.
- **Missing accepted launch:** `test_accepted_missing_result_is_not_resent`
  adds an absent-thread case alongside its existing absent-initial-message
  case. Neither dispatches again.
- **Send settings and identity:** `test_send_and_resume` retains an earlier
  message with identical text but a different ID. It checks exact submitted
  text, wire model selection through the fixture, all saved settings,
  private record mode and token exclusion, matching saved/wire/output message
  IDs, the persisted turn ID, delivered/active output, unchanged thread count,
  one newly persisted message and no prompt in output.
- **Dry run:** `test_send_dry_run` checks the dry-run flag and target ID,
  no dispatch or receipt, no request directory, no message and no prompt
  output.
- **Missing target:** the `missing` case in
  `test_send_rejects_invalid_target_or_prompt` retains the target refusal and
  no dispatch. All refusal cases also check no new thread, message or record.
- **Other project:** the `other-project` case retains workspace ownership
  rejection and no dispatch. The `workspace` case additionally rejects an
  unmatched workspace.
- **Empty prompt:** the `empty` case retains whitespace-only prompt rejection
  and no dispatch.
- **Lost send reply after acceptance:** `test_send_and_resume[after]`
  checks the timeout, a single dispatch and persisted new message, then
  successful acknowledgement recovery with no duplicate.
- **Loss before send acceptance:** `test_send_and_resume[before]`
  checks the timeout and two identical attempts using the saved command
  and message IDs, resulting in exactly one new message.
- **Removed accepted message:** `test_send_success_then_missing_message_is_not_resent`
  checks successful fresh-send output, then removes the persisted message.
  Resume refuses, leaves the acknowledged record unchanged and never resends.

Existing old-record-on-V2 coverage stays: start/send records, loss before and
after acceptance, identical saved IDs/settings, forced server deduplication,
partial launch visibility, acknowledged missing results and archived recovery.
The V2-only first-handshake and authentication refusal tests also remain.
D1 already removed live V1 protocol parametrization; no V1 fake remains.

## Validation

Focused helper commands run one at a time with networking disabled:

```bash
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider t3-start-thread/tests -q
ruff check t3-start-thread/tests/test_start_thread.py
ruff format --check t3-start-thread/tests/test_start_thread.py
git diff --check
```

The final combined suite passed **81 tests** after rebasing onto the shell-read
optimization. Ruff lint, formatting and whitespace checks passed. No live T3
server was contacted. The smaller count than the previous 83-test suite comes
from folding 11 direct-fake cases into nine additional wire cases; no
behavior assertion was dropped.

An intermediate run passed 71 tests before that dependency landed. The first migration run passed 69 and
failed one newly added, unsupported absent-send-thread scenario in the fixture.
That extra scenario was removed; the original absent-launch-thread and
absent-send-message assertions remain. The first run after rebasing passed 79 tests and failed two request-count
cases still using the removed global loss switch. Their injection is now
local to the scenario; the request-count assertions are unchanged.

Initial lint findings (statement count
and explicit encoding) were corrected before delivery.

## Resource record

Guarded commands use a 180-second runtime bound, process-group cleanup and
memory/swap monitoring.

- **Initial helper suite — started at once:** wait 0.0 s; admission
  MemAvailable 2936 MiB; final 2856 MiB; starting swap 2157 MiB;
  growth 0 MiB (peak 0); elapsed 4.1 s; exit 1.
- **Intermediate helper suite — started at once:** wait 0.0 s; admission
  MemAvailable 2670 MiB; final 2720 MiB; starting swap 2156 MiB;
  growth 0 MiB (peak 0); elapsed 2.9 s; exit 0.

- **First combined suite — started at once:** wait 0.0 s; admission
  MemAvailable 2913 MiB; final 2949 MiB; starting swap 2151 MiB;
  growth 0 MiB (peak 0); elapsed 3.8 s; exit 1.
- **Final combined suite — started at once:** wait 0.0 s; admission
  MemAvailable 2974 MiB; final 2975 MiB; starting swap 2152 MiB;
  growth 0 MiB (peak 0); elapsed 4.3 s; exit 0.

## Merge and evidence

Fast-forwarded `main` from `d54154faf05ba2a16b984aca58bf100162f1c6a6` to
`12d5a78703648a38836a8f5303bdf3c0ac989ed6`. Delivery commits, oldest first:

- `12d5a78703648a38836a8f5303bdf3c0ac989ed6`

The task worktree remains detached at the merged commit for clean-checkout
recording; its branch is retained. The shared checkout remains on `main`.

Both checks were recorded against that clean commit and passed (exit 0):

- **`helper-fake-suite`:** all 81 helper tests with networking disabled.
- **`lint-format-whitespace`:** Ruff lint and formatting, plus whitespace
  validation of the complete delivery diff.

The [machine receipt] records exact commands, commit identity and SHA-256
fingerprints of the helper, tests, reference and lint configuration.
This helper has no lockfile; its offline test dependencies were explicitly
pinned in the command. No editable local checkout is used.

- **Recorder `helper-fake-suite` — started at once:** wait 0.0 s; admission
  MemAvailable 2955 MiB; final 2843 MiB; starting swap 2171 MiB;
  growth 0 MiB (peak 0); elapsed 6.1 s; exit 0.
- **Recorder `lint-format-whitespace` — started at once:** wait 0.0 s; admission
  MemAvailable 2877 MiB; final 2863 MiB; starting swap 2171 MiB;
  growth 0 MiB (peak 0); elapsed 0.6 s; exit 0.

No acceptance conditions remain unmet. Completion is recorded unchecked;
user acceptance stays separate. The steward owns the later deployed-server
read-only inspection. No owner action is required.

[architecture-review]: ../reviews/2026-10-22-t3-start-thread-architecture-review.md#draft-issues
[tracker]: ../../TASKS.md
[tests]: ../../t3-start-thread/tests/test_start_thread.py
[machine receipt]: 27-fold-the-t3-helper-s-duplicate-handoff-test-fakes-into-the-v2-wire-fix.evidence.json
