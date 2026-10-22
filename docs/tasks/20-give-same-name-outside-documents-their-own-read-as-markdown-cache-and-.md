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
