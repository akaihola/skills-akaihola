# Review every skill for stale instructions, weak triggers and token cost, and draft the fixes

Steward issue, 2026-10-19 (spare quota, steward decisions D48 and D53:
quality, tokens per unit of work, and review of docs and instructions).
Goal: agentic-leverage; skills-akaihola is tier 2. It took 47 commits in the
last week and has never had a whole-repository review. Agents read these
skills' descriptions in every session and load a SKILL.md whenever one
matches: a vague description loads the wrong skill or misses the right one,
and a long SKILL.md costs tokens on every load. `t3-start-thread`, which the
steward uses on every run, lives here.

## Work

1. List every skill with the length of its description and SKILL.md and
   the references it loads.
2. For each skill, check: does the description say concretely when to use
   it, and when not? Is SKILL.md short, with details behind links? Do the
   commands, paths and scripts it names still exist, and do the scripts'
   `--help` and offline tests run? Does it duplicate another skill?
3. Apply `honey-review` to the scripts (dead code, single-caller
   abstractions, hand-rolled stdlib) and `writing-for-agents` to the
   instructions.
4. Write `docs/reviews/2026-10-19-skills-review.md`: a table of every
   skill, then findings ranked by benefit per hour, each with file and line
   evidence and a drafted issue (title, work, acceptance, about an agent
   hour each). Mark drafts that overlap open issues in `TASKS.md` instead of
   duplicating them.

## Ground rules

- Read-only apart from the report and this issue's tracker moves. Don't
  file the drafts; the steward files them.
- Run nothing that sends a message, starts or settles a thread, or reaches
  the network.
- No host names or private home paths in any file: the topology check
  rejects them.

## Acceptance

- Every skill appears in the report's table.
- Every finding cites a file and line on `main` and says what changes if it
  is fixed.
- The report names the three drafts it would do first, and why.
