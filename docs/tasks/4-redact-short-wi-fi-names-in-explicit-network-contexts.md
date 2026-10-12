---
dependencies: []
---

# Redact short Wi-Fi names in explicit network contexts

Requested on 2026-10-12 for review finding P2.

## Problem

`Redactor._remember` discards learned values shorter than three characters.
Configuration keys rely on learned-value replacement rather than a direct
redaction rule. Consequently, the invented `configKey="AB"WPA_PSK` survives
`report.py --redact`. A short name can also survive elsewhere after an
explicit SSID context has identified it.

## Scope

Review `android-diagnostics/scripts/androiddiag/redact.py:146`, network-name
learning, configuration-key matching and replacement. Avoid a fix that
indiscriminately replaces ordinary short words throughout the report.

## Acceptance criteria

- One- and two-character SSIDs are hidden in explicit SSID, network-key and
  configuration-key contexts while surrounding syntax remains readable.
- Any retained context-based learning policy does not leave those values
  exposed elsewhere in exported findings or evidence.
- Unknown-network sentinels, ordinary prose, existing longer-name behavior
  and idempotence remain covered.
- Offline regression tests cover direct redaction and final Markdown and
  JSON-summary report output using invented network names.
