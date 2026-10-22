---
depends-on: [25]
---

Steward issue, 2026-10-22 08:54 refill (steward decisions D53 and D95: simplification that keeps behaviour). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Estimated 1 h.

This is draft D3 of [the 2026-10-22 t3-start-thread architecture review](../reviews/2026-10-22-t3-start-thread-architecture-review.md#draft-issues), filed as written there; read that draft and the finding it cites before starting. The review's line numbers refer to its baseline; recheck them on current `main`.

The helper is the steward's only route for follow-ups and settling threads, so keep its CLI, output shapes and refusals unchanged. Don't call a live T3 server: fake servers verify this work, and the steward runs a read-only `inspect` against hopeli's T3 after the merge.

## Work

Separate projection and message reads from shell-summary composition inside the existing server and reconciliation boundary. Reuse a shell already fetched for that observation, keep merge precedence and archived lookup, and fetch fresh summary state after a dispatch. No persistent connection or snapshot cache.

## Acceptance

- Fake request traces show five successful RPCs for a fresh V2 send and two for an already-visible V2 launch resume.
- Message-ID checks, summary output and archived recovery are unchanged; a fake state change after dispatch appears in the returned summary.
- Each settle target still gets its own fresh shell and its own refusal or error outcome; the helper suite passes with networking disabled.

## Ground rules

- Behaviour stays the same unless the acceptance says otherwise. Write the pinning test first where the draft asks for one.
- Run at most one focused test command at a time, under your launch prompt's memory rule; no full browser suite.
- Keep private paths and host names out of committed docs and code. The check receipt (`*.evidence.json`) is machine evidence and exempt.
- Handoff: a short outcome; details go in this task record.

Tracker: [the skills-akaihola tracker](../../TASKS.md).
