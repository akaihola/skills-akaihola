---
name: t3-start-thread
description: Route requested T3 Code coordination to child-task delegation, an explicitly requested new conversation, or messaging and settling existing threads, including when native tools are not initially exposed.
---

# Coordinate T3 Code tasks and threads

## Apply model-setting preferences

Before creating a thread or delegating a task, read the available user-preference
instructions for T3 model settings, when present. Explicit user
preferences override inherited and catalog-default reasoning and service-tier
options. Pass the resolved options explicitly and verify the created thread's
saved configuration. For helper settings and overrides, follow the
[start reference](references/helper.md#start-an-explicitly-requested-ordinary-thread).

## Choose the operation first

Decide from the user's intent before choosing a tool or helper command:

- A subagent, delegated review, or parallel child task belongs to the current
  thread. Follow **Delegate a child task** below.
- An explicitly requested separate/new/top-level thread or conversation uses
  `t3_thread_launch` or `create_threads`, or the helper's `start` command.
- A follow-up to an existing ordinary thread uses `t3_thread_send`, or the
  helper's `send` command. Settling uses the native settle tool or `settle`.

"Delegate this review to a subagent" does not authorize a top-level launch.
If "hand this off" leaves the intended kind of coordination unclear, ask
whether the user wants a child task or a separate conversation.

## Preserve the main task identity

When the current task prompt begins with `Task thread identity: {…}`, copy that
entire JSON line unchanged as the first line of every related child task, fork,
or independently launched thread's initial prompt. This applies to native tools,
the ACP transport and the helper, including cross-project work. Keep the original
canonical tracker, stable issue ID, task reference, main thread ID and server;
never replace the main ID with a supporting thread's ID. Record returned task and
thread IDs in the task record. A reference number alone is project-local and does
not identify a related thread in another project.

The main task thread stays unsettled unless the user explicitly asks the agent
to settle it. For authorized self-settlement, use the
[detached helper](references/helper.md?f#settle-after-the-current-run).
Its final response summarizes all work, supporting results, verification and
limitations. Supporting threads may be settled after their results have been
collected and their pending obligations resolved; they may inherit the main's
automatic-settlement opt-out. If the main identity is missing or ambiguous, report
that fact instead of inventing it or treating missing thread history as acceptance.
These rules do not themselves authorize delegation or a new conversation.

## Delegate a child task

Call `orchestrator_capabilities` to discover the live provider instances and
model IDs, including configured custom models. Follow the session's T3
orchestration contract when selecting native subagent tools or `delegate_task`.
Prefer native subagent tools for same-provider work only when they support the
selected model. Use `delegate_task` with that provider instance and model when
native tools cannot, for cross-provider or explicitly T3-owned child tasks,
and for a child needing a separate checkout. For the latter, set
`isolation: "worktree"`; it starts from the parent's local commit, runs project
setup, and does not copy uncommitted edits.

Retain each returned `taskId` for `task_status` or `task_cancel`. The returned
`childThreadId` is backing storage, not an ordinary thread to launch or message.
For each further T3 delegated review round, call `delegate_task` again with the
original brief, prior findings, responses and unresolved objections. Give each
round a distinct `clientRequestId`, stable across retries of that round.

If T3 tools are missing from the initial catalog, make one bounded direct
`orchestrator_capabilities` attempt using the harness's T3 tool name. If an ACP
harness still exposes no tools and `T3_ACP_MCP_NODE` is set, use its supported
transport, with arguments passed as JSON:

```bash
ELECTRON_RUN_AS_NODE=1 "$T3_ACP_MCP_NODE" ${T3_ACP_MCP_ENTRYPOINT:+"$T3_ACP_MCP_ENTRYPOINT"} \
  acp-mcp-call orchestrator_capabilities '{}'
```

Use the same transport for `delegate_task`, `task_status` or `task_cancel` as
needed. If delegation remains unavailable, report the observed blocker.
The helper implements ordinary thread operations only; never substitute
`start`, `send` or `t3_thread_launch` for child-task delegation.

## Ordinary thread operations

For a paced follow-up on this integration, use the helper's `send` path even
when `t3_thread_send` is exposed, unless that native tool has an explicit,
verified way to preserve pacer admission. Read the
[paced follow-up guidance](references/helper.md#paced-follow-ups) before sending.
For webhook-triggered thread turns, see the [webhook limits](references/helper.md#webhook-triggered-turns).
For SSH command output, see the [tested handoff](references/ssh-output-trial.md).
For other ordinary-thread operations, prefer an exposed native T3 tool.
Otherwise use the helper below. It uses the running server's authenticated
WebSocket API and also works when the collaborative browser is unavailable.
See [server discovery and authentication](references/helper.md#server-discovery-and-authentication)
for local defaults and explicit server overrides.

Before claiming ordinary thread creation or messaging is unavailable, check
this helper and the local backend. Missing native tools do not establish that
the operation is impossible. Describe an observed authentication, connection,
or API failure precisely; describe an untested path as untested.

For cross-client link labels and navigation checks, read
[thread links across clients](references/helper.md#thread-links-across-clients).

## Helper reference

For inspecting instructions supplied at startup, read
[initial-context inspection](references/initial-context.md).

Before ordinary-thread coordination through native tools or the helper, read
the [ordinary-thread command reference](references/helper.md). It covers authentication,
all five subcommands, paced review routing, persistence checks, interrupted
requests, and fork limitations. Resolve
[scripts/start_thread.py](scripts/start_thread.py) from the loaded skill directory.
Python 3.11+ and `websocket-client` are declared in its PEP 723 metadata.

For a credential-free, offline parser check:

```bash
uv run --offline --no-project --script /path/to/t3-start-thread/scripts/start_thread.py --help
```

Only `--help` exits before authentication. The `send` and `settle` dry runs
contact the server; `start` has no dry-run option.
