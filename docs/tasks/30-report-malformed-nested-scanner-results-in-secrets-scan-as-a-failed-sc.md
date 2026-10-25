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

## Implementation record

- **Boundary checks.** [scan.py][scan] gained `expect()`, which returns a
  value of the expected JSON type or raises the existing `ScannerError`. Its
  reason names the malformed part (for example `loc.start was not a JSON
  object`), never the value. `parse_secretlint_batch()` now builds the
  finding dicts itself and checks each level: the output list, each result
  item, `filePath`, `messages`, each message, `loc`, `start`, `end` and the
  four line and column positions. A malformed batch fails as a whole, so none
  of its findings are kept. Other batches' findings are, and the reason
  counts the batches not scanned. `run_secretlint()` only collects batches
  now. `run_detect_secrets()` checks that every `results` entry is a list of
  objects. Missing keys keep their old defaults, and no rule or
  classification changed.
- **Beyond the listed shapes.** A non-object message, a non-string
  `filePath` and a non-integer column also crashed (`AttributeError` from
  `.get`/`.replace`, `TypeError` from slicing in `secretlint_value()`), so
  they get the same per-level check. Detect-secrets leaf values reach no
  crashing code and stay unchecked.
- **Python 3.10.** The script declares `requires-python = ">=3.10"`, so
  `expect()` uses `TypeVar` rather than PEP 695 syntax, with a
  `ruff: ignore[non-pep695-generic-function]` comment. Ruff with
  `--target-version py310` parses the file cleanly. A control file with a
  type parameter list fails that check.
- **Docs.** [classifying-findings.md][ref] lists the nested shapes that fail
  a batch or detect-secrets, and says that reasons name the malformed part.
  [SKILL.md][skill] needed no change.
- **Tests.** [test_secrets_scan.py][tests] adds 13 malformed shapes, each run
  in Markdown and JSON (26 cases). They use the existing fake-executable
  harness, which stands in for what `run_tool()` launches, and synthetic data
  only. Ten are secretlint shapes: null, scalar and list items, non-string
  `filePath`, non-list `messages`, non-object message, `loc`, `start` and
  `end`, and a non-integer column. Three are detect-secrets shapes:
  non-mapping `results`, a non-list entry and a non-object finding. Every
  case expects exit 2, the scanner named as failed with its exact reason,
  and exactly one finding: the one from the well-formed secretlint batch.
  Both files and every malformed value hold the synthetic token, so the
  harness's redaction assert would catch an echoed value.
- **Red, then green.** Against the unchanged scanner, 24 of the 26 new cases
  failed with uncaught `AttributeError` or `TypeError`. The two non-mapping
  `results` cases passed already, because `7e7a300` handles that shape;
  they stay as regression guards. With the change, all 42 scanner tests and
  the 27 security-boundary tests pass.

### Checks before merge

`CHECKS` is the external check-artifact directory named in the receipt. Its
requirements lock is the one task 29 compiled. Commands ran from the task
worktree root:

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH= PYTHONNOUSERSITE=1
unshare -rn uv run --offline --no-project --with-requirements "$CHECKS/requirements.lock" python scripts/check_skill_metadata.py
unshare -rn uv run --offline --no-project --with-requirements "$CHECKS/requirements.lock" pytest -p no:cacheprovider tests/test_skill_metadata.py tests/test_secrets_scan.py tests/test_read_as_markdown.py tests/test_security_boundaries.py t3-start-thread/tests -q
unshare -rn uv run --offline --no-project --with-requirements "$CHECKS/requirements.lock" python secrets-scan/scripts/scan.py --help
ruff check secrets-scan/scripts/scan.py tests/test_secrets_scan.py
ruff format --check secrets-scan/scripts/scan.py tests/test_secrets_scan.py
ruff check --isolated --target-version py310 --select F,E9 secrets-scan/scripts/scan.py
python3 .github/scripts/check_symlinks.py
git diff --check
```

- **Metadata:** exit 0; 48 skill frontmatters validated.
- **Regressions:** exit 0; 184 passed (task 29's 158 plus the 26 new cases).
- **Help:** exit 0.
- **Ruff:** check and format passed on both changed Python files; ty also
  passed on `scan.py`.
- **Symlinks and whitespace:** passed.

The other skills' own suites (`android-diagnostics`, `ecb-rates`,
`himalaya-email-manager`, `mcp-to-skill`, `processing-scanned-receipts`,
`reflect-extensions`) have separate CI and dependencies. Nothing they import
changed, so they were not run.

### Memory before merge

The guard waited up to 600 seconds for 2,048 MiB available, with a 1,536 MiB
fallback. It polled every 0.2 seconds and would stop the process group below
1,024 MiB available or above 512 MiB swap growth. Each command had a timeout
of 120–300 seconds and its process group was cleaned up afterwards. Commands
ran one at a time. No fallback or running stop occurred. These measurements
contain no command output.

| Command | Outcome | Wait (s) | Admission / final available (MiB) | Starting swap / growth (MiB) | Elapsed (s) | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| New tests against the unchanged scanner | started at once | 0.0 | 57958.1 / 57945.1 | 0.5 / 0 | 2.0 | exit 1 (24 failed, as intended) |
| Scanner and boundary tests after the change | started at once | 0.0 | 57907.6 / 57879.4 | 0.5 / 0 | 2.81 | exit 0 |
| Same, after tightening one assertion | started at once | 0.0 | 57893.1 / 57826.3 | 0.5 / 0 | 1.6 | exit 0 |
| Final new tests against the unchanged scanner | started at once | 0.0 | 57894.7 / 57891.9 | 0.5 / 0 | 2.0 | exit 1 (24 failed, as intended) |
| Metadata validator | started at once | 0.0 | 57589.2 / 57583.8 | 0.5 / 0 | 0.2 | exit 0 |
| Regression suites | started at once | 0.0 | 57584.8 / 57521.5 | 0.5 / 0 | 3.41 | exit 0 |
| Scanner help probe | started at once | 0.0 | 57576.1 / 57563.7 | 0.5 / 0 | 0.2 | exit 0 |

### Integration and merged checks

Base commit: `2e3340114abcbee3e6b96d8c7f8df2c06c4f2a1e`. Delivery and merged
commit: `95bbe1f900414735f84acd25f513d2524c842b02`. The task branch was
rebased onto `main` (adding only the start move beneath it) and
fast-forwarded. The task worktree was detached at the merged commit for
clean-checkout recording. The task branch and worktree are retained.

All four evidence commands passed at the merged commit:

- **metadata:** exit 0; 48 skill frontmatters validated.
- **regressions:** exit 0; 184 passed. This is the full repository-level
  suite: all four root `tests/` files and `t3-start-thread/tests`.
- **new-tests-fail-on-base:** exit 0. In a temporary export of the merged
  tree with the base commit's `scan.py`, the two new test functions gave
  `24 failed, 2 passed`. The two passes are the non-mapping `results` cases
  that `7e7a300` already handled.
- **ruff:** exit 0; check and format passed on both changed Python files,
  and the Python 3.10 parse passed on `scan.py` (Ruff 0.16.8).

The [check receipt][receipt] records the exact commands, dependency hashes
(the requirements lock, `pyproject.toml` and the Ruff binary), the tested
commit and the results. It was copied only after all record calls finished.
No commit intervened between the merge and the completion move. User
acceptance remains unchecked.

### Memory for evidence recording

Each row names `CHECK_ID` in this command (`RECORDER` and `EVIDENCE` identify
the external recorder and declaration used for this task):

```bash
uv run "$RECORDER" record "$EVIDENCE" 'skills-akaihola [30]' CHECK_ID
```

The same admission and monitoring guard applied, with a 300-second timeout
per record call and process-group cleanup. These measurements contain no
check output; the results are listed above.

| Record command / CHECK_ID | Outcome | Wait (s) | Admission / final available (MiB) | Starting swap / growth (MiB) | Elapsed (s) | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `metadata` | started at once | 0.0 | 57486.9 / 57460.5 | 0.5 / 0 | 0.2 | exit 0 |
| `regressions` | started at once | 0.0 | 57473.9 / 57431.1 | 0.5 / 0 | 3.61 | exit 0 |
| `new-tests-fail-on-base` | started at once | 0.0 | 57509.0 / 57474.8 | 0.5 / 0 | 1.6 | exit 0 |
| `ruff` | started at once | 0.0 | 57491.3 / 57461.5 | 0.5 / 0 | 0.2 | exit 0 |

[scan]: ../../secrets-scan/scripts/scan.py
[ref]: ../../secrets-scan/references/classifying-findings.md
[skill]: ../../secrets-scan/SKILL.md
[tests]: ../../tests/test_secrets_scan.py
[receipt]: 30-report-malformed-nested-scanner-results-in-secrets-scan-as-a-failed-sc.evidence.json
