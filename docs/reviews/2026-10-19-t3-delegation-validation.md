# T3 delegation routing validation

HAI-10, 2026-10-19. Manual routing walkthrough of the revised
`t3-start-thread/SKILL.md`, using synthetic requests and tool availability.
No live capabilities probe, launch, delegation or message was sent. These
checks assess the instructions; the helper tests assess protocol behavior.

- Request: "Delegate this review to a T3-owned subagent."
  With orchestration tools available, select `orchestrator_capabilities`,
  then `delegate_task` with a provider instance and model from that catalog.
  Retain `taskId` for monitoring. The explicit child-task branch selects this
  path before any helper command, even if `start` is available. Pass.
- Request: "Start a new conversation to implement this change."
  With native launch tools absent and the local helper available, select
  helper `start`. With native tools available, select `t3_thread_launch`
  or `create_threads`. The explicit new-conversation branch permits both. Pass.
- Request: "Send this follow-up to the existing ordinary thread."
  With native messaging absent, select helper `send` for the target thread.
  With native messaging available, select `t3_thread_send`. Neither route
  creates a conversation. Pass.
- Request: "Have the T3 subagent review the revised patch again."
  Select a fresh `delegate_task` round with the original brief, findings,
  responses and unresolved objections, plus a new stable retry key.
  Do not message `childThreadId`. Pass.
- Request: "Delegate a child task in its own checkout."
  Select `delegate_task` with `isolation: "worktree"`. If orchestration tools
  are initially absent, attempt bounded discovery and the supported ACP
  transport when configured. An unavailable delegation path reports a blocker
  rather than falling through to helper `start`. Pass.

Compatibility checks passed:

```bash
uv run --no-project --with pytest --with 'websocket-client>=1.8,<2' pytest t3-start-thread/tests -q
ruff check t3-start-thread
uv run --no-project --with pyyaml python /path/to/skill-creator/scripts/quick_validate.py t3-start-thread
python3 .github/scripts/check_symlinks.py
git diff --check
```

All 83 helper tests passed. The helper implementation, arguments, V1/V2
protocol instructions and interrupted-request recovery rules are unchanged.
