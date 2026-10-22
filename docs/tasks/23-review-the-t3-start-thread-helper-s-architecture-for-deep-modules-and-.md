Steward issue, 2026-10-22 08:00 digest (steward decisions D53 and D95: architecture review aimed at simplification that keeps behaviour). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Label `review`. Estimated 1 h.

The `t3-start-thread` helper (`t3-start-thread/scripts/start_thread.py`, about 670 lines, with about 1,200 lines of tests) is the steward's only route for sending follow-ups to T3 threads and settling them, several times a day. It grew in small steps (V2 protocol [6], `settle` [7], child-task routing [10]) and has never had an architecture review of its own; [the 2026-10-19 skills review](../reviews/2026-10-19-skills-review.md) covered the whole collection only briefly.

## Work

1. Read `t3-start-thread/SKILL.md`, `references/helper.md`, the script and its tests, and the task records of [6], [7] and [10].
2. Apply the `honey` principles (speculative generality, hand-rolled stdlib, single-caller abstractions, dead code, narration) and the `codebase-design` deep-module vocabulary, using those skills if your session has them: where the session, RPC, launch, send and settle paths could share fewer, deeper modules, what V1-era code can go now that T3 runs V2 only, and whether the skill text and the script still agree.
3. Write `docs/reviews/2026-10-22-t3-start-thread-architecture-review.md`: findings ranked by benefit per hour, each with file and line evidence on `main`, what changes if it is fixed, and a drafted issue (title, work, acceptance, about an agent hour each). Mark drafts that overlap open issues or Unverified proposals in `TASKS.md` instead of duplicating them, and mark any draft that needs a live T3 server to verify.

## Ground rules

- Architecture only. Don't probe for vulnerabilities.
- Read-only apart from the report and this issue's tracker moves. Don't file the drafts; the steward files them.
- Follow your launch prompt's memory rule; one heavy command at a time.
- Keep private paths and host names out of committed files.
- Make no call to a T3 server; the tests' fakes are enough. This repository's history is public.

## Acceptance

- Every finding cites code on `main` and says what changes if it is fixed.
- The report ends with a `## Draft issues` section and names the three drafts to do first, and why.
- Handoff: a short outcome; details go in the report and this task record.

Tracker: [the skills-akaihola tracker](../../TASKS.md).
