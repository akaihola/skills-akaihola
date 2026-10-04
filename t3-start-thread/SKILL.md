---
name: t3-start-thread
description: Start a separate T3 Code thread with a task handoff, optionally inheriting an existing thread's model settings and preparing an isolated Git worktree. Use when the user asks to start another T3 Code thread or delegate work to a new T3 thread.
---

# Start a T3 Code thread

Create the thread in the requested T3 project, submit the task, and verify its
state. A Codex subagent is not a T3 Code thread.

Prefer a native T3 thread-creation tool if one is exposed. Otherwise use the
helper below. It uses the running server's authenticated WebSocket API and also
works when the collaborative browser is unavailable on a headless server.

## Inspect the project

Run commands in Bash. Resolve the helper relative to this skill directory.

```bash
uv run scripts/start_thread.py inspect --workspace /path/to/repository
```

This prints matching project metadata and recent thread IDs, titles, and model
settings. Choose the intended parent thread using conversation context, rather
than assuming the newest thread is the current one. `CODEX_THREAD_ID` is the
provider's session ID, not necessarily T3's thread ID.

The default server is `http://127.0.0.1:3773`. Use `--url` for another server.
For a local server, the helper captures `t3 auth session issue --ttl 5m
--token-only` without printing the token. Set `--base-dir` when the CLI's state
directory differs from the server's. For a remote server, supply an existing
bearer session through `T3_THREAD_AUTH_TOKEN`; do not mint credentials from an
unrelated local server. Tokens stay in memory.

## Hand off the task

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

For an explicitly requested shared checkout, pass `--shared-checkout` instead
of `--branch`; this does not switch the checkout's branch. For a model change,
use the native tool or adapt the request to the running server's current schema
instead of silently changing the inherited settings.

## Verify and handle interrupted requests

Before sending a command, the helper saves its thread ID, command ID, prompt,
and connection details under `~/.local/state/t3-start-thread/`, with private
permissions. Its output includes the record path. If a request loses its reply,
resume that record rather than running `start` again:

```bash
uv run scripts/start_thread.py resume /path/to/request.json
```

Resume first queries the server for the saved thread ID. If it exists, it
reports its state without submitting another turn. Otherwise it resends the
same command ID, preserving the server's deduplication behavior. Stop and
inspect a failed turn or schema error; do not create fresh threads as retries.

Report the title, branch/worktree, and observed turn state. Claim the task is
running only when the server reports a running turn or active session. Check
the new thread's UI if it needs an approval or user answer.

The helper was exercised against T3 Code 0.0.44. If the API changes, inspect
the running version's contracts before modifying the request. Relevant source:
[thread commands](https://github.com/pingdotgg/t3code/blob/v0.0.44/packages/contracts/src/orchestration.ts),
[authentication](https://github.com/pingdotgg/t3code/blob/v0.0.44/apps/server/src/cli/auth.ts),
and [WebSocket server](https://github.com/pingdotgg/t3code/blob/v0.0.44/apps/server/src/ws.ts).

## Forking an existing conversation

On the tested server, `thread.fork` fails validation because it is absent from
the accepted client commands. The probe used synthetic IDs and verified that
the server's thread IDs were unchanged. The contracts expose conversation
rewind, but no command for cloning a thread with its provider history.

Starting a new thread with a summary is a handoff, not a history-preserving
fork. **Edit from here** changes the original conversation. Do not use it when
the user wants to preserve both branches. See the upstream
[rewind documentation](https://github.com/pingdotgg/t3code/blob/v0.0.44/docs/user/composer.md).
