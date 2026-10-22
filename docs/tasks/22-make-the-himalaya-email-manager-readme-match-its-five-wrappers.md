Steward issue, 2026-10-22 03:00 refill. Goal: agentic-leverage (skills-akaihola is tier 2). Estimated 30 min. Source: draft D8 of [the 2026-10-22 docs review](../reviews/2026-10-22-docs-review.md#draft-issues).

`himalaya-email-manager/README.md` still promises a rolling 24-hour summary, server-side filtering and an older attachment location. The five wrapper scripts do otherwise: the summary uses date prefixes and one default page, search filters one page locally, and the save script writes elsewhere. The README was outside the docs review's corpus, so it wasn't fixed there. Separately, `jmap/SKILL.md` points to a workspace helper that isn't bundled and assumes a fixed account and tunnel.

## What to do

1. Make the README describe what the five wrappers do on `main`, and link `SKILL.md` and `references/scripts.md` rather than repeat them.
2. Add the `jmap/SKILL.md` observation to the existing portable-JMAP proposal in [the backlog](../../BACKLOG.md) as an amendment; don't file a new proposal and don't edit `jmap/`.

## Constraints and acceptance

- Documentation only. Leave `docs/tasks/adopt-task-tracking-principles.md`, earlier reviews and the scripts as they are.
- Before merging, run the checks the Rules and `AGENTS.md` ask for.
- Handoff: one or two sentences; detail goes in this task record.
- Acceptance: each README statement about behaviour names the wrapper and option it matches in this task record; the backlog amendment is on `main`.

Tracker: [the skills-akaihola tracker](../../TASKS.md).
