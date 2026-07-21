---
name: discard-whitespace-hunks
description: >
  Discard whitespace-only diff hunks from the git working tree while preserving
  real content changes. Use this skill whenever the user asks to clean up
  whitespace noise in a git diff, discard formatting-only changes, remove
  whitespace/indentation/line-break-only hunks, strip cosmetic diff noise, or
  keep only meaningful changes in unstaged modifications. Also use it when the
  user says things like "my diff is full of whitespace junk" or "I only want the
  real changes" or "drop the reformatting hunks".
---

# Discard Whitespace-Only Diff Hunks

Remove all unstaged diff hunks whose only effect is whitespace, indentation, or
line-break reformatting — keeping hunks that change actual content.

## What counts as "whitespace-only"

A hunk is whitespace-only when the removed lines and added lines, after
**concatenation and removal of all whitespace characters** (spaces, tabs,
newlines), produce the **same string**. This catches:

- Pure indentation changes (tabs ↔ spaces, indent level)
- Line-break reformatting (one long line → multiple short lines or vice-versa)
- Trailing whitespace additions/removals
- Blank line additions/removals
- Any combination of the above

## Procedure

### 1. Check for unstaged changes

```bash
git diff --stat
```

If there's nothing, stop — nothing to do.

### 2. Restore files that are entirely whitespace changes

Compare regular diff against whitespace-ignoring diff at the file level:

```bash
git diff --stat          # all changes
git diff -w --stat       # non-whitespace changes only
```

Files that appear in the first but **not** the second are entirely whitespace —
restore them:

```bash
git checkout -- <file>
```

### 3. Find and discard whitespace-only hunks in mixed files

For files that appear in both diffs (they have a mix of real and whitespace-only
hunks), run the bundled Python script:

```bash
python3 <skill-dir>/scripts/discard_ws_hunks.py
```

The script:

1. Parses `git diff` output into per-file, per-hunk structures.
2. Classifies each hunk: concatenate all removed lines (without the leading `-`)
   and all added lines (without the leading `+`), strip every whitespace
   character from both, and compare. If identical → whitespace-only.
3. Builds a patch containing only the whitespace-only hunks.
4. Applies it in reverse (`git apply --reverse`) to undo just those hunks.

### 4. Verify

```bash
git diff --stat
```

Confirm the remaining diff is smaller and all hunks are substantive.

## Edge cases

- **Staged changes**: This procedure only touches the working tree (unstaged
  changes). Staged hunks are not affected.
- **New/deleted files**: Files that are fully added or fully deleted have no
  "whitespace-only" hunks by definition — they're left alone.
- **Binary files**: Skipped automatically (no text diff to parse).
- **Mixed indentation in context lines**: The reverse-apply uses exact context
  matching, so it works correctly as long as the working tree hasn't been
  modified between generating and applying the patch. Don't edit files between
  steps 3 and 4.
