Steward issue, 2026-10-22 03:00 refill. Goal: agentic-leverage (skills-akaihola is tier 2 on the goals page). Estimated 1 h. Source: draft D3 of [the 2026-10-22 docs review](../reviews/2026-10-22-docs-review.md#draft-issues).

A secrets scan that never ran reads as clean. In `secrets-scan/scripts/scan.py` on `main` (`278d0d1`), `run_detect_secrets()` returns `{}` when detect-secrets exits with anything other than 0 or 1 or prints invalid JSON; `run_secretlint()` silently skips a batch whose output is empty or invalid; a secretlint setup failure only prints "skipping". `main()` then renders the report and exits 0 when nothing needs review. Placeholder classification also accepts a placeholder word anywhere on the line, so a real-format value beside such a word is classed as a placeholder.

## What to do

1. Track each scanner's outcome: ran, skipped on request (`--no-secretlint` and the like) or failed, with the reason. A requested scanner that failed (unexpected exit status, unparsable output, setup failure, a skipped batch) is named in the report, and the scan exits with a status distinct from exit 1 ("findings need review"), for example 2. A skip on request stays a skip, reported as such, not a failure.
2. Judge a finding a placeholder from the detected value itself, not from words elsewhere on its line.
3. Update `secrets-scan/SKILL.md` and `secrets-scan/references/classifying-findings.md` to describe the exit statuses and the per-scanner outcome.
4. Add offline tests with fake scanners: process failure, malformed JSON, setup failure, a skipped batch, a clean complete run (still exit 0), and a real-format fake value beside a placeholder word. Build fake values with the right shape; never use a real credential.

## Constraints and acceptance

- No network in tests; don't install scanners for them.
- Never print a credential's value; name the file and line instead.
- Before merging, run the tests and checks the Rules and `AGENTS.md` ask for.
- Memory: before each command, wait up to 10 minutes for `MemAvailable` of at least 2 GiB; if it doesn't come, start the command anyway when at least 1.5 GiB is available. Stop a running command when `MemAvailable` falls below 1 GiB or swap grows by more than 512 MiB. Run one heavy command at a time, and bound any background job you start.
- Handoff: a short outcome and the checks run; detail goes in this task record.
- Acceptance: each failure path above exits with the new status and names the scanner; a clean complete run exits 0; the placeholder test passes; the two documents match the code.

Tracker: [the skills-akaihola tracker](../../TASKS.md).
