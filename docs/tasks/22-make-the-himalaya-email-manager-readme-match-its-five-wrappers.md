Steward issue, 2026-10-22 03:00 refill. Goal: agentic-leverage (skills-akaihola is tier 2). Estimated 30 min. Source: draft D8 of [the 2026-10-22 docs review](../reviews/2026-10-22-docs-review.md#draft-issues).

`himalaya-email-manager/README.md` still promises a rolling 24-hour summary, server-side filtering and an older attachment location. The five wrapper scripts do otherwise: the summary uses date prefixes and one default page, search filters one page locally, and the save script writes elsewhere. The README was outside the docs review's corpus, so it wasn't fixed there. Separately, `jmap/SKILL.md` points to a workspace helper that isn't bundled and assumes a fixed account and tunnel.

## What to do

1. Make the README describe what the five wrappers do on `main`, and link `SKILL.md` and `references/scripts.md` rather than repeat them.
2. Add the `jmap/SKILL.md` observation to the existing portable-JMAP proposal in [the backlog](../../BACKLOG.md) as an amendment; don't file a new proposal and don't edit `jmap/`.

## Constraints and acceptance

- Documentation only. Leave `docs/tasks/adopt-task-tracking-principles.md`, earlier reviews and the scripts as they are.
- Before merging, run the checks the Rules and `AGENTS.md` ask for.
- Handoff: one or two sentences; detail goes in this task record.
- Acceptance: each README statement about behaviour names the wrapper and option it matches in this task record; the backlog amendment is on `main`.

Tracker: [the skills-akaihola tracker](../../TASKS.md).


## Task record

Implemented 2026-10-22. The start move was committed on shared `main` as
`d4d6c92`, left the tracker clean, and was incorporated by rebasing the task
worktree. Implementation changes only [the README], [the backlog] and this
record. Scripts, earlier reviews, the adoption proposal and [the JMAP skill]
are unchanged.

### README behaviour evidence

Every behaviour in [the README], including its quick-start examples, maps to
these wrappers and options, checked against `main` after the start rebase:

- **Shared setup:** all five wrappers below declare Python `>=3.13` and
  dependencies in PEP 723 metadata. Each invokes `himalaya` with its fixed
  `ACCOUNT`, with no account-selection option. Their CLI entry points handle
  `--help` before mailbox calls. `uv run` reads the metadata; Himalaya setup
  guidance is linked through [troubleshooting].
- **Summary:** [summary wrapper], no operation options in the example;
  `get_email_summary()` calls `envelope list` once per INBOX/Sent without
  page or page-size arguments. Its `startswith(today.isoformat())` and
  `startswith(yesterday.isoformat())` filters explain the date-prefix window.
  There is no elapsed-time cutoff or pagination loop.
- **Search filters:** [search wrapper], `--folder` defaults to INBOX;
  `--from` and `--subject` apply substring filters locally, and
  `--date-start` / `--date-end` compare date prefixes inclusively. Every filter
  must pass before appending the envelope (AND). No body-search option exists.
- **Search bounds:** [search wrapper], `--limit` defaults to 20 and is capped
  by `MAX_LIMIT = 100`. The default request uses `--page-size 500`;
  `--no-limit` ignores the numeric limit and uses `--page-size 10000`.
  Both modes call `run_himalaya()` once. The example's `--from` and `--limit 5`
  match these options and use a reserved example-domain address.
- **Read:** [read wrapper], numeric `message_id` and `--format` default `text`,
  with allowed values `markdown`, `json`, `raw`. The example uses
  `--format markdown`. The README says display, since even JSON includes
  surrounding status output; details remain in [the script reference].
- **Save output:** [save wrapper], numeric `message_id`, `--format` default
  `markdown` with `text` and `json` alternatives. `--output` defaults to
  `None`; `_determine_output_path()` then uses the current directory.
- **Save attachments:** [save wrapper], `--download-attachments` defaults
  true; `_process_attachments()` selects the saved email's parent plus
  `<message-id>-attachments/` unless `--attachment-dir` is supplied.
  `--no-download-attachments` skips downloads, as the quick-start example does.
- **Save replacement:** [save wrapper], `--overwrite` defaults false;
  `_handle_existing_file()` prompts when the email file exists and overwrite
  is disabled. Enabling `--overwrite` bypasses that prompt.
- **Delete:** [delete wrapper], numeric `message_id`, `--execute` defaults
  false. `get_message()` reads a live preview before the dry-run return.
  Only `--execute` reaches deletion, and `is_interactive()` gates confirmation
  on `stdin.isatty()`. The example omits `--execute`; authorization guidance
  matches [the skill instructions].

### Backlog amendment

Amended the existing JMAP mail skill proposal in [the backlog], rather than
creating a proposal. It now explicitly records the unbundled workspace-relative
helper, fixed account and tunnel assumption, with helper packaging,
configurable account/base URL and tunnel prerequisites to verify during the
portable skill work. No identifying account or workspace names were copied.

### Verification

- `python -m pytest himalaya-email-manager/tests tests -q`: **85 passed**.
- `python scripts/check_skill_metadata.py`: **48 valid skill frontmatters**.
- `python .github/scripts/check_symlinks.py`: **passed**.
- All five wrappers invoked with `--help`: **passed**, without mailbox calls.
  Used the existing shared virtual environment's Python, with installed
  dependencies, rather than fetching another environment through `uv`.
- `git diff --check`: **passed**.
- Full [topology check]: **exit 1**, matching only five pre-existing task
  documents: [scanner task], [protocol task], [settle task], [evidence task]
  and [adoption proposal]. These are unchanged and outside scope. The changed
  documents contain no topology matches.
- Reviewed the complete diff against the PII checklist: no real names,
  addresses, organizations or message content added. Example address uses
  `example.org`. README and backlog links resolve and use reference style.
- Hai loaded the complete tracker: **22 unique stable IDs**, no duplicate
  detail references, and **22 resolving detail links**. Rechecked before
  tracker completion; acceptance remains unchecked.

### Memory record

Checks ran serially under a temporary external guard with a 600-second
admission window, 2048 MiB normal admission, 1536 MiB fallback and a 300-second
runtime timeout. The guard checks memory every 0.1 seconds and terminates the
process group below 1024 MiB available or above 512 MiB swap growth. No command
was stopped. All waits below were 0.00 seconds; each outcome is **started at
once**. Readings are MiB; elapsed time is seconds.

| Command | Admission / final available | Starting swap / growth | Elapsed | Status |
| --- | --- | --- | --- | --- |
| `python -m pytest himalaya-email-manager/tests tests -q` | 2589 / 2535 | 2369 / 6 | 3.32 | exit 0 |
| `python scripts/check_skill_metadata.py` | 2576 / 2576 | 2374 / 0 | 0.20 | exit 0 |
| `python .github/scripts/check_symlinks.py` | 2571 / 2565 | 2374 / 0 | 0.10 | exit 0 |
| Bash loop invoking each wrapper with `--help` | 2556 / 2484 | 2374 / 10 | 2.66 | exit 0 |
| Topology `git grep -lIE` with the CI pattern and exclusion | 2484 / 2484 | 2384 / 0 | 0.22 | exit 1 |

### Merge and completion

Fast-forwarded shared `main` to implementation commit `0f0280d`, including the
backlog amendment. Then moved this issue through Hai to Completed / Accepted
in `73164a0`, leaving `[ ]` for user acceptance. The final Hai read confirmed
22 unique issues and resolving detail links; shared `main` had no uncommitted
tracker changes. The worktree and branch are retained. The only check failure
is the pre-existing topology debt documented above; no implementation
acceptance conditions remain unmet.

[the README]: ../../himalaya-email-manager/README.md
[the backlog]: ../../BACKLOG.md
[the JMAP skill]: ../../jmap/SKILL.md
[troubleshooting]: ../../himalaya-email-manager/references/troubleshooting.md
[summary wrapper]: ../../himalaya-email-manager/scripts/email-summary.py
[search wrapper]: ../../himalaya-email-manager/scripts/email-search.py
[read wrapper]: ../../himalaya-email-manager/scripts/email-read.py
[save wrapper]: ../../himalaya-email-manager/scripts/email_save.py
[delete wrapper]: ../../himalaya-email-manager/scripts/email-delete.py
[the script reference]: ../../himalaya-email-manager/references/scripts.md
[the skill instructions]: ../../himalaya-email-manager/SKILL.md
[topology check]: ../../.github/workflows/check-topology.yml
[scanner task]: 19-make-secrets-scan-fail-when-a-requested-scanner-doesn-t-finish.md
[protocol task]: 6-make-the-t3-start-thread-helper-speak-t3-s-v2-protocol-as-well-as-v1.md
[settle task]: 7-add-a-settle-command-to-the-t3-start-thread-helper.md
[evidence task]: 8-gather-acceptance-evidence-for-the-2-review-queue-items.md
[adoption proposal]: adopt-task-tracking-principles.md
