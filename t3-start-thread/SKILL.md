---
name: t3-start-thread
description: Route requested T3 Code coordination to child-task delegation, an explicitly requested new conversation, or messaging and settling existing threads, including when native tools are not initially exposed.
---

# Coordinate T3 Code tasks and threads

## Apply model-setting preferences

Before creating a thread or delegating a task, read
[agent@tinni:~/my-knowledge/USER.md](http://tinni/my-knowledge/USER.md?f#t3-code-model-settings) when present. Explicit user
preferences override inherited and catalog-default reasoning and service-tier
options. Pass the resolved options explicitly and verify the created thread's
saved configuration. The helper's `start` accepts exactly one of `--parent-thread` or `--settings`.
For an override, copy all three settings fields from `inspect`, edit the required
options, and pass only `--settings`; it replaces rather than merges settings.

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

Prefer a native T3 tool for the selected operation if one is exposed.
Otherwise use the helper below. It uses the running server's authenticated
WebSocket API and also works when the collaborative browser is unavailable.

Before claiming ordinary thread creation or messaging is unavailable, check
this helper and the local backend. Missing native tools do not establish that
the operation is impossible. Describe an observed authentication, connection,
or API failure precisely; describe an untested path as untested.

## Helper reference

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
