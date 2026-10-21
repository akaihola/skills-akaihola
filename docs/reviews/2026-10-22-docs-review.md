# Documentation review, 2026-10-22

Reviewed current local main at `872546a` after the task’s start-state commit.
This is the documentation-only result for [checking changed skills against
their scripts][task]. No script, test, earlier review, task description or
agent bootstrap file was edited. Only the authorized lifecycle moves affect
the [tracker]. Findings below are drafts for the steward, not newly filed tasks.

## Coverage and method

Read the [repository README][readme], [agent guidelines][agents] and
[root backlog][backlog], then every selected skill instruction and all its
existing references. Compared names, positional arguments, options, defaults,
environment inputs, filesystem effects and examples with the implementations.

| Skill | Documents read | Implementation checked |
| --- | --- | --- |
| T3 coordination | [t3-start-thread/SKILL.md][t3-skill]; no references at baseline | [t3-start-thread/scripts/start_thread.py][t3-code], all five subcommands and protocol/resume tests |
| Receipt processing | [processing-scanned-receipts/SKILL.md][receipt-skill]; no references at baseline | [processing-scanned-receipts/process_receipts.py][receipt-code], including preview, cache and rename paths |
| ECB rates | [ecb-rates/SKILL.md][ecb-skill]; no references | [ecb-rates/fetch_ecb_rates.py][ecb-code] and its offline tests |
| Secret scans | [secrets-scan/SKILL.md][scan-skill] and [secrets-scan/references/classifying-findings.md][scan-ref] | [secrets-scan/scripts/scan.py][scan-code], both scanner paths and report construction |
| Email management | [himalaya-email-manager/SKILL.md][mail-skill], [himalaya-email-manager/references/scripts.md][mail-ref], [himalaya-email-manager/references/troubleshooting.md][mail-trouble] | [summary][summary-code], [search][search-code], [read][read-code], [save][save-code] and [delete][delete-code] |
| Transcription | [youtube-transcription/SKILL.md][yt-skill] and [youtube-transcription/references/assemblyai_options.md][yt-ref] | [youtube-transcription/scripts/transcribe_video.py][yt-code], including SDK configuration and file selection |
| Markdown reading | [read-as-markdown/SKILL.md][markdown-skill]; no references at baseline | [read-as-markdown/scripts/read_as_markdown.py][markdown-code], cache, backend and CLI paths |
| Library | [library/SKILL.md][library-skill]; no references directory | No bundled program: read the [catalog][catalog], [library backlog][library-backlog] and all eight cookbooks: [add], [install], [list], [push], [remove], [search], [sync], [use] |

Also inspected metadata validation, the relevant CI workflows and existing
tests. The [companion email README][mail-readme], [JMAP instructions][jmap]
and [adoption proposal][adoption] provided context for stale cross-references.
Earlier reviews were consulted for overlap, without rewriting their findings.

No skill contacted a live service, mailbox or account. Runtime probes ran
with networking disabled by `unshare -rn` and UV offline. Dependencies came
from the existing local package cache. No scan or external credential
verification was run. File and line references identify credential-related
evidence; values are not reproduced.

## Changes by document

- **[Repository README][readme]:** mark the skills table as a selection, add
  the reviewed skills missing from it, remove the absent credential-check
  entry, and describe Power as a webshop search. Update T3 coordination wording,
  optional scripts, discovery setup and reference links. Matches the tracked
  skill inventory, [Power’s search implementation][power-code],
  [T3’s helper][t3-code], [library cookbooks][use], and
  [metadata validator][metadata-code]/[metadata workflow][metadata-ci].

- **[Agent guidelines][agents]:** clarify that discovery symlinks cover selected
  skills and that scripts/references are optional. Preserve the actual example
  layout and link trackers/backlogs. Replace a test-address example with a
  reserved example domain. Matches the Git index’s relative symlink entries,
  [symlink checker][symlink-code], and the [tracker’s rules][tracker].

- **[Root backlog][backlog]:** distinguish the existing workspace-specific
  JMAP reference from the proposed portable implementation, and mark tracker
  adoption as partial. Matches the [JMAP instructions][jmap], absence of a
  bundled JMAP helper, the existing [tracker][tracker] and [agent guidelines][agents].
  The older proposal still requires reconciliation; its state was not moved.

- **[T3 skill][t3-skill] and new [T3 helper reference][t3-ref]:** retain operation
  routing and model preferences in the entry point; move detailed commands,
  delivery/resume rules and historical fork observations behind a reference.
  State that parent/settings inputs are mutually exclusive, settings replace
  rather than merge, shared checkouts reject both branch flags, and dry runs
  authenticate. Matches `main()`, `start()`, `send()`, `settle()`,
  `save_record()`, `submit()` and `submit_message()` in [the helper][t3-code].
  Label the old fork probe as historical rather than current capability evidence.

- **[Receipt skill][receipt-skill] and new [receipt review reference][receipt-ref]:**
  document first-image OCR, original-stem cache keys, full-basename duplicate
  matching and overwrite/rerun limitations. Locate `payee_short` in JSON
  rather than generated text; move correction/output examples to the reference.
  Matches `extract_jpg_from_pdf()`, `process_one()`, `make_base_name()`,
  `unique_name()`, `preview_receipts()`, `make_receipt_text()` and the write
  loop in [the receipt script][receipt-code].

- **[Secret-scan skill][scan-skill] and [classification reference][scan-ref]:**
  replace copied external CLI/plugin tables and unsafe raw-output examples
  with the wrapper’s actual interface. Clarify always-disabled verification,
  detect-secrets-only untracked-file scanning, sanitized JSON fields,
  substring classification and incomplete-scan exit behaviour. Matches
  `run_detect_secrets()`, `get_git_tracked_files()`, `run_secretlint()`,
  `is_placeholder()`, `build_combined()` and `main()` in
  [the scanner][scan-code]. The wrapper has no baseline/audit workflow.

- **[Email skill][mail-skill]:** shorten to operation selection, link the detailed
  reference, identify the fixed account setting, correct search/summary limits
  and describe noninteractive deletion. Mark attachment vision/replacement as
  separate work. Matches the five wrappers listed in Coverage, particularly
  `get_email_summary()`, `search_emails()`, `save()` and `delete_email()`.

- **[Email script reference][mail-ref]:** remove message-content examples;
  correct summary output and verbose flag, search page/result limits, read
  formats/default, JSON-stream limitation, save attachment defaults, filenames
  and output-path handling. Matches `get_email_summary()` in [summary][summary-code],
  `search_emails()` in [search][search-code], `read()` and
  `format_json_output()` in [read][read-code], and `save()`,
  `generate_filename()`, `_determine_output_path()`,
  `_process_attachments()` and `_download_attachments_internal()` in [save][save-code].
  Record the actual limited effect of `--preserve-html`.

- **[Email troubleshooting][mail-trouble]:** remove fixed host/keyring/version
  assumptions and the instruction to print all configuration. Explain fixed
  account selection, local filtering, safe help probes, output choices and
  side effects. Matches each wrapper’s `ACCOUNT`, PEP 723 metadata and CLI,
  plus `attachment download -d` in [the save helper][save-code].

- **[Transcription skill][yt-skill] and [integration reference][yt-ref]:** describe
  a single positional input, English configuration, declared dependencies,
  progress plus plain-text output and a fixed output file. Remove unsupported
  feature recipes, pricing percentages, non-English accuracy claims and implied
  Markdown generation. Explicitly identify the absent help parser and unresolved
  credential/file-selection concerns. Matches `main()`,
  `get_youtube_audio()` and `transcribe_with_assemblyai()` in
  [the script][yt-code]; external SDK behaviour remains an open question below.

- **[Markdown-reading skill][markdown-skill] and new [cache reference][markdown-ref]:**
  document fallback to the current directory, extension-preserving cache names,
  basename-only external paths, ignore-file writes, handled-error exit status,
  and the single implemented toolchain step. Move output/schema/backend detail
  behind a reference. Matches `compute_cache_paths()`, `convert()`,
  `ensure_gitignore_entry()`, `pdftotext_converter()` and `main()` in
  [the converter][markdown-code].

- **[Library skill][library-skill]:** identify the implementation as agent-run
  cookbooks and a catalog, not an automatic installer or parser. Correct local
  symlink versus remote-copy behaviour, scope repository pulls, identify
  checkout assumptions as prose rather than environment-variable support,
  and preserve the caller’s workspace before changing directories. Matches
  [use], [sync], [install], the [catalog] and [library backlog][library-backlog].
  Keep broader cookbook repairs as a draft below.

The [ECB skill][ecb-skill] needed no edit: positional year/output, fixed 2025
default, CSV ordering and columns, dependency and test commands match
[its script][ecb-code] and help. All eight entry points remain valid YAML;
the larger ones now disclose detail through references.

## Validation

- **Metadata:** the required command passed, validating 48 frontmatters.
- **CLI examples:** 15 supported help probes passed: T3 root plus
  `inspect/start/send/settle/resume`; receipt, ECB, scanner and Markdown
  helpers; all five email wrappers. Examples were compared with those parsers
  and their implementation defaults.
- **Unsupported probes:** transcription has no help parser; source inspection
  replaced execution. Library has no executable CLI. No live operation was
  substituted for either.
- **Regression tests:** 181 passed across metadata, security boundaries, T3,
  receipt, ECB and email suites. Transport, scanner, conversion and mailbox
  boundaries use existing mocks/synthetic inputs; networking was disabled.
- **Scope:** no script/test edits, no new issues or messages, and no changes to
  task descriptions, older reviews or the agent bootstrap file.
- **Pre-commit privacy checklist:** reviewed added text for personal names,
  real email addresses, identifying organizations, private message content and
  financial/proprietary data. Examples use generic descriptors and reserved
  domains; no code or test fixture changed. Deleted legacy examples are not
  repeated in this report.
- **Final document checks:** relative links, heading lengths, diff whitespace
  and documentation-only scope passed: 18 changed/new Markdown files and
  137 relative links. The committed-symlink checker also passed.

Reproduction commands, from the repository root:

```bash
export UV_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
unshare -rn uv run --no-project --with pyyaml python scripts/check_skill_metadata.py
unshare -rn uv run --no-project --with pytest --with typer --with rich --with pyyaml --with websocket-client --with defusedxml pytest -p no:cacheprovider tests/test_skill_metadata.py tests/test_security_boundaries.py t3-start-thread/tests processing-scanned-receipts/tests ecb-rates/tests himalaya-email-manager/tests -q
# Repeat for each audited script/subcommand; never use this on transcription.
unshare -rn uv run --offline --no-project --script t3-start-thread/scripts/start_thread.py start --help
git diff --check
```

## Integration evidence

The start move was committed on shared main as `872546a`. Documentation
commit `0a087d2` was fast-forwarded to main before completion commit
`21d0ffd`. A fresh Hai read confirmed `Completed / Accepted` with
`accepted: false`, 18 unique issues and resolving detail links. The shared
checkout was clean. The task branch and worktree were retained.
No remote push, new issue, thread launch or coordination message was needed.

## Resource record

Every command used a memory admission guard: wait up to 600 seconds for
2,048 MiB available; after that allow the 1,536 MiB fallback, otherwise do not
run. Running process groups were bounded by timeouts and monitored every
0.2 seconds; less than 1,024 MiB available or swap growth above 512 MiB would
stop the process group. No memory stop or fallback was needed. Heavy commands
ran sequentially. Measurements below describe resources, not command output.

| Command | Outcome | Wait (s) | Admission / final available (MiB) | Starting swap / growth (MiB) | Elapsed (s) | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Baseline rebase and scoped file inventory | started at once | 0.0 | 2912 / 2905 | 2426 / 0 | 0.2 | exit 0 |
| Recent-main Git history and document inventory | started at once | 0.0 | 2944 / 2944 | 2426 / 0 | 0.2 | exit 0 |
| 15 sequential offline help commands | started at once | 0.0 | 2913 / 2888 | 2414 / 0 | 6.8 | exit 0 |
| Required metadata command | started at once | 0.0 | 2903 / 2895 | 2402 / 0 | 0.4 | exit 0 |
| Targeted pytest command above | started at once | 0.0 | 2918 / 2855 | 2402 / 0 | 3.6 | exit 0 |
| Local document/link inventory, diff and symlink checks | started at once | 0.0 | 2846 / 2845 | 2398 / 0 | 0.6 | exit 0 |

The task description is intentionally unchanged. This review holds the detailed
execution record to honour the documentation-only constraint.

## Draft issues

These are proposals for steward review; none was filed or messaged elsewhere.

- **D1 — Verify and repair transcription credentials/options.** Evidence:
  [youtube-transcription/scripts/transcribe_video.py][yt-code], `transcribe_with_assemblyai()` at lines 45–50,
  creates a local Settings object without passing it into Transcriber; language
  is fixed to English, and `main()` has no help parser. It is unclear whether
  the installed SDK independently reads the environment.

  **Recommendation:** inspect the installed SDK’s supported credential path,
  wire it explicitly, add offline credential-wiring/help tests and choose an
  explicit language/output contract. Do not infer service failure from this
  static review. The help portion overlaps [the earlier parser finding][old-help].

- **D2 — Make transcription files private and invocation-specific.** Evidence:
  [youtube-transcription/scripts/transcribe_video.py][yt-code], `get_youtube_audio()` at lines 36–39 selects
  the newest shared temporary MP3; `main()` at lines 93–94 overwrites a fixed
  transcript file.

  **Recommendation:** continue [the existing temporary-file finding][old-temp]
  with private per-run files, exact download identity and an output option.
  This is an overlap, not a new independent issue.

- **D3 — Report incomplete secret scans as failures.** Evidence:
  [secrets-scan/scripts/scan.py][scan-code], `run_detect_secrets()` at lines 128–139,
  `run_secretlint()` at lines 224–231 and `main()` at lines 455–475 can turn
  scanner/setup/parse failures into an empty report and exit 0. Placeholder
  classification also accepts a substring anywhere on a line.

  **Recommendation:** track each scanner’s completion explicitly, fail incomplete
  coverage, and keep placeholder matches advisory. Add fake-scanner tests for
  process failure, malformed JSON and a real-format value beside a placeholder.

- **D4 — Decide the email wrappers’ account and output contract.** Evidence:
  all five wrappers have a fixed `ACCOUNT` and no override. [Summary][summary-code]
  uses date prefixes and one default page; [search][search-code] filters one
  page locally. [Read][read-code], lines 298–366, does not change body selection
  with `--preserve-html` and prints status alongside JSON.

  **Recommendation:** choose configurable account selection, explicit pagination
  and summary-window semantics, and a clean JSON output mode. Either implement
  HTML preservation where meaningful or remove the misleading flag. Keep tests
  offline with fake Himalaya responses.

- **D5 — Resolve receipt rerun and destination collisions.** Evidence:
  [processing-scanned-receipts/process_receipts.py][receipt-code], `process_one()` keys cache files by
  the original stem; the write loop at lines 358–367 does not protect existing
  destinations. Renamed inputs lose the old cache lookup.

  **Recommendation:** continue [the existing receipt-rerun finding][old-receipt]
  with explicit overwrite/correction preservation and stable cache identity.
  The corrected docs describe present behaviour without choosing that policy.

- **D6 — Decide external-document cache identity.** Evidence:
  [read-as-markdown/scripts/read_as_markdown.py][markdown-code], `compute_cache_paths()` at lines
  187–205 uses only the basename outside the workspace; `check_cache()`
  uses mtime and size. Different external files can share a location and even
  satisfy the same fast-path check. `main()` also returns success for handled
  conversion errors.

  **Recommendation:** include source identity or verify content for ambiguous
  paths, and decide whether error objects should produce nonzero CLI status.
  Test same-name external documents and failure status without real converters.

- **D7 — Finish the library cookbook contract.** Evidence: [use], [list],
  [remove] and [sync] compute workspace context after a persistent `cd` to the
  library; [use] parses a remote branch but clones the default branch, omits
  target-directory creation, and applies skill-directory installation to agent
  and prompt entries whose intended layout is unspecified.

  **Recommendation:** preserve workspace context in every cookbook, create
  destinations, honour the source ref, and decide file-versus-directory handling
  before populating agents/prompts. Reuse the [existing library backlog][library-backlog]
  for script-backed validation rather than creating duplicate proposals.

- **D8 — Reconcile adjacent stale documentation and plans.** Evidence:
  [himalaya-email-manager/README.md][mail-readme] still promises a rolling
  24-hour summary, server-side filtering and the older attachment location;
  it is outside the specifically requested skill/reference corpus. The
  [adoption proposal][adoption] still describes distributed backlog queues
  while the [tracker] is canonical. [jmap/SKILL.md][jmap] points to an
  unbundled workspace helper and fixed account/tunnel assumptions.

  **Recommendation:** align the companion README with the five wrappers,
  reconcile the adoption proposal with implemented tracker rules, and extend
  the existing [portable JMAP proposal][backlog] rather than filing duplicates.
  JMAP overlaps [the earlier portability finding][old-jmap]. Preserve the
  protected task file until that follow-up is authorized.

[task]: ../tasks/18-check-skills-akaihola-s-readme-and-the-skills-changed-since-10-19-agai.md
[tracker]: ../../TASKS.md
[readme]: ../../README.md
[agents]: ../../AGENTS.md
[backlog]: ../../BACKLOG.md
[t3-skill]: ../../t3-start-thread/SKILL.md
[t3-code]: ../../t3-start-thread/scripts/start_thread.py
[t3-ref]: ../../t3-start-thread/references/helper.md
[receipt-skill]: ../../processing-scanned-receipts/SKILL.md
[receipt-code]: ../../processing-scanned-receipts/process_receipts.py
[receipt-ref]: ../../processing-scanned-receipts/references/review.md
[ecb-skill]: ../../ecb-rates/SKILL.md
[ecb-code]: ../../ecb-rates/fetch_ecb_rates.py
[scan-skill]: ../../secrets-scan/SKILL.md
[scan-code]: ../../secrets-scan/scripts/scan.py
[scan-ref]: ../../secrets-scan/references/classifying-findings.md
[mail-skill]: ../../himalaya-email-manager/SKILL.md
[mail-ref]: ../../himalaya-email-manager/references/scripts.md
[mail-trouble]: ../../himalaya-email-manager/references/troubleshooting.md
[mail-readme]: ../../himalaya-email-manager/README.md
[summary-code]: ../../himalaya-email-manager/scripts/email-summary.py
[search-code]: ../../himalaya-email-manager/scripts/email-search.py
[read-code]: ../../himalaya-email-manager/scripts/email-read.py
[save-code]: ../../himalaya-email-manager/scripts/email_save.py
[delete-code]: ../../himalaya-email-manager/scripts/email-delete.py
[yt-skill]: ../../youtube-transcription/SKILL.md
[yt-code]: ../../youtube-transcription/scripts/transcribe_video.py
[yt-ref]: ../../youtube-transcription/references/assemblyai_options.md
[markdown-skill]: ../../read-as-markdown/SKILL.md
[markdown-code]: ../../read-as-markdown/scripts/read_as_markdown.py
[markdown-ref]: ../../read-as-markdown/references/cache.md
[library-skill]: ../../library/SKILL.md
[catalog]: ../../library/library.yaml
[library-backlog]: ../../library/BACKLOG.md
[add]: ../../library/cookbook/add.md
[install]: ../../library/cookbook/install.md
[list]: ../../library/cookbook/list.md
[push]: ../../library/cookbook/push.md
[remove]: ../../library/cookbook/remove.md
[search]: ../../library/cookbook/search.md
[sync]: ../../library/cookbook/sync.md
[use]: ../../library/cookbook/use.md
[power-code]: ../../power/scripts/search.py
[metadata-code]: ../../scripts/check_skill_metadata.py
[metadata-ci]: ../../.github/workflows/test-skill-metadata.yml
[symlink-code]: ../../.github/scripts/check_symlinks.py
[jmap]: ../../jmap/SKILL.md
[adoption]: ../tasks/adopt-task-tracking-principles.md
[old-help]: 2026-10-19-skills-review.md#d7-parse-help-before-reading-private-data-or-performing-work
[old-jmap]: 2026-10-19-skills-review.md#d13-parameterize-jmap-assumptions-amend-the-existing-proposal
[old-temp]: 2026-10-21-security-review.md#s13-transcription-and-watch-history-use-shared-tmp
[old-receipt]: 2026-10-21-security-review.md#s8-receipt-reruns-overwrite-corrected-results
