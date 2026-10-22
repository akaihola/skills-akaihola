Steward issue, 2026-10-22 08:54 refill (steward decisions D53 and D95: simplification that keeps behaviour). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Estimated 1 h.

This is draft D1 of [the 2026-10-22 t3-start-thread architecture review](../reviews/2026-10-22-t3-start-thread-architecture-review.md#draft-issues), filed as written there; read that draft and the finding it cites before starting. The review's line numbers refer to its baseline; recheck them on current `main`.

The helper is the steward's only route for follow-ups and settling threads, so keep its CLI, output shapes and refusals unchanged. Don't call a live T3 server: fake servers verify this work, and the steward runs a read-only `inspect` against hopeli's T3 after the merge.

## Work

Connect with V2 at once; remove the V1 handshake fallback, V1 server-state decoding and protocol selection outside the transport. Keep the saved command shape and the V2 converter, summary compatibility keys, CLI, settings and settlement refusals. Collapse the live-server parametrization to V2, adapt the older direct fakes just enough to keep the suite passing, and update `t3-start-thread/references/helper.md` in the same change. Record migration and wholesale fixture consolidation are out of scope (draft D4 owns the fakes).

## Acceptance

- The first socket requests V2 with one ticket; a failed authentication or upgrade does not retry.
- The full helper suite passes with all five actions covered on V2, with networking disabled.
- Old start and send records keep their saved command, thread and message IDs; pending, acknowledged, archived and lost-reply recovery still pass.
- The reference distinguishes V2 server support from old-record support.

## Ground rules

- Behaviour stays the same unless the acceptance says otherwise. Write the pinning test first where the draft asks for one.
- Run at most one focused test command at a time, under your launch prompt's memory rule; no full browser suite.
- Keep private paths and host names out of committed docs and code. The check receipt (`*.evidence.json`) is machine evidence and exempt.
- Handoff: a short outcome; details go in this task record.

Tracker: [the skills-akaihola tracker](../../TASKS.md).
