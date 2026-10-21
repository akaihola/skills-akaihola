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
approvals or input, and background tasks on either protocol. A parked paced
run alone is not active. Choose the intended parent thread using conversation
context, rather than assuming the newest thread is the current one.
`CODEX_THREAD_ID` is the provider's session ID, not necessarily T3's thread ID.

The default server is `http://127.0.0.1:3773`. Use `--url` for another server.
For a local server, the helper captures `t3 auth session issue --ttl 5m
--token-only` without printing the token. Set `--base-dir` when the CLI's state
directory differs from the server's. For a remote server, supply an existing
bearer session through `T3_THREAD_AUTH_TOKEN`; do not mint credentials from an
unrelated local server. Tokens stay in memory.

## Settle threads

Use the thread IDs from `inspect`, which includes each thread's `settledAt`:

```bash
uv run scripts/start_thread.py settle --url http://127.0.0.1:3773 \
  --thread T3_THREAD_ID --thread ANOTHER_THREAD_ID --dry-run
```

Remove `--dry-run` to dispatch `thread.settle` on either protocol. No workspace
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
mode. It submits a normal user message using V1 `thread.turn.start` or V2
`message.dispatch`. V2 queues the message after any active run. This does not
create a thread or worktree. The helper detects the protocol from the WebSocket handshake,
without relying on the server's version string.

Use `--dry-run` to verify authentication, the target, and its settings without
sending a message or writing a request record. It does not print the prompt.
Capability checks do not require sending a live test message.

Send messages or coordination the user requested. For shared resources such
as a browser, ask the other thread to acknowledge a handoff before using the
resource. An idle thread and a lock used by only one participant do not
establish exclusive access.

Successful output includes `delivered: true` after finding the exact message
ID in the target's thread snapshot. This verifies persistence, not that the
other agent has acted on the message. Report the message's turn ID, or V2 run
ID in `messageTurnId`, and observed state when available. Wait for the requested
acknowledgement when needed.

## Route review findings back to the implementer

When a review or acceptance check finds changes needed in work a known ordinary
thread implemented, send the findings to that thread as a paced follow-up.
Include the original issue, evidence (files, failing checks or reproduction),
the changes needed and what "done" means. End the private prompt with `...`
so the pacing hook parks it until admission. Do not hand the findings to the
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

When no parent thread fits, pass `--settings FILE` instead of
`--parent-thread`. The file is a JSON object holding exactly `modelSelection`,
`runtimeMode` and `interactionMode`, in the shape `inspect` prints. Use it for
an explicitly requested model and for scheduled jobs, since archived threads
drop out of the snapshot and can no longer serve as parents. Never change the
settings silently.

On a server with the pacing hook, a prompt ending in `...` or `…`, ignoring
trailing whitespace, parks until the pacer admits it. This applies to both
initial prompts and follow-ups. Delivery confirms persistence even when the
run is parked; it does not mean the agent is running.

## Verify and handle interrupted requests

Before sending a command, the helper saves its thread ID, command ID, message
ID, prompt, and connection details under `~/.local/state/t3-start-thread/`, with
private permissions. Its output includes the record path. If a request loses
its reply, resume that record rather than running `start` or `send` again:

```bash
uv run scripts/start_thread.py resume /path/to/request.json
```

For thread creation, resume checks the saved thread ID and, on V2, the initial
message ID so a partially accepted launch can finish. For existing-thread
messaging, it checks the saved message ID, since the thread already exists.
If the result is visible, it reports it without submitting another turn.
Otherwise it resends the same command ID, preserving server deduplication.
Existing V1 records remain resumable after a V2 upgrade. Records keep their
original IDs and request format; the helper translates requests at dispatch.
An acknowledged command with a missing result stops for inspection. Stop and
inspect a failed turn or schema error; do not create fresh requests as retries.

Report the title, branch/worktree, and observed turn state. Claim the task is
running only when the server reports a running turn, active session, or V2
running run. Check
the new thread's UI if it needs an approval or user answer.

The helper supports V1 and V2 orchestration. V1 uses turn bootstrap commands;
V2 uses `orchestration.launchThread` for creation and `message.dispatch` for
follow-ups. If the API changes, inspect the running version's contracts before
modifying the request. Relevant V1 source:
[thread commands],
[authentication],
and [WebSocket server].

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
[thread commands]: https://github.com/pingdotgg/t3code/blob/v0.0.44/packages/contracts/src/orchestration.ts
[authentication]: https://github.com/pingdotgg/t3code/blob/v0.0.44/apps/server/src/cli/auth.ts
[WebSocket server]: https://github.com/pingdotgg/t3code/blob/v0.0.44/apps/server/src/ws.ts
[rewind documentation]: https://github.com/pingdotgg/t3code/blob/v0.0.44/docs/user/composer.md
