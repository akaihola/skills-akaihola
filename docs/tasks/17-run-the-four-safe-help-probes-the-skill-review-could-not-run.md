Steward issue, 2026-10-21 14:00 tick. Goal: agentic-leverage (skills-akaihola is tier 2 in `<steward-vault>/Goals.md`). Estimated 1 h.

[9] (review every skill for stale instructions, weak triggers and token cost) waits in the review queue: four harmless help probes lacked their offline dependencies, so they never ran. Source: the steward's triage of the review queue, `<steward-vault>/notes/2026-10-21-left-to-antti-triage.md`, "Prepare the specific repairs", item "Skill instruction review".

## Work

1. Find the four probes in [9]'s report and task file.
2. Provide their dependencies in an isolated environment (`uv run --with …` or a disposable venv) and run each help probe.
3. Where a skill parses its arguments by hand, read the parser instead of invoking a real operation.

## Acceptance

- All four probes have recorded results in a dated note in [9]'s task file, and any help path that stays unsupported is explained.
- No private database, mailbox, model call or external message is used. Memory: follow your launch prompt's memory rule, and run one heavy command (test suite, browser, build) at a time.
