---
dependencies: []
---

# Protect Android diagnostics captures from other local users

Requested on 2026-10-12 for review finding P1.

## Problem

With a normal POSIX umask of `022`, collection creates workdirs with mode
`0755` and raw files with mode `0644`. The default temporary location allows
other local users to read bugreports, account information and network details.
The review reproduced these permissions through `collect.make_workdir` and
`androiddiag.readonly.save_output` without connecting a phone.

## Scope

Review `android-diagnostics/scripts/collect.py:183`, the output helpers in
`android-diagnostics/scripts/androiddiag/readonly.py`, and directory creation
in `sample_live.py` and `adb_ro.py`. Protect personal data before the first
write, including temporary manifest files and the bugreport archive. Avoid
changing permissions on unrelated user directories or following unsafe links.

## Acceptance criteria

- Newly created POSIX workdirs have mode `0700`, and personal-data files are
  owner-only. A permissive umask does not weaken these protections.
- Collection, sampling and ad-hoc saved reads use the same protection policy.
  Existing unsafe destinations are handled explicitly before writing data.
- Synthetic tests cover umasks `022` and `002`, directory and file modes,
  and the existing-directory behavior. Skip POSIX mode assertions on systems
  without POSIX permissions.
- Collection documentation explains the storage protection. Phone commands
  remain read-only, and validation requires no connected device.
