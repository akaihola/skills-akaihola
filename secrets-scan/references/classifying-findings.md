# Classifying secrets-scan findings

This reference describes [secrets-scan/scripts/scan.py], rather than the
version-dependent CLI or detector inventory of its external tools.

## Classification

`build_combined()` reads the flagged line internally, recovers the detected
value and passes only that value to `classify()`. `is_placeholder()` performs
a case-insensitive substring search over the value using
`PLACEHOLDER_INDICATORS`; words elsewhere on the line do not count.

- **detect-secrets:** the baseline holds only `hashed_secret`, a SHA-1 of the
  value. `detect_secrets_value()` hashes substrings of the line that start
  and end at a line end or beside a non-alphanumeric character, and keeps the
  one that matches. Lines longer than `MAX_HASH_SEARCH_LINE` (1,000
  characters) are not searched.
- **secretlint:** `secretlint_value()` takes the span between the message's
  start and end columns (0-based), or to the end of the line when the match
  spans lines.

Recognized indicators include `your_key_here`, `your-key-here`,
`your_actual_key`, `your-api-key`, hyphenated and underscored variants of
`your-token` and `your-secret`, `changeme`, `placeholder`, `example.com`,
the documented Slack placeholder fragment, `username:password@`, canonical
AWS documentation examples, `<your`, `[your`, `INSERT_`, `TODO:`, and
`FIXME:`. The source constant is authoritative for the exact list.

A matching value gets `likely-false-positive`; otherwise the finding gets
`review-required`. File type, directory and entropy do not participate in
this classification. Exclusion lists are separate. When the value cannot be
recovered (a failed line read, no hash match, an over-long line or an empty
span), the finding is `review-required`.

- **Placeholder match:** review non-secret context before suppressing it.
  A marker inside a longer value, such as a real credential embedded in an
  `example.com` URL, still makes the finding `likely-false-positive`.
- **Documentation or test fixture:** location alone does not prove that data
  is synthetic. Confirm provenance without printing the flagged line.
- **Vendor-format match:** a detector match alone does not prove validity.
  Keep it under review until there is evidence; the wrapper performs no
  online credential verification.

## Output and coverage

Combined JSON contains `repo`, `scanners`, `findings` and `summary`. Each
finding has `source`, `file`, `line`, `type` and `classification`.
Detect-secrets findings also carry `is_verified`; secretlint findings carry
`rule_id`. Source lines, detected values, hashed secrets and raw scanner
messages are omitted. The Markdown renderer reports the same safe
location/type information and the scanner outcomes.

For scanner options and the verification policy, see the [skill entry point][skill].
Secretlint uses `get_git_tracked_files()` and batches `SECRETLINT_BATCH_SIZE`
(200) paths at a time.

`scanners` maps each scanner name to `{"status": "ran"}`,
`{"status": "skipped", "reason": "--no-secretlint"}` or
`{"status": "failed", "reason": ...}`, and `summary.failed_scanners` lists
the failed names. Reasons name exit statuses, parse errors and the part of
the output with the wrong JSON type, never its value or raw scanner stderr.
A scanner fails when:

- **detect-secrets:** `uvx` cannot start, exits with a status other than 0
  or 1, or prints output that is not JSON with a `results` object mapping
  each file to a list of objects.
- **secretlint setup:** `bun add` cannot start or fails, it leaves no
  secretlint binary, or `git ls-files` fails (for example outside a Git
  repository).
- **secretlint batch:** a batch cannot start, exits with a status other than
  0 or 1, exits 1 with empty output, or prints output that is not a JSON list.
  A nested value of the wrong JSON type fails the batch too: a result that is
  not an object, a `filePath` that is not a string, `messages` that is not a
  list of objects, a `loc`, `start` or `end` that is not an object, or a line
  or column that is not an integer. Empty output with exit 0 counts as a clean
  batch. Findings from the other batches are kept, and the reason counts the
  batches not scanned.

See [exit statuses and incomplete-scan handling][results].

## Remediation and suppression

Follow the [skill's authorization and reporting rules][results]; replace
confirmed source credentials with a credential mechanism.

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
[skill]: ../SKILL.md
[results]: ../SKILL.md#interpret-a-result
