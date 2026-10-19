Steward issue, 2026-10-19. Goal: agentic-leverage; skills-akaihola is tier 2.

From draft D1 of `docs/reviews/2026-10-19-skills-review.md` (the review in skills-akaihola [9]), which ranks it among the first to do. The draft follows as the reviewer wrote it; read the review's other sections only if this one points there.

## Draft

Evidence: `t3-start-thread/SKILL.md:3` includes delegation in its trigger;
`t3-start-thread/SKILL.md:107` routes handoff through `start`;
`t3-start-thread/scripts/start_thread.py:523` exposes ordinary thread actions,
not a delegated-task action. The skill itself distinguishes a harness subagent
at `t3-start-thread/SKILL.md:9`, but never gives that branch a child-task path.
The current session's T3 contract explicitly distinguishes delegated tasks from
top-level conversations. This is an instruction mismatch, not a failed live probe.

Draft title: **Separate T3 child-task delegation from top-level launches.**
Work: introduce an explicit intent decision before helper commands; route
subagent requests through live orchestration capabilities/delegate_task and
reserve `start` for explicitly requested ordinary threads. Keep the helper's
protocol and interruption recovery rules. Acceptance: synthetic requests for a
subagent, a new conversation and a follow-up each select the correct operation;
no live launch needed; all 83 helper tests still pass. Benefit: prevents the
wrong kind of conversation and its coordination overhead. Estimate: 1 hour.
Overlap: adjacent to completed [6]/[7], not a duplicate.

## Steward's constraints

- The steward's scheduled runs call `start_thread.py start`, `send` and `settle` (`agents/steward/scripts/start-run.sh` in the vault). Change the skill's instructions, not those commands or their arguments.

## Done when

The draft's acceptance holds, lint and tests pass, and the change is merged to `main` as the Rules describe. No push or deploy.
