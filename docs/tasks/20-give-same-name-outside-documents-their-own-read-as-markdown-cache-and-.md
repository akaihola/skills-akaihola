Steward issue, 2026-10-22 03:00 refill. Goal: agentic-leverage (skills-akaihola is tier 2). Estimated 1 h. Source: draft D6 of [the 2026-10-22 docs review](../reviews/2026-10-22-docs-review.md#draft-issues).

`read-as-markdown` can return another document's Markdown. In `read-as-markdown/scripts/read_as_markdown.py` on `main` (`278d0d1`), `compute_cache_paths()` uses only the file name for a source outside the workspace, so `/a/report.pdf` and `/b/report.pdf` share `.cache/markdown/report.pdf.md`, and `check_cache()`'s mtime-and-size test can let the second file pass the fast path. `main()` also exits 0 when a conversion failed and was reported as an error object.

## What to do

1. Give sources outside the workspace a stable identity in their cache path, for example a short hash of the resolved absolute path as a directory. Leave the paths of sources inside the workspace as they are, so existing caches stay valid.
2. Make the command exit non-zero when any requested conversion failed, keeping the JSON error object it prints now.
3. Update `read-as-markdown/SKILL.md` where it describes the cache layout or the exit status.
4. Add offline tests: two same-name documents in different directories outside the workspace get different cache paths and their own Markdown; a failed conversion exits non-zero. Use fake converters; no real PDF or DOCX tools.

## Constraints and acceptance

- Keep the content-hash index's trust rules as they are: the 2026-10-21 security review's S5 (a planted cache index) is a separate security decision, not part of this issue.
- Before merging, run the tests and checks the Rules and `AGENTS.md` ask for.
- Memory: before each command, wait up to 10 minutes for `MemAvailable` of at least 2 GiB; if it doesn't come, start the command anyway when at least 1.5 GiB is available. Stop a running command when `MemAvailable` falls below 1 GiB or swap grows by more than 512 MiB. Run one heavy command at a time, and bound any background job you start.
- Handoff: a short outcome and the checks run; detail goes in this task record.
- Acceptance: the two tests pass, in-workspace cache paths are unchanged (a test shows it), and SKILL.md matches the code.

Tracker: [the skills-akaihola tracker](../../TASKS.md).


## Task record

Implemented 2026-10-22 in the isolated task worktree.

- **Cache identity:** [the converter] preserves workspace-relative paths and
  puts external documents under `_external/<path-hash>/<filename>.md` with
  matching metadata. The hash is the first 16 hex digits of SHA-256 of the
  resolved absolute path. Symlink aliases resolve to the same identity.
- **Exit status:** `main()` returns 1 for a handled JSON error and 0 for success;
  the script entry point propagates it with `sys.exit(main())`.
- **Compatibility:** the content-hash index and its trust rules are unchanged.
  Old external caches remain available through content-hash lookup; existing
  workspace-relative caches still pass the fast path.
- **Documentation:** [the skill] and [cache reference] describe the layout and
  exit statuses.
- **Regression evidence:** [the offline tests] use two different documents with
  equal sizes and mtimes, verify separate Markdown and metadata paths and cache
  hits, check resolved aliases, reuse a pre-existing in-workspace cache, and run
  the actual CLI with fake pandoc executables for success and failure. Against
  the original code, the two bug regressions failed and two compatibility/success
  cases passed. No real document converter or network was used.

### Checks and review

- `pytest tests/test_read_as_markdown.py tests/test_security_boundaries.py -q`:
  31 passed after the fix, including the existing confinement and rename tests.
- `pytest tests -q`: all 55 root tests passed. These runs used the existing shared
  checkout's virtual environment, without installing dependencies.
- `python scripts/check_skill_metadata.py`: all 48 skill frontmatters valid.
- `python .github/scripts/check_symlinks.py`: passed.
- `ruff check tests/test_read_as_markdown.py`: passed after fixing test style.
  Direct lint of the converter still reports 16 pre-existing findings; comparing
  rule/message counts against `main` found zero additions (17 findings before).
  Graylint is unavailable, so the comparison used Ruff JSON output.
- `ruff format --check` on both changed Python files: passed.
- `git diff --check`: passed. Reviewed the complete implementation and test diff
  against the requirements and the PII checklist; only synthetic document content
  and generic examples were added. The index implementation was not changed.
- Hai loaded all 22 issues with unique stable IDs; every numbered detail link
  resolves. The required start move was committed on shared `main` as `af7aa44`
  and left no uncommitted tracker changes. The worktree was rebased onto it.
- **Existing check failure:** the repository topology check fails on five
  pre-existing task documents. Comparing matched filenames with `main` confirms
  this change adds no failure. These unrelated documents were left untouched;
  this is an agent-owned follow-up for the steward, not an owner decision.

### Memory record

Test commands ran serially under a memory monitor with a 300-second timeout, a
600-second admission window, process-group termination below 1024 MiB available
or above 512 MiB swap growth, and Bash subprocess environments. The following
are the guarded test commands; no heavy command was stopped or skipped.

- `pytest tests/test_read_as_markdown.py -q` (before the fix): **started at once**,
  wait 0.00 s; admission MemAvailable 2926 MiB, final 2911 MiB; starting swap
  2385 MiB, growth 0 MiB; elapsed 2.13 s; exit 1 (two expected regressions).
- `pytest tests/test_read_as_markdown.py tests/test_security_boundaries.py -q`:
  **started at once**, wait 0.00 s; admission 2915 MiB, final 2914 MiB; starting
  swap 2384 MiB, growth 0 MiB; elapsed 2.88 s; exit 0.
- `pytest tests -q`: **started at once**, wait 0.00 s; admission 2870 MiB, final
  2876 MiB; starting swap 2384 MiB, growth 0 MiB; elapsed 2.51 s; exit 0.

### Merge and completion

Implementation commit `5fb1387` was fast-forward merged into `main`. Completion
was recorded afterward in `649f458`, with acceptance left unchecked. A fresh Hai
read confirms 22 unique issues, resolving detail links and the completed state;
the tracker is clean. The task branch and worktree are retained.

[the converter]: ../../read-as-markdown/scripts/read_as_markdown.py
[the skill]: ../../read-as-markdown/SKILL.md
[cache reference]: ../../read-as-markdown/references/cache.md
[the offline tests]: ../../tests/test_read_as_markdown.py
