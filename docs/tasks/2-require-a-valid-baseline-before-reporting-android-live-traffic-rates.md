---
dependencies: []
---

# Require a valid baseline before reporting Android live traffic rates

Requested on 2026-10-12 for review finding P2.

## Problem

When the first netstats sample fails and the next succeeds, `_traffic_rows`
uses zero for each missing starting counter. It reports the later cumulative
counts as traffic during the short sampling interval. A synthetic two-minute
comparison with no baseline and 20,000 packets in the later sample reported
10,000 packets per minute, with no comparison limitation note.

## Scope

Review `android-diagnostics/scripts/sample_live.py:355` and `diff_traffic`.
Distinguish a successfully read empty map from a failed, missing or partially
parsed baseline. Inspect command status as well as parsed rows. Handle UID
and interface counters consistently.

## Acceptance criteria

- A failed, missing or unusable baseline yields unavailable deltas and rates,
  with a clear limitation note. It never invents a zero starting counter.
- Incomplete tables do not turn unobserved starting rows into measured rates.
- Successfully read empty tables and genuinely new counter rows retain their
  documented behavior. Existing valid-baseline comparisons still work.
- Offline tests cover failed-first/successful-second reads, partial parsing,
  empty valid maps and ordinary valid deltas. No phone is required.
