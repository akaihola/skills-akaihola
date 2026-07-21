#!/usr/bin/env python3
"""Discard whitespace-only diff hunks from the git working tree.

Parses ``git diff``, classifies each hunk as whitespace-only or substantive,
builds a patch of the whitespace-only hunks, and reverse-applies it so those
changes are reverted while real content changes are preserved.

A hunk is "whitespace-only" when the removed and added lines, concatenated and
stripped of ALL whitespace (spaces, tabs, newlines), produce the same string.

Usage::

    python3 discard_ws_hunks.py          # operate on cwd
    python3 discard_ws_hunks.py /path    # operate on a specific repo
    python3 discard_ws_hunks.py --dry-run  # show what would be discarded
"""

from __future__ import annotations

import re
import subprocess  # noqa: S404
import sys
import tempfile
from pathlib import Path


def _run_git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command and return its stdout."""
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        msg = f"git {' '.join(args)} failed:\n{result.stderr}"
        raise RuntimeError(msg)
    return result.stdout


def _parse_diff(diff_text: str) -> list[dict]:
    """Parse unified diff into a list of file dicts, each with header + hunks."""
    files: list[dict] = []
    current_file: dict | None = None
    current_hunk: list[str] | None = None

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git"):
            if current_file is not None:
                if current_hunk:
                    current_file["hunks"].append(current_hunk)
                files.append(current_file)
            current_file = {"header": [line], "hunks": []}
            current_hunk = None
        elif (
            current_file is not None
            and current_hunk is None
            and not line.startswith("@@")
        ):
            current_file["header"].append(line)
        elif line.startswith("@@"):
            if current_hunk is not None and current_file is not None:
                current_file["hunks"].append(current_hunk)
            current_hunk = [line]
        elif current_hunk is not None:
            current_hunk.append(line)

    if current_file is not None:
        if current_hunk:
            current_file["hunks"].append(current_hunk)
        files.append(current_file)

    return files


def _is_whitespace_only_hunk(hunk_lines: list[str]) -> bool:
    """Return True if removed and added content differ only in whitespace."""
    removed = [
        line[1:]
        for line in hunk_lines
        if line.startswith("-") and not line.startswith("---")
    ]
    added = [
        line[1:]
        for line in hunk_lines
        if line.startswith("+") and not line.startswith("+++")
    ]

    removed_blob = re.sub(r"\s+", "", "".join(removed))
    added_blob = re.sub(r"\s+", "", "".join(added))

    return removed_blob == added_blob


def _file_path_from_header(header: list[str]) -> str:
    """Extract the file path from a diff header."""
    return header[0].split(" b/", 1)[-1].strip()


def main() -> None:
    """Entry point — parse args, find whitespace-only hunks, discard them."""
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    cwd = Path(args[0]) if args else None

    # ── Step 1: Restore files that are entirely whitespace changes ───────
    all_files = _run_git("diff", "--name-only", cwd=cwd).splitlines()
    real_files = _run_git("diff", "-w", "--name-only", cwd=cwd).splitlines()
    real_set = set(real_files)
    ws_only_files = [f for f in all_files if f not in real_set]

    if ws_only_files:
        print(f"Files with only whitespace changes ({len(ws_only_files)}):")
        for f in ws_only_files:
            print(f"  restore: {f}")
        if not dry_run:
            _run_git("checkout", "--", *ws_only_files, cwd=cwd)

    # ── Step 2: Parse remaining diff and find whitespace-only hunks ──────
    diff_text = _run_git("diff", cwd=cwd)
    if not diff_text.strip():
        if not ws_only_files:
            print("No unstaged changes.")
        return

    files = _parse_diff(diff_text)

    ws_patch_lines: list[str] = []
    total_ws = 0
    total_hunks = 0

    for f in files:
        ws_hunks = [h for h in f["hunks"] if _is_whitespace_only_hunk(h)]
        total_hunks += len(f["hunks"])
        if ws_hunks:
            total_ws += len(ws_hunks)
            fpath = _file_path_from_header(f["header"])
            print(
                f"  {fpath}: {len(ws_hunks)}/{len(f['hunks'])} "
                f"hunks are whitespace-only"
            )
            ws_patch_lines.extend(f["header"])
            for h in ws_hunks:
                ws_patch_lines.extend(h)

    if not ws_patch_lines:
        print("No whitespace-only hunks found in mixed files.")
        return

    print(f"\nTotal: {total_ws}/{total_hunks} whitespace-only hunks to discard")

    if dry_run:
        print("\n(dry-run mode — no changes applied)")
        return

    # ── Step 3: Reverse-apply the whitespace-only patch ──────────────────
    patch = "".join(ws_patch_lines)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(patch)
        tmp_path = tmp.name

    try:
        _run_git("apply", "--reverse", tmp_path, cwd=cwd)
        print("Whitespace-only hunks discarded.")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
