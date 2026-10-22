---
depends-on: [24]
---

Steward issue, 2026-10-22 08:54 refill (steward decisions D53 and D95: simplification that keeps behaviour). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Estimated 1 h.

This is draft D2 of [the 2026-10-22 t3-start-thread architecture review](../reviews/2026-10-22-t3-start-thread-architecture-review.md#draft-issues), filed as written there; read that draft and the finding it cites before starting. The review's line numbers refer to its baseline; recheck them on current `main`.

The helper is the steward's only route for follow-ups and settling threads, so keep its CLI, output shapes and refusals unchanged. Don't call a live T3 server: fake servers verify this work, and the steward runs a read-only `inspect` against hopeli's T3 after the merge.

## Work

Use one record-oriented submission path for saved IDs, acknowledgement writes, the accepted-but-missing refusal and final persistence. Keep operation-specific dispatch and output small and explicit. Check the V2 launch's initial message after dispatch as well as on resume.

## Acceptance

- Fake loss before and after acceptance keeps the IDs and never creates a second message; an acknowledged missing result never redispatches.
- A newly acknowledged launch whose thread is visible but whose first message is not reports incomplete visibility and keeps its record; once visible, resume finishes without replay.
- Archived launch recovery, private record handling and both successful CLI output shapes stay covered; the helper suite passes with networking disabled.

## Ground rules

- Behaviour stays the same unless the acceptance says otherwise. Write the pinning test first where the draft asks for one.
- Run at most one focused test command at a time, under your launch prompt's memory rule; no full browser suite.
- Keep private paths and host names out of committed docs and code. The check receipt (`*.evidence.json`) is machine evidence and exempt.
- Handoff: a short outcome; details go in this task record.

Tracker: [the skills-akaihola tracker](../../TASKS.md).
