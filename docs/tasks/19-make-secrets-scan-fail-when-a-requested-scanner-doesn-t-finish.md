Steward issue, 2026-10-22 03:00 refill. Goal: agentic-leverage (skills-akaihola is tier 2 on the goals page). Estimated 1 h. Source: draft D3 of [the 2026-10-22 docs review](../reviews/2026-10-22-docs-review.md#draft-issues).

A secrets scan that never ran reads as clean. In `secrets-scan/scripts/scan.py` on `main` (`dcb627c`), `run_detect_secrets()` returns `{}` when detect-secrets exits with anything other than 0 or 1 or prints invalid JSON; `run_secretlint()` silently skips a batch whose output is empty or invalid; a secretlint setup failure only prints "skipping". `main()` then renders the report and exits 0 when nothing needs review. Placeholder classification also accepts a placeholder word anywhere on the line, so a real-format value beside such a word is classed as a placeholder.

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

## Task record

Implemented 2026-10-22 in the HAI-19 task worktree.

- **Per-scanner outcome.** [scan.py](../../secrets-scan/scripts/scan.py) records `ran`, `skipped` (`--no-secretlint`) or `failed` with a redacted reason for each scanner, in JSON `scanners` and `summary.failed_scanners` and in a Markdown "Scanners" list. Failures raise `ScannerError` from `run_tool()` (cannot start), `run_detect_secrets()` (exit status other than 0/1, invalid JSON, no `results` object), `setup_secretlint()` (`bun add` failed, no binary) and `get_git_tracked_files()` (`git ls-files` failed). `parse_secretlint_batch()` fails a batch on an exit status other than 0/1, exit 1 with empty output, invalid JSON or a non-list; other batches' findings are kept and the reason counts the batches not scanned.
- **Exit statuses.** `exit_status()` returns 2 when a requested scanner failed (outranking 1), else 1 when a finding needs review, else 0. An invalid path now exits 2 rather than 1, so exit 1 only means "findings need review"; argparse usage errors already exited 2. `main()` returns the status and `sys.exit(main())` raises it.
- **Placeholder judgement.** `classify()` now gets the detected value only. For detect-secrets, `detect_secrets_value()` finds the line substring whose SHA-1 equals `hashed_secret` (bounded candidates; lines over 1,000 characters are not searched). For secretlint, `secretlint_value()` slices the message's start/end columns. An unrecoverable value is `review-required`.
- **Docs.** [SKILL.md](../../secrets-scan/SKILL.md) and [classifying-findings.md](../../secrets-scan/references/classifying-findings.md) describe the outcomes, failure conditions and exit statuses; `--help` lists the exit statuses too.
- **Tests.** New [test_secrets_scan.py](../../tests/test_secrets_scan.py) runs `scan.main()` with fake `uvx`, `bun`, `git` and secretlint scripts first on `PATH`: a clean complete run (exit 0, Markdown and JSON), a requested skip (exit 0, reported as skipped), detect-secrets process failure and malformed JSON, secretlint setup failure, a skipped batch and a batch process failure (each exit 2 naming the scanner, both formats), a failure outranking findings, and a synthetic GitHub-token-shaped value beside `your_key_here` (review-required) next to a bare placeholder value (likely-false-positive) for both scanners. Three tests in [test_security_boundaries.py](../../tests/test_security_boundaries.py) follow the new signatures. Against the `main` scanner the new file fails 16 of 16.

Agent-owned follow-up for the steward: the secretlint rules (empty output with exit 0 is clean; columns are 0-based) follow secretlint's documented formats, but no real secretlint run checked them here: the tests stay offline and no scanner was installed. A real-scanner smoke run on `atom` would confirm both.

### Checks

- `uv run --no-project --with pytest --with typer --with rich pytest tests/test_secrets_scan.py tests/test_security_boundaries.py -q`: 43 passed.
- `uv run --no-project --with pyyaml python scripts/check_skill_metadata.py`: 48 frontmatters valid; `pytest tests/test_skill_metadata.py`: 8 passed.
- `ruff check` and `ruff format --check` on the changed Python files: clean, with no new findings in `tests/test_security_boundaries.py` (graylint is not installed here, so the comparison used ruff against the `main` copy).
- `uv run secrets-scan/scripts/scan.py --help`: exit 0, lists the exit statuses.
- `AGENTS.md` pre-commit checklist: the diff holds only synthetic values and example names.

### Memory record

- Pytest run of the two scanner test files (first run): started at once, no wait; admission MemAvailable 2616 MiB, final 2777 MiB; starting swap use 2562 MiB, growth 0; 8 s; exit 0.
- Same pytest run after the final edit: started at once, no wait; admission 2896 MiB, final 2914 MiB; starting swap use 2511 MiB, growth 0; 2 s; exit 0.
- A search of `~` and `/nix/store` for a local secretlint copy (`fd`, depth 6): started without the admission check, a mistake; stopped while running, by the agent after 120 s because its scope was too broad; MemAvailable 2900 MiB afterwards; swap readings not taken at start; not completed.
