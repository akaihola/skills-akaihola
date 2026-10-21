# Classifying secrets-scan findings

This reference describes [secrets-scan/scripts/scan.py], rather than the
version-dependent CLI or detector inventory of its external tools.

## Classification

`build_combined()` reads the flagged line internally and calls `classify()`.
`is_placeholder()` performs a case-insensitive substring search over the
whole line using `PLACEHOLDER_INDICATORS`.

Recognized indicators include `your_key_here`, `your-key-here`,
`your_actual_key`, `your-api-key`, hyphenated and underscored variants of
`your-token` and `your-secret`, `changeme`, `placeholder`, `example.com`,
the documented Slack placeholder fragment, `username:password@`, canonical
AWS documentation examples, `<your`, `[your`, `INSERT_`, `TODO:`, and
`FIXME:`. The source constant is authoritative for the exact list.

A matching line gets `likely-false-positive`; otherwise it gets
`review-required`. File type, directory and entropy do not participate in
this classification. Exclusion lists are separate, and a failed line read
becomes an empty string, hence `review-required`.

- **Placeholder match:** review non-secret context before suppressing it.
  A real credential beside a placeholder marker can receive the same label.
- **Documentation or test fixture:** location alone does not prove that data
  is synthetic. Confirm provenance without printing the flagged line.
- **Vendor-format match:** a detector match alone does not prove validity.
  Keep it under review until there is evidence; the wrapper performs no
  online credential verification.

## Output and coverage

Combined JSON contains `repo`, `findings` and `summary`. Each finding has
`source`, `file`, `line`, `type` and `classification`. Detect-secrets
findings also carry `is_verified`; secretlint findings carry `rule_id`.
Source lines, hashed secrets and raw scanner messages are omitted.
The Markdown renderer reports the same safe location/type information.

The wrapper always passes `--no-verify` to detect-secrets. Its
`--all-files` option applies only to that scanner; secretlint uses
`get_git_tracked_files()` and batches 200 paths at a time.

`run_detect_secrets()` returns an empty result for some command/JSON failures;
secretlint setup failure skips that scanner, and malformed or empty batch
output can be ignored. The summary does not record coverage failures.
Read stderr before describing a scan as complete.

## Remediation and suppression

For a confirmed exposed credential, arrange authorized revocation/rotation
and replace source literals with a credential mechanism. Never reproduce the
old value in reports, patches or commands.

Suppress only verified false positives and prefer narrow suppressions.
Broadly excluding documentation, test fixtures or dependency directories can
hide real credentials. History removal is separate repository work and does
not make an exposed credential safe again.

Direct scanner output may contain secrets. Prefer the wrapper’s redacted
report; if manual scanner use is necessary, capture raw output privately
and report only locations/types. Consult the installed tools’ help for their
current options. The wrapper implements neither a persistent baseline nor
an audit/diff workflow.

[secrets-scan/scripts/scan.py]: ../scripts/scan.py
