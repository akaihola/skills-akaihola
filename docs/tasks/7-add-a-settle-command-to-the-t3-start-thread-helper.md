---
depends-on: [6]
---

# Add a settle command to the t3-start-thread helper

Steward coordination item, requested by Antti on 2026-10-17 in T3 thread
`ee231743` (decision D42 in `/home/agent/my-knowledge/agents/steward/decisions.md`).

## Why

Each steward run (tick, digest, weekly) is a fresh T3 thread. From 2026-10-17
every run's closing message also covers the earlier runs Antti has not read, and
the run then settles those earlier run threads, so his sidebar shows one steward
run thread instead of one per run. T3's automatic settling (after inactivity, on
merge) is switched off on gogo. The helper can start and message threads but
cannot settle them.

## Protocol facts

- Both protocols take the same command through `orchestration.dispatchCommand`:
  `{"type": "thread.settle", "commandId": …, "threadId": …}`. V1: t3code tag
  `v0.0.45`, `packages/contracts/src/orchestration.ts` (`ThreadSettleCommand`).
  V2: t3code `main`, `packages/contracts/src/orchestrationV2.ts`, which adds an
  optional `settledAt`.
- The V1 server (`apps/server/src/orchestration/decider.ts` at `v0.0.45`)
  refuses with `OrchestrationThreadSettleBlockedError` when the session is
  starting or running, when an approval or callback is pending, or when a turn
  start is queued. It dismisses a pending message-mode question unanswered.
  Settling an already-settled thread is a silent no-op that keeps the original
  `settledAt`.
- A new turn in a settled thread un-settles it (`thread.unsettled`, reason
  `activity`).

## Requirements

1. `settle --url URL --thread ID [--thread ID …]` dispatches `thread.settle`
   for each thread on V1 and V2, with a fresh `commandId` per thread.
2. It refuses, without dispatching, a thread that is archived, active (the
   `inspect` `active` flag) or waiting for an answer or approval, reports it and
   continues with the rest. Settling must never dismiss an unanswered question.
3. `--dry-run` reports what each thread would get without dispatching.
4. One JSON result per thread: `settled`, `already-settled`, `refused` with the
   reason, or the server's error. Exit non-zero if any thread was refused or
   failed.
5. `inspect` adds each thread's `settledAt`, so callers need not read T3's
   database.
6. `SKILL.md` documents the command.
7. Tests cover both protocols, an already-settled thread and each refusal.

## Acceptance

- Unit tests, Ruff, ty and `git diff --check` pass.
- Against gogo's live T3 (V1): `inspect` shows `settledAt`, and `settle
  --dry-run` on the steward's run threads reports sensible results. Settle no
  live threads; the steward's runs are the first real users (D42).
- Against an isolated V2 server set up as in [6]: settle a scratch thread,
  settle it again (no-op), and check that a running thread is refused.

Out of scope: which threads the steward settles (its `AGENTS.md`).
