# Documentation recheck, 2026-10-25

Reviewed local `main` at `f35e0f6` for [the source-change recheck][task].
The source baseline is `278d0d1`; the [earlier review] remains unchanged.
Six instruction/reference documents needed corrections or deduplication.
No production code or tests changed. The draft below is for the steward;
no issue was filed and no thread was launched, messaged or settled.

## Source changes

The requested inventory returns exactly seven commits, oldest first:

```bash
git log --no-merges --reverse 278d0d1..main -- . ':!docs' ':!*.md'
```

| Commit | Observable change |
| --- | --- |
| `7e7a300` | [Scanner][scan-code]: adds per-scanner `ran`/`skipped`/`failed` outcomes and `summary.failed_scanners` to reports. Requested scanner/setup/batch failures and invalid paths exit 2, ahead of review-required findings (1) and complete clean scans (0). Failure reasons omit raw stderr; incomplete scans no longer print the clean banner. Classification examines the recovered detected value, not other words on its line; unrecoverable values need review. Flags, scanner installation files and report destinations are unchanged. |
| `5fb1387` | [Converter][cache-code]: external source paths use a directory keyed by the first 16 SHA-256 hex digits of the resolved absolute path, with extension-preserving Markdown and metadata names. In-workspace paths remain unchanged; old external entries can still supply content-hash hits. JSON `error` results now exit 1, successes 0. Flags, default backends, index and ignore-file writes are unchanged. |
| `a671c38` | [T3 helper][t3-code]: the first socket requests V2; rejected tickets/upgrades fail without a second ticket or V1 retry. Launch and message RPCs use V2, while durable records retain V1-shaped commands and original IDs. Activity comes from V2 fields; `messageTurnId` comes from `runId`. CLI flags, settings and settlement refusals stay unchanged. |
| `b293300` | [T3 helper][t3-code]: launch/send recovery shares `submit()` and saves acknowledgements before checking results. A newly acknowledged launch now needs both its thread and initial message to be visible. Missing results retain the accepted record and fail; resume never replays an acknowledged command. Existing IDs, record paths and output keys are preserved. |
| `b10db5b` | [T3 helper][t3-code]: message checks read projections without another shell read; launches reuse the observed shell, sends fetch a shell for their summary. Fresh launches/sends use five rather than six RPCs; a visible launch resume uses two rather than three. Fresh post-dispatch observations, summary precedence, archived lookup and settlement refreshes remain intact. No user command, file or failure-policy change. |
| `32cb1fc` | [T3 tests][t3-tests] only: duplicate direct handoff fakes become shared V2 wire fixtures. No runtime command, flag, default, file, message or failure behavior changes. |
| `fe72104` | [T3 helper][t3-code]: omitted `--url` discovers the selected base directory's runtime `origin`, with loopback fallback. Local session issuance now trusts the matching recorded origin as well as loopback; other origins require an existing bearer token. `--base-dir` controls discovery and CLI state. Explicit URLs and saved resume endpoints remain authoritative; no new flags or written files. |

## Documents read

Read all eight requested documents in full and compared their runnable examples,
flags, defaults, filesystem effects, outputs and failures with current code:

- **Repository:** [repository README][readme] and [agent guidelines][agents]. Neither needs a
  change for these commits. The skill inventory, installation and tracker
  rules still match. The agent guidelines name no test command; the README
  requires metadata validation, and this issue adds the three regression suites.
- **T3 coordination:** [t3-start-thread/SKILL.md][t3-skill] and
  [t3-start-thread/references/helper.md][t3-ref]. Checked the complete helper,
  per-commit changes and V2/discovery/recovery tests.
- **Document conversion:** [read-as-markdown/SKILL.md][cache-skill] and
  [read-as-markdown/references/cache.md][cache-ref]. Checked the complete
  converter and cache identity/CLI tests.
- **Secret scanning:** [secrets-scan/SKILL.md][scan-skill] and
  [secrets-scan/references/classifying-findings.md][scan-ref]. Checked scanner
  changes, report/CLI paths and synthetic scanner tests.

These are the only reference files in the three selected skills. Also read
[the metadata workflow][metadata-ci], [topology workflow][topology-ci],
[symlink checker][symlink-code] and [security regression tests][security-tests]
to establish validation scope.

## Changes by document

- **[t3-start-thread/SKILL.md][t3-skill]:** replace the private host-specific
  preference link with the same requirement to consult available user
  preferences. Preserve explicit model options and saved-setting verification.
  Link the helper's settings section instead of repeating its parent/file
  exclusivity and replacement rules, which match `SETTINGS`, `main()` and
  `start()` in [the helper][t3-code]. Replace the remote-only advice for
  `--url`/token overrides with a link to discovery/authentication, matching
  `fe72104` (`Server.__init__()`).
- **[t3-start-thread/references/helper.md][t3-ref]:** replace the stale fixed
  default with runtime discovery, loopback fallback, base-directory selection,
  explicit override precedence and normalized-origin trust. Include the exact
  local authentication command; matches `fe72104`, `local_origin()`,
  `normalized_origin()` and `Server.__init__()`. Consolidate settings-file
  guidance from the entry point, retaining all three fields, replacement
  semantics and the parent alternative; matches `start()` and `main()`.
  Correct the implication that missing visibility prints a detailed resume
  instruction: the record survives and the CLI emits a generic exception-type
  error with exit 1. Matches `b293300`, `submit()` and the final exception
  handler. V2-only transport, old-record compatibility, dry-run warnings,
  settlement restrictions, pacing and every command example remain.
- **[read-as-markdown/SKILL.md][cache-skill]:** link cache lookup/layout and
  backend detail instead of explaining it twice. Keep workspace selection,
  cache/ignore writes, arguments, examples and exit-status rules; place the
  reference's uncaught-error warning beside those rules. Matches `5fb1387`,
  `compute_cache_paths()`, `convert()` and `main()` in [the converter][cache-code].
- **[read-as-markdown/references/cache.md][cache-ref]:** retain the single
  full explanation of external path hashing, symlink behavior and legacy
  content reuse; incorporate the mtime/size fast path and SHA-256 fallback
  from the entry point. Retain backend ordering and move the forced-backend
  no-fallback rule here. Link result handling back to the entry point.
  Matches `5fb1387`, `check_cache()`, `check_hash_index()`, `BACKENDS` and
  `convert()` in [the converter][cache-code].
- **[secrets-scan/SKILL.md][scan-skill]:** link the detailed classification
  algorithm and failure conditions instead of repeating them. Keep outcome
  names, exit precedence, incomplete-coverage warning, authorization and
  redaction rules, CLI examples and offline validation. Matches `7e7a300`,
  `classify()`, `build_combined()`, `exit_status()` and scanner error handling
  in [the scanner][scan-code].
- **[secrets-scan/references/classifying-findings.md][scan-ref]:** retain the
  detailed algorithm/schema/failure conditions; link options, exit statuses,
  verification and reporting/authorization rules to their single entry-point
  explanation. Preserve narrow suppressions, manual raw-output caution,
  source remediation and the history-removal warning. Matches `7e7a300`,
  `run_detect_secrets()`, `run_secretlint()`, `build_combined()` and `exit_status()`.

## Validation

The required scanner, converter and T3 suites, plus metadata and security
regressions, passed: **158 tests**. They use fake scanners/converters and V2
wire responses; no live service or repository scan was used. Runtime checks
run with network access disabled and UV offline after dependency preparation.

Metadata validation covered 48 frontmatters; eight offline help probes,
relative links, heading lengths, diff whitespace, changed-text privacy,
documentation-only scope and committed symlinks also passed.

The [task record][task] records exact checks, integration evidence, setup
retries and memory reports. A separate evidence receipt captures checks on
the clean merged commit. No repository lockfile exists; validation uses an
external pinned requirements lock, recorded by SHA-256, with no editable
package dependency. The repository's scripts and tests remain unchanged.

## Draft issues

- **D1 — Validate nested scanner report shapes.** `7e7a300` rejects invalid
  JSON and wrong outer containers, but `run_secretlint()` assumes every list
  item/message is a dictionary; `build_combined()` similarly trusts nested
  detect-secrets results. A synthetic in-memory probe returning `[null]` from
  a fake `run_tool()` reached an uncaught `AttributeError` before a scanner
  outcome/report was produced. No scanner executable was invoked. The
  existing tests cover malformed JSON and outer containers, not these nested
  shapes. It is unclear whether malformed nested results belong to the
  promised scanner-failure contract or are deliberately treated as programming
  errors; this review leaves that code decision open.

  **Recommendation:** validate nested result shapes at each scanner boundary
  and classify malformed batches as redacted failures with exit 2, retaining
  other batches' findings. Add synthetic tests for null/scalar items and
  malformed message/location structures. This extends the existing incomplete
  scanner handling rather than weakening its documentation; it requires code
  and tests beyond this documentation task. No issue was filed.

[task]: ../tasks/29-check-skills-akaihola-s-skill-instructions-against-the-seven-source-ch.md
[earlier review]: 2026-10-22-docs-review.md
[readme]: ../../README.md
[agents]: ../../AGENTS.md
[t3-skill]: ../../t3-start-thread/SKILL.md
[t3-ref]: ../../t3-start-thread/references/helper.md
[t3-code]: ../../t3-start-thread/scripts/start_thread.py
[t3-tests]: ../../t3-start-thread/tests/test_start_thread.py
[cache-skill]: ../../read-as-markdown/SKILL.md
[cache-ref]: ../../read-as-markdown/references/cache.md
[cache-code]: ../../read-as-markdown/scripts/read_as_markdown.py
[scan-skill]: ../../secrets-scan/SKILL.md
[scan-ref]: ../../secrets-scan/references/classifying-findings.md
[scan-code]: ../../secrets-scan/scripts/scan.py
[metadata-ci]: ../../.github/workflows/test-skill-metadata.yml
[topology-ci]: ../../.github/workflows/check-topology.yml
[symlink-code]: ../../.github/scripts/check_symlinks.py
[security-tests]: ../../tests/test_security_boundaries.py
