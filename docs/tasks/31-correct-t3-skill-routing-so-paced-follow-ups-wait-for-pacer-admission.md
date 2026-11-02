Tracker: [the skill tracker]. Correct the ordinary-thread routing instructions so a requested paced follow-up waits for the pacer even when the native MCP send tool is exposed. This fixes a demonstrated instruction gap and prevents unexpected subscription use; it does not change T3 or the pacer.

## Evidence and scope

On October 26, a follow-up ending in the literal `...` was sent with native `t3_thread_send`, `mode=queue`. The idle target started at 14:18:22 UTC, while its provider was paused by the pacer. The steward interrupted it at 14:18:51. Sending a continuation through the existing WebSocket helper at 14:19:18 produced a durable queued run with no start time and preserved the target model options. The [run record] preserves the private delivery evidence; do not copy actual messages, identities or authentication into this repository.

The [routing skill] currently says to prefer a native tool for ordinary-thread operations. Its [helper reference] separately says the trailing marker parks messages. That combination caused the native choice. Inspect the installed T3 native-send implementation and the helper's command translation to establish the route difference before documenting it. The native service delegates to ThreadManagementService.sendToThread; its queue-after-active mode is not proof of pacer admission when no run is active. Do not infer that all native tools or future versions behave the same.

## Work

- Add the smallest explicit exception at the routing decision: for paced follow-ups on this integration, use the helper's send path unless the native tool has an explicit, verified way to preserve pacer admission. Keep the default native preference for operations that are not affected. Do not create another transport or change launch/delegation behavior.
- Explain the observed limitation and how to verify persistence versus admission: a message can be delivered while the run remains queued with no start time. `mode=queue` and a trailing marker alone did not keep the native request parked here. Preserve existing dry-run, target-resolution, model-setting and request-recovery guidance.
- Verify this conclusion from local code and existing fixtures. If the helper already preserves the required dispatch shape and marker, leave its implementation alone. Add or adjust a focused regression only if there is a real untested behavioral boundary; no test that merely matches documentation text. Never send a live probe, restart a service, or change an existing conversation to test this task.
- Use the writing-for-agents and skill-creator workflows for the skill edit. Keep progressive disclosure and exact copyable commands. Examples must be synthetic and portable; no actual prompt text or account details.

## Acceptance

The routing decision and helper reference agree on how paced follow-ups reach admission. The evidence distinguishes the native queue mode from pacer parking and scopes the limitation to the observed integration. Existing ordinary messaging, delegation, settlement, model preferences, dry runs and idempotent recovery keep their documented behavior. Run the relevant existing helper and skill validation, inspect the final diff for private data, and record literal delivery commits and a passing check receipt. No live send or configuration change is needed for completion.

Expected focused effort about 30 minutes. Keep the final handoff brief; no owner action is expected. Do not push, deploy, send messages, add new infrastructure or change pacer settings.

## Implementation and local evidence

The [routing skill] now makes paced follow-ups an explicit exception to the
native-tool preference. Its [helper reference] keeps the observed limitation,
message attribution, marker, persistence and admission checks together.
Ordinary messaging, launch/delegation, settlement, target lookup, model
preferences, dry runs and recovery retain their existing instructions.

Applied [writing-for-agents] and the installed skill-creator workflow:
keep the decision at the routing point, disclose the send-specific explanation,
preserve invocation metadata and copyable commands, and validate the skill.

Inspected the installed server bundle, not just the upstream checkout:

```text
/nix/store/br62y8qdd3r0wzgmaw8ys419x80xhzkp-t3code-0.1.0/libexec/t3code/apps/server/dist/binCli-D845Gj8J.mjs
sha256: 1844e2071fe23af92b1a34e6be6e3b15cfc0b4eaf71fd4703fb470c6ceab0e48
```

- **Native send (lines 322927–322956, 282814–282847):** the MCP service
  passes agent attribution and, when thread-scoped, a sender-thread ID to
  `ThreadManagementService.sendToThread`. Queue mode becomes
  `queue_after_active` without changing those fields.
- **Pacing (lines 274678–274690, 277795–277805):** the marker matcher accepts
  three periods or the ellipsis character plus trailing whitespace. Eligibility
  requires user attribution and no sender-thread ID. The queue branch accepts
  paced requests even without an active run.
- **Parking (lines 277869–277887):** the eligible idle request gets a queued
  run, a pacing hold and `startedAt: null`. Delivery and execution are separate.
- **Helper:** [dispatch translation] retains the original text and model
  selection, sends user/MCP attribution and omits the sender-thread ID. Its
  implementation needed no changes.
- **Regression:** extended [send/resume tests] across ordinary text, both
  markers and trailing whitespace, with reply loss before/after acceptance.
  Existing wire assertions cover attribution, queue mode and model selection;
  the regression also checks absence of sender-thread attribution, exact text,
  original IDs and one durable dispatch. These offline fixtures verify the
  helper boundary; the installed source establishes pacing semantics.

No live send, authentication probe, conversation mutation, service restart,
pacer configuration change, push or deployment was used. The diff was reviewed
for private data; only synthetic fixture text was added.

## Validation before merge

The focused helper and metadata suite passed: **115 tests**. The repository
validator passed all **48 skill frontmatters**; skill-creator validation,
**six offline help checks**, Ruff and `git diff --check` passed. Edit-time lint
caught argument-count and line-length issues; both were corrected before this
passing run. Local Markdown targets and the new heading links were reviewed.
Hai read the whole canonical tracker: unique stable IDs, resolved detail
links, and this issue In Progress after the immediate start commit.

Commands (also declared in the final receipt):

- **regressions:**

  ```bash
  PYTHONPATH= PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 unshare -rn uv run --offline --no-project --with-requirements /home/agent/.local/state/kandev-pacer/t3/evidence/hai31-checks/requirements.lock pytest -p no:cacheprovider t3-start-thread/tests tests/test_skill_metadata.py -q
  ```

- **skill-validation:**

  ```bash
  PYTHONPATH= PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 unshare -rn uv run --offline --no-project --with-requirements /home/agent/.local/state/kandev-pacer/t3/evidence/hai31-checks/requirements.lock bash -e -c 'python scripts/check_skill_metadata.py
  python /home/agent/.local/state/kandev-pacer/t3/evidence/hai31-checks/quick_validate.py t3-start-thread'
  ```

- **helper-help:**

  ```bash
  PYTHONPATH= PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 unshare -rn uv run --offline --no-project --with-requirements /home/agent/.local/state/kandev-pacer/t3/evidence/hai31-checks/requirements.lock bash -e -c 'python t3-start-thread/scripts/start_thread.py --help >/dev/null
  for action in inspect start send settle resume; do
    python t3-start-thread/scripts/start_thread.py "$action" --help >/dev/null
  done
  printf "%s\n" "Six offline help checks passed"'
  ```

- **python-lint:**

  ```bash
  /nix/store/n67r0lpnvh89s3mbgnys5fcrl131prrf-ruff-0.16.8/bin/ruff check t3-start-thread/tests/test_start_thread.py
  ```

## Memory reports before merge

All commands ran sequentially with a 300-second timeout, process-group cleanup,
2 GiB admission, and monitoring for memory below 1 GiB or swap growth above
512 MiB. Readings are MiB; wait and elapsed values are seconds.

| Command ID | Outcome | Wait | Admission | Final | Swap start | Swap growth | Elapsed | Exit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| premerge-regressions | started at once | 0.0 | 57498 | 57451 | 1 | 0 | 1.2 | 0 |
| premerge-skill-validation | started at once | 0.0 | 57516 | 57496 | 1 | 0 | 0.2 | 0 |
| premerge-helper-help | started at once | 0.0 | 57496 | 57435 | 1 | 0 | 0.6 | 0 |
| premerge-python-lint | started at once | 0.0 | 57435 | 57442 | 1 | 0 | 0.2 | 0 |

## Merge and recorded acceptance checks

Base commit: `945a4195a22e7e5e9121cc5a794616f8b6d33c76`. Delivery commits, oldest first:

- `db3983b059673a252e9df1ce122bc1f15d3e682d`

Fast-forward merged locally to `main`. The task worktree is clean and detached
at `db3983b059673a252e9df1ce122bc1f15d3e682d`; the task branch remains available.
No push or deployment occurred.

The [check receipt] records six passing checks at that exact merged commit:

- **regressions:** 115 passed in 0.79 seconds.
- **skill-validation:** all 48 skill frontmatters and skill-creator validation passed.
- **helper-help:** six offline parser/help checks passed.
- **python-lint:** Ruff passed.
- **installed-route-inspection:** pinned installed-source and helper excerpts
  match the attribution and queue analysis above. This is source inspection,
  not a live admission test.
- **delivery-scope:** literal base/delivery comparison and whitespace checks
  passed; only the routing skill, helper reference, regression and this task
  record changed. The helper implementation is identical to the base.

The receipt declares the pinned requirements lock by SHA-256, plus the copied
skill validator, installed Ruff and installed server bundle where used. There
are no editable dependency checkouts. Scope checks use literal commit hashes,
so later completion metadata is outside their comparison. Final diff review
found no added identities, message content or credentials.

## Memory reports for evidence recording

Each record command used the same guard and timeout as the pre-merge checks:

```bash
for check in regressions skill-validation helper-help python-lint installed-route-inspection delivery-scope; do
  uv run /home/agent/my-knowledge/agents/steward/scripts/check-evidence.py record /home/agent/.local/state/kandev-pacer/t3/evidence/fcb6d0aab0322152788b7c6c5df8974185cf26bf1e14d2f4fd676e9bba7876aa.evidence.json 'skills-akaihola [31]' "$check"
done
```

Readings are MiB; wait and elapsed values are seconds. Each row names its
individual record invocation above.

| Command ID | Outcome | Wait | Admission | Final | Swap start | Swap growth | Elapsed | Exit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| record-regressions | started at once | 0.0 | 57500 | 57504 | 1 | 0 | 1.2 | 0 |
| record-skill-validation | started at once | 0.0 | 57504 | 57480 | 1 | 0 | 0.2 | 0 |
| record-helper-help | started at once | 0.0 | 57480 | 57439 | 1 | 0 | 0.6 | 0 |
| record-python-lint | started at once | 0.0 | 57439 | 57431 | 1 | 0 | 0.2 | 0 |
| record-installed-route-inspection | started at once | 0.0 | 57431 | 57436 | 1 | 0 | 0.2 | 0 |
| record-delivery-scope | started at once | 0.0 | 57436 | 57448 | 1 | 0 | 0.2 | 0 |

No failed, skipped or stopped acceptance checks; no agent-owned follow-up remains.
Completion is recorded pending user acceptance; the acceptance box stays unchecked.

[the skill tracker]: ../../TASKS.md
[routing skill]: ../../t3-start-thread/SKILL.md
[helper reference]: ../../t3-start-thread/references/helper.md
[run record]: http://tinni/my-knowledge/agents/steward/log/2026-10-26.md?f#1613-refill-pacer-wake-up
[writing-for-agents]: https://github.com/mattpocock/skills/blob/main/skills/productivity/writing-for-agents/SKILL.md
[dispatch translation]: ../../t3-start-thread/scripts/start_thread.py
[send/resume tests]: ../../t3-start-thread/tests/test_start_thread.py
[check receipt]: 31-correct-t3-skill-routing-so-paced-follow-ups-wait-for-pacer-admission.evidence.json
