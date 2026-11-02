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

## Review outcome, 2026-10-22

The [architecture report] ranks four unfiled drafts. Do V1 server retirement,
shared launch/send reconciliation, and redundant snapshot removal first;
consolidate overlapping test fakes afterward. Preserve saved request IDs,
resume behavior, settlement refusals and the five-command CLI. The report
identifies one launch/recovery asymmetry and distinguishes its correction
from behavior-preserving simplification.

Read the complete helper, tests, skill/reference and the requested historical
tasks at main commit `8e45bbda384ace41013fce0cd8f4c7105dfec9bb`. Checked all
tracker sections and both older backlogs for overlap. No drafts were filed,
no implementation or test files changed, and no T3 calls or messages were made.
V2-only deployment is the task's premise; the V1-retirement draft explicitly
requires a later authorized live check before rollout. That future check is
not an acceptance requirement for this review.

## Validation

- **Helper baseline:** 100 tests passed with networking disabled. The command
  below uses fake ticket/WebSocket transport and temporary request records.
- **Report acceptance:** all four findings cite baseline code and explain
  the resulting behavior; each has a title, bounded work, acceptance, overlap
  status and live-verification label. The final section is Draft issues and
  recommends D1, D2 and D3 with reasons. Relative links and citation bounds
  passed the offline document check; the reviewed sources match the baseline.
- **Tracker:** Hai loaded all 23 issues, with unique stable IDs and resolving
  detail links. User acceptance remains unchecked.
- **Scope:** no production behavior was exercised. No full collection test
  suite, build, external capability check or vulnerability probe was needed
  for this documentation-only review.

```bash
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest --with websocket-client pytest -p no:cacheprovider t3-start-thread/tests -q
git diff --check
```

## Resource record

- **Helper suite — started at once:** wait 0.00 s; admission MemAvailable
  2141.5 MiB; final 2195.4 MiB; starting swap 2302.4 MiB; final swap growth
  -6.0 MiB (peak growth 0.0 MiB); elapsed 10.67 s; exit 0. Guard checked memory
  throughout, with a 180-second command bound and process-group cleanup.
  No other heavy command ran concurrently.


## Merge and recorded checks

Fast-forwarded from `8e45bbda384ace41013fce0cd8f4c7105dfec9bb` to delivery
commit `4854e22483f5fd1efa92e30dae43e13967144294`. Retained the task branch
and worktree; the task worktree is detached at the tested delivery commit.

- **Report acceptance:** the evidence recorder ran the document checks and
  committed-diff whitespace check against the clean merged checkout; exit 0.
  It verifies source equality with the reviewed baseline, citation bounds,
  relative links, ranked findings, complete drafts, overlap/live labels,
  first-three order and the final Draft issues section. Judgment about each
  finding's usefulness remains the written review, not a mechanical assertion.
- **Helper fake suite:** the recorder reran all 100 tests with networking
  disabled and pinned pytest 9.1.1 and websocket-client 1.9.2; exit 0. No lockfile
  exists for this standalone helper. The receipt declares its script metadata
  as a SHA-256 dependency; no editable package checkouts are used. The document
  check uses only Python's standard library and Git, with its command embedded
  in the receipt rather than depending on a temporary verifier file.
- **Evidence helper suite — started at once:** wait 0.00 s; admission
  MemAvailable 2797.3 MiB; final 2818.4 MiB; starting swap 2221.5 MiB; final
  growth 2.0 MiB (peak 2.2 MiB); elapsed 8.80 s; exit 0. This includes the
  evidence recorder around the command below. The same 180-second guard,
  memory thresholds and process-group cleanup applied; one heavy command ran
  at a time.

```bash
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider t3-start-thread/tests -q
```

## Receipt publication

The user explicitly authorized committing the required receipt unchanged,
including its machine paths, on 2026-10-22. This resolves the earlier conflict
with the task's private-path restriction for this receipt only. The
[recorded check receipt] contains both passing checks at the clean merged
commit. Its freshness check passed before publication; no implementation or
review changes required rerunning the suite.

The report acceptance criteria are met. No checks failed or stopped. Complete
this item with user acceptance unchecked; the steward handles the unfiled
drafts in the report.

[architecture report]: ../reviews/2026-10-22-t3-start-thread-architecture-review.md
[recorded check receipt]: 23-review-the-t3-start-thread-helper-s-architecture-for-deep-modules-and-.evidence.json
