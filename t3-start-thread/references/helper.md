# Ordinary T3 thread helper

Implementation: [t3-start-thread/scripts/start_thread.py].

## Inspect the project

Run commands in Bash. Examples below assume the skill directory as the working
directory; otherwise substitute the absolute helper path.

```bash
uv run scripts/start_thread.py inspect --workspace /path/to/repository
```

This prints matching project metadata and recent thread IDs, titles, and model
settings. Each thread includes an `active` boolean for running work, pending
approvals or input, and background tasks. A parked paced run alone is not
active. Choose the intended parent thread using conversation
context, rather than assuming the newest thread is the current one.
`CODEX_THREAD_ID` is the provider's session ID, not necessarily T3's thread ID.

## Thread links across clients

Use `t3-thread://v1/<exact-thread-id>` and prefer the destination's current
`title` from `t3_thread_read` as the authored Markdown label. A self-link may
leave the current screen unchanged; test a link to a different existing
conversation before diagnosing failed navigation.

Observed 2026-11-06: the user reported that Desktop displayed the linked
thread's current title while Android retained the authored label. The native
read tool confirmed the current title; the user confirmed Android navigation
to that thread and return with Back. This was a user-run UI check, not an
agent-driven Android reproduction. Client versions and other environments
were not tested. A label difference alone does not establish a broken link.

## Server discovery and authentication

Without `--url`, the helper reads `origin` from the selected base directory's
runtime file. The default base and file are:

```text
~/.t3/userdata/server-runtime.json
```

If discovery finds no origin, the helper falls back to
`http://127.0.0.1:3773`. `--url` overrides discovery. `--base-dir` selects both
the runtime-file base and the local authentication CLI's state directory;
choose the base used by the intended server.

`T3_THREAD_AUTH_TOKEN`, when set, supplies an existing bearer session. Otherwise
the helper captures `t3 auth session issue --ttl 5m --label "T3 thread handoff"
--token-only` without printing the token, but only for loopback or the recorded
runtime origin (matching scheme, hostname and effective port). Other origins
require `T3_THREAD_AUTH_TOKEN`; do not mint credentials from an unrelated local
server. Tokens stay in memory.

## Settle threads

Use the thread IDs from `inspect`, which includes each thread's `settledAt`:

```bash
uv run scripts/start_thread.py settle --url http://127.0.0.1:3773 \
  --thread T3_THREAD_ID --thread ANOTHER_THREAD_ID --dry-run
```

Remove `--dry-run` to dispatch `thread.settle`. No workspace
argument is needed. Each target gets one JSON line with `threadId`, `dryRun`
and `status`: `settled`, `already-settled`, `refused` with a `reason`, or `error`
with the server's rejection. In a dry-run, `settled` means it would be settled.
Archived, active and pending-input or pending-approval threads are refused
before dispatch. A refusal or error makes the exit status nonzero, while the
remaining targets are still checked. Already-settled threads retain their
original timestamp. New activity un-settles a thread.

Settle only threads the user has authorized. This command sends no user message
and creates no request record; after an interrupted invocation, inspect the
targets before retrying.

## Webhook-triggered turns

The T3 server checkout inspected on 2026-11-06 logs webhook request bodies
(up to 64 KiB) and rendered prompts. It rejects a filled-in prompt over
120,000 characters without starting a provider turn. This follows
`apps/server/src/scheduledTasks/ScheduledTaskService.ts` and
`packages/contracts/src/chatAttachment.ts` in that checkout; deployed versions
may differ. Bound output and avoid sending secrets. Check the delivery outcome:
acceptance of a request alone does not prove an agent turn started. End-to-end
SSH-output delivery through a webhook was not tested.

## Message an existing thread

Use `inspect` to identify the requested thread and its project. For a specific
thread ID, `send` checks all unarchived threads, including ones outside `inspect`'s
ten most recent results. Write the requested message to a private prompt file
outside the repository, then run:

```bash
uv run scripts/start_thread.py send \
  --workspace /path/to/repository \
  --thread T3_THREAD_ID \
  --prompt-file /path/to/private-message.txt
```

The helper preserves the target's model options, runtime mode, and interaction
mode. It submits a normal user message with V2 `message.dispatch`, which queues
the message after any active run. This does not create a thread or worktree.

Use `--dry-run` to verify authentication, the target, and its settings without
sending a message or writing a request record. It does not print the prompt.
Capability checks do not require sending a live test message.

Send messages or coordination the user requested. For shared resources such
as a browser, ask the other thread to acknowledge a handoff before using the
resource. An idle thread and a lock used by only one participant do not
establish exclusive access.

Successful output includes `delivered: true` after finding the exact message
ID in the target's thread snapshot. This verifies persistence, not that the
other agent has acted on the message. Report the message's run ID, which the
output keeps in `messageTurnId`, and observed state when available. Wait for the requested
acknowledgement when needed.

## Update an already running turn

Verified 2026-11-06: native `t3_thread_send` with `mode: "steer"` delivered
an internal implementation handoff to an already running writer. The response
reported `delivery: "steered"` with the same active `runId`; a subsequent
`t3_thread_read` showed the persisted message and the writer acting on it
within that run. No new turn was launched. This is an in-flight update, not
pacer admission for a new follow-up. Check that the intended turn is active
first, verify the returned delivery and run ID, and use the helper below for
a separate follow-up turn. Idle or paused targets were not tested.

## Paced follow-ups

Follow the [ordinary-thread routing decision](../SKILL.md#ordinary-thread-operations) even when a native send tool is
exposed. On the integration inspected on 2026-10-26, native `t3_thread_send`
with `mode=queue` and a trailing `...` started an idle target while its provider
was paused by the pacer. That queue mode waits behind active work; it does not
by itself wait for pacer admission.

The installed native service calls `ThreadManagementService.sendToThread` with
`createdBy: "agent"` and, for a thread-scoped caller, `senderThreadId`. This
integration's pacing hook requires `createdBy: "user"` and no sender-thread
ID. The helper's `send` translates its saved request to V2 `message.dispatch`
with `createdBy: "user"`, `creationSource: "mcp"`, no `senderThreadId`, and
the original message text. Both paths use `queue_after_active`; their message
attribution differs. This limitation is specific to the inspected integration,
not a claim about every native tool or future version.

End the private prompt with `...` or `…` (trailing whitespace is allowed).
Use the helper's `send --dry-run` to check the target and settings, then send
the authorized follow-up. `delivered: true` verifies message persistence.
Use `t3_thread_read` or the server's run record to check the returned
`messageTurnId`: `status: "queued"` and `startedAt: null` show it has not
started. Where exposed, `pacing: "held"`
or `"waiting"` identifies the pacer wait; a queued status alone can also mean
waiting behind active work. Report the observed state without treating delivery
as admission. Use existing records and local code for capability verification;
a live probe is unnecessary. Recover interrupted sends with `resume` below.

## Route review findings back to the implementer

When a review or acceptance check finds changes needed in work a known ordinary
thread implemented, send the findings to that thread as a paced follow-up.
Include the original issue, evidence (files, failing checks or reproduction),
the changes needed and what "done" means. Follow [paced follow-ups](#paced-follow-ups) for the
send path, trailing marker and delivery checks. Do not hand the findings to the
user to relay. Preserve any explicit restriction on messaging.

For paced work, resolve the implementing thread from its canonical tracker
and issue number:

```bash
uv run scripts/start_thread.py send \
  --tracker /path/to/repository/TASKS.md --issue 14 \
  --prompt-file /path/to/private-review.txt --dry-run
```

This requires `hai-tasks` on PATH. It reads Hai's `sourceReference` to find the
stable issue ID, then matches `tracker` and `issue` in the local launch records
under `~/.local/state/kandev-pacer/t3/`. The workspace defaults to the tracker's
directory; pass `--workspace` if its T3 project root differs. Server and
authentication options are the same as for explicit thread IDs. The live
snapshot must still contain the target in the selected project. Missing,
archived or ambiguous targets are refused; dry-run sends nothing.

After checking the dry-run, remove `--dry-run` to send the paced follow-up.
If the implementing thread is gone or archived, or no launch record identifies
it, file a follow-up issue in the same tracker with the evidence and completion
criteria. Check for duplicates and follow that tracker's ordering rules. An
authentication or connection failure does not establish that a thread is gone.

The steward includes these routing instructions in review issues it files:
send actionable findings to the implementing thread as paced follow-ups; file
follow-up issues in the same tracker when that thread is unavailable. Record
the destination and delivery evidence in the review result.

## Start an explicitly requested ordinary thread

Write a private prompt file outside the repository. Include the user's goal,
relevant files and decisions, useful verification results, and the permitted
scope of work. Preserve existing constraints on deployment, publishing, and
messaging. Keep unrelated conversation content out of the handoff.

```bash
uv run scripts/start_thread.py start \
  --workspace /path/to/repository \
  --parent-thread T3_THREAD_ID \
  --title "Implement the requested change" \
  --prompt-file /path/to/private-prompt.txt \
  --base-branch main \
  --branch implement-requested-change
```

The helper copies the selected parent's model options, runtime mode, and
interaction mode. It asks T3 to prepare a separate worktree. Omit `--branch` to
generate a unique branch name. `--base-branch` defaults to the repository's
current branch. The parent must belong to the selected project.

For an explicitly requested shared checkout, pass `--shared-checkout` and omit
both `--branch` and `--base-branch`; this does not switch the checkout's branch.

`start` requires exactly one of `--parent-thread` or `--settings FILE`.
When no parent fits, or to override settings, use the file: copy all three
fields from `inspect` and edit the required options. Settings replace rather
than merge. The file is a JSON object holding exactly `modelSelection`,
`runtimeMode` and `interactionMode`, in the shape `inspect` prints. Use it for
an explicitly requested model and for scheduled jobs, since archived threads
drop out of the snapshot and can no longer serve as parents. Never change the
settings silently.

On a server with the pacing hook, a helper initial prompt ending in `...` or
`…`, ignoring trailing whitespace, parks until the pacer admits it. Delivery
confirms persistence even when the run is parked; it does not mean the agent
is running. For follow-ups, use [paced follow-ups](#paced-follow-ups).

## Verify and handle interrupted requests

Before sending a command, the helper saves its thread ID, command ID, message
ID, prompt, and connection details under `~/.local/state/t3-start-thread/`, with
private permissions. Its output includes the record path. If a request loses
its reply, resume that record rather than running `start` or `send` again:

```bash
uv run scripts/start_thread.py resume /path/to/request.json
```

For thread creation, resume checks the saved thread ID and the initial message
ID so a partially accepted launch can finish. For existing-thread messaging, it
checks the saved message ID, since the thread already exists. If the result is
visible, it reports it without submitting another turn. Otherwise it resends
the same command ID, preserving server deduplication. An acknowledged command
with a missing result stops for inspection. Immediately after dispatch, a launch
also requires both its thread and initial message to be visible. Incomplete
visibility retains the acknowledged record and exits 1; resume does
not replay an acknowledged command while waiting for its result to appear.
Stop and inspect a failed run or schema error; do not create fresh requests
as retries.

The CLI hides most exception details to avoid exposing credentials, printing
`Error: <ExceptionType>. Inspect the request record and server state before
retrying.` Inspect the saved `accepted` flag and acknowledgement instead of
expecting a detailed missing-result message on stderr.

Report the title, branch/worktree, and observed run state. Claim the task is
running only when the server reports a running run. Check the new thread's UI
if it needs an approval or user answer.

## Server and record compatibility

The helper speaks only T3's V2 orchestration protocol. Every WebSocket
connection asks for V2 with a fresh single-use ticket. A refused ticket or
rejected upgrade fails the command without a retry or V1 fallback, so a V1-only
server is not supported. V2 uses `orchestration.launchThread` for creation and
`message.dispatch` for follow-ups.

Request records are a separate matter. New and older records alike keep the
V1-era request format: a `thread.turn.start` command with its thread, command
and message IDs, plus a `bootstrap` for thread creation. The helper translates
the record to V2 at dispatch without rewriting it, so a record saved before the
V2 upgrade still resumes against a V2 server with its original IDs.

If the API changes, inspect the running version's contracts before modifying
the request. Relevant source: the V2 [orchestration contracts] and
[WebSocket server]; the V1 [thread commands] that define the saved record
format; and ticket [authentication], which V2 did not change.

## Forking an existing conversation

The historical V1 probe found that `thread.fork` fails validation because it is absent from
the accepted client commands. The probe used synthetic IDs and verified that
the server's thread IDs were unchanged. That version’s contracts expose conversation rewind, but no command for cloning
a thread with its provider history. This is not a current-server capability check;
consult live capabilities before making a claim about a newer server.

Starting a new thread with a summary is a handoff, not a history-preserving
fork. **Edit from here** changes the original conversation. Do not use it when
the user wants to preserve both branches. See the upstream
[rewind documentation].

[t3-start-thread/scripts/start_thread.py]: ../scripts/start_thread.py
[orchestration contracts]: https://github.com/pingdotgg/t3code/blob/v0.1.1-nightly.20261017.3238/packages/contracts/src/orchestrationV2.ts
[WebSocket server]: https://github.com/pingdotgg/t3code/blob/v0.1.1-nightly.20261017.3238/apps/server/src/ws.ts
[thread commands]: https://github.com/pingdotgg/t3code/blob/v0.0.44/packages/contracts/src/orchestration.ts
[authentication]: https://github.com/pingdotgg/t3code/blob/v0.0.44/apps/server/src/cli/auth.ts
[rewind documentation]: https://github.com/pingdotgg/t3code/blob/v0.0.44/docs/user/composer.md
