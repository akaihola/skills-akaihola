# Make the t3-start-thread helper speak T3's V2 protocol as well as V1

Steward coordination item, a prerequisite of step 2 in the pacing-hook sequence
(decisions D29–D30 in `/home/agent/my-knowledge/agents/steward/decisions.md`).

## Why

`t3-start-thread/scripts/start_thread.py` speaks T3's V1 orchestration protocol,
which gogo's T3 0.0.45 serves. T3 main and nightlies from 0.0.46 serve V2. The
upgrade that brings the pacing hook to gogo would break this helper, and with it
the steward's interim scheduler (`agents/steward/scripts/start-run.sh` in the
vault, started every 3 hours by a Tyko Hermes job) and every agent that starts or
messages T3 threads. The helper must work on both protocols before the upgrade, so
the switch needs no coordinated change on the day.

## Current V1 use

- Transport: `POST /api/auth/websocket-ticket`, then `/ws?wsTicket=…`.
- `orchestration.subscribeShell` (first `snapshot` chunk) for `inspect`, `start`
  and `send`; `orchestration.subscribeThread` for one thread.
- `orchestration.dispatchCommand` with `thread.turn.start`. `start` adds
  `bootstrap.createThread` (a worktree with `requireWorktree`, or the shared
  checkout); `send` messages an existing thread; `resume` resends a saved record.
- `inspect` prints projects and the 10 newest threads with V1 `session` and
  `latestTurn`. `start-run.sh` re-derives "active" from those fields.

## V2 facts (observed on the wire, 2026-10-15)

kandev-pacer issue [49] records them in
`/home/agent/prg/kandev-pacer/docs/tasks/49-port-t3-mode-to-t3-s-v2-protocol-pacedruns-discovery-and-queued-run-ad.md`.
In short:

- The socket needs `/ws?orchestrationProtocol=2&wsTicket=…`; without it V2 answers
  HTTP 426 `orchestration_protocol_incompatible`. Auth is unchanged.
- New threads start with `orchestration.launchThread` (`workspaceStrategy`,
  `initialMessage`); it returns `{threadId, projection, resumed}`. Follow-ups use
  `message.dispatch`.
- Thread activity lives in `status`, `activeRunId`, `activityRunStatus`,
  `pendingRuntimeRequest` and `pendingBackgroundTasks`; archived threads move to
  `archivedThreads`.
- On a server with the pacing hook, a prompt ending in `...` or `…` parks until
  the pacer admits it (D28).

The V2 source is `/home/agent/repos/ai/t3code`, branch
`t3code/implement-pacing-hook` (local to gogo); its `docs/pacing-hook/README.md`
describes running a dev server ("Checked end to end").

## Requirements

1. Detect the protocol once per invocation, by behaviour or response shape, not
   by version string (main still reports 0.0.45), and use V1 or V2 accordingly.
2. `inspect`, `start` (worktree and `--shared-checkout`; `--settings` and
   `--parent-thread`), `send` and `resume` keep their CLI and output on both.
3. `inspect` adds an `active` flag per thread, so callers stop re-deriving it
   from protocol fields.
4. Saved records under `~/.local/state/t3-start-thread/` stay resumable, and a
   resend with the same `commandId` stays idempotent on V2.
5. `SKILL.md` warns that a prompt ending in `...` or `…` parks on a paced server.
6. Tests cover both protocols for every action.

## Acceptance

- Unit tests pass for both protocols.
- Against gogo's live T3 (0.0.45, V1): `inspect` works, and
  `agents/steward/scripts/start-run.sh tick --dry-run` in the vault still passes
  (run it unsandboxed; it creates no thread). Start no threads on the live server.
- Against a V2 dev server built from the t3code branch, with a scratch project and
  a pruned copy of the database: `inspect`, `start` with a shared checkout and with
  a worktree, and `send` all work.

Out of scope: `start-run.sh` itself (the steward adapts it to the `active` flag)
and deploying T3.
