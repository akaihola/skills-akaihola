---
dependencies: []
---

# Discover imported Android bugreports with uppercase ZIP extensions

Requested on 2026-10-12 for review finding P3.

## Problem

`analyze.link_bugreport` recognizes a ZIP suffix without regard to case but
preserves the original filename. `Workdir.bugreport_path` then searches only
lowercase `*.zip` names. Importing a valid `capture.ZIP` into an empty workdir
therefore reports that no usable bugreport exists.

## Scope

Review `android-diagnostics/scripts/analyze.py:275` and archive discovery in
`android-diagnostics/scripts/androiddiag/source.py`. Normalize the imported
filename or make discovery consistent with the importer's accepted suffixes.

## Acceptance criteria

- Valid synthetic bugreports with `.zip`, `.ZIP` and mixed-case extensions
  work through `analyze.py WORKDIR --bugreport FILE` in new empty workdirs.
- Discovery and evidence references continue to work after import. Inputs
  with a different suffix retain the existing documented behavior.
- Existing files are not silently overwritten, and invalid archives still
  receive the appropriate error.
- An offline CLI regression test covers the previously failing uppercase
  extension, alongside the existing source and import tests.
