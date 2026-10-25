Steward issue, 2026-10-25 03:11 refill (steward decisions D43, D53 and D95). Goal: agentic-leverage (skills-akaihola is a tier 2 project in `<steward-vault>/Goals.md`). Unlabelled, so it can use either subscription. Estimated 1.5 h.

Tracker: [TASKS.md](../../TASKS.md).

## Why

[The 2026-10-25 docs recheck](../reviews/2026-10-25-docs-recheck.md#draft-issues), draft D1: `secrets-scan/SKILL.md` promises exit 2 when "a requested scanner failed", and `7e7a300` reports invalid JSON and wrong outer containers that way. But `run_secretlint()` assumes every result item and message is a dictionary, and `build_combined()` trusts nested detect-secrets results the same way. A synthetic probe whose fake `run_tool()` returned `[null]` ended in an uncaught `AttributeError` before any report: the agent gets a traceback and exit 1, which the table reads as "a finding needs review", instead of exit 2 and a named failed scanner. This is failure reporting, not detection: no rule or finding changes.

## What to do

1. Write failing tests first in `tests/test_secrets_scan.py`, with a fake `run_tool()` and synthetic data only: secretlint batches whose items are `null`, a scalar or a list, whose `messages` isn't a list, and whose `loc`/`start`/`end` aren't objects; detect-secrets `results` that isn't a mapping, or whose entries aren't lists of objects. Each case expects exit 2, the scanner named as failed with a reason that prints no file content, and findings from well-formed batches kept.
2. Validate each nested shape at the scanner boundary (in `parse_secretlint_batch` and where detect-secrets output is parsed), raising the existing `ScannerError` so the current incomplete-scan path handles it. Keep the code small: one check per level, no new dependency.
3. If `SKILL.md` or `references/classifying-findings.md` needs a word for the new failure reason, change only that.

## Constraints and acceptance

- Never run the scanners on a real repository or read any secret for this; synthetic in-memory data only. Never print flagged lines or values, in tests, logs or the task record.
- Keep private paths out of committed docs and code; the check receipt is exempt.
- Before merging, run the checks [the last docs recheck's record](29-check-skills-akaihola-s-skill-instructions-against-the-seven-source-ch.md) ran (the skill metadata check and the pytest line covering `tests/test_secrets_scan.py` and `tests/test_security_boundaries.py`), and Ruff on the changed files.
- Memory: follow your launch prompt's memory rule. Run one heavy command at a time and bound any background job you start.
- Acceptance: every malformed shape above gives exit 2 with the scanner named as failed, well-formed batches' findings still appear, the new tests failed before the change and pass after, and the full suite passes at the merged commit. Handoff: a short outcome; details go in this task record.
