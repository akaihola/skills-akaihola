---
dependencies: []
---

# Redact valid email addresses with package-like domain prefixes

Requested on 2026-10-12 for review finding P2.

## Problem

The email regex excludes every domain beginning with `com.`, `org.`, `net.`,
`io.`, `de.`, `android.`, `androidx.` or `vendor.`. These prefixes can also
belong to valid email subdomains. Synthetic reserved-domain addresses using
these prefixes remain visible in the final `report.py --redact` rendering.

## Scope

Review `android-diagnostics/scripts/androiddiag/redact.py:60`. Distinguish
actual email addresses from HAL names and Android job tags without excluding
whole classes of otherwise valid domains. Use only invented test addresses
under `example.com` or `example.org`.

## Acceptance criteria

- Email addresses with each excluded prefix are replaced consistently by
  email placeholders, including when they appear in findings or evidence.
- Existing HAL and job-tag examples remain intact, and normal email
  redaction, case normalization and idempotence still work.
- Tests exercise both the redactor and final Markdown and JSON-summary report
  output under `--redact`. No actual message content or identifiers are used.
