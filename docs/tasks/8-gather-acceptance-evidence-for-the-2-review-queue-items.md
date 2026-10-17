# Gather acceptance evidence for the 2 review-queue items

Steward issue, 2026-10-17 (decisions D7, D10 and D37 in
`/home/agent/my-knowledge/agents/steward/decisions.md`). It takes over
skills-akaihola's part of vault [17]. The vault's tracker is blocked, so this
check runs here, in the repository it checks. The verdicts feed the steward's
next digest, so that Antti can accept or reject these items with less checking
of his own.

## Items

These `- [ ]` items under `## Completed / Accepted`:

- [6], the `t3-start-thread` helper on T3's V2 protocol as well as V1.
- [7], its `settle` command. Steward runs have used it since 2026-10-17 20:08
  against gogo's V1 server; their logs under
  `/home/agent/my-knowledge/agents/steward/log/` are evidence too.

Items whose Hai metadata has no `updatedAt` (it starts with 1970 in `hai-tasks
read`) are legacy bullets that predate Hai timestamps. Judge them against
today's `main`: find the commits that delivered each one (`git log -S`,
`--grep`, its description under `docs/tasks/`) and check that the behaviour
still exists. An item superseded by later work is "would accept" only when the
later work covers its request; name the issue that superseded it.

## Work

Run the test suite that the README or AGENTS.md documents once on current
`main`, and a targeted test wherever an issue names one. Make no call to a live
T3 server. Check criterion 3 with `git revert --no-commit` of an item's merge
commits in a temporary worktree (`git worktree add --detach
"$TMPDIR/revert-check" main`, removed afterwards); conflicts only in `TASKS.md`
and `docs/tasks/` don't count.

For each item, record one line: issue, a one-line outcome, the evidence
(commits, files, test command with pass and fail counts) and a verdict under
`/home/agent/my-knowledge/agents/steward/acceptance-policy.md`:

- **would accept:** all four criteria hold; give the revert command;
- **left to Antti:** name the criterion or the "Always left to Antti" class;
- **not done:** say what is missing.

## Deliverable

A section `## Evidence, YYYY-MM-DD` in this description file, with the lines
grouped by verdict and the counts per verdict at the end.

## Ground rules

- Change no other issue's state or text, and never change `[ ]` to `[x]`: only
  Antti accepts.
- Don't push, deploy or restart services, and don't touch the vault or the
  running pacer.

## Acceptance

- Every listed item has a line with evidence and a verdict.
- Nothing outside this file and the issue's own tracker moves changed.
