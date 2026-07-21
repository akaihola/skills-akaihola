#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Fail if any committed symlink is absolute or escapes the repository.

An absolute symlink resolves only on the machine and account it was authored on;
every other clone inherits a dead link. A relative link that climbs out of the
repo is the same bug wearing a disguise. Both are invisible in review and only
surface later, on someone else's machine.

Run with no arguments to check the whole repository.
"""

from __future__ import annotations

import subprocess  # noqa: S404
import sys
from pathlib import Path

GIT_SYMLINK_MODE = "120000"


def repo_root() -> Path:
    """Absolute path of the repository being checked."""
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(proc.stdout.strip())


def committed_symlinks(root: Path) -> list[Path]:
    """Every symlink tracked in the index, as repo-relative paths."""
    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "ls-files", "-s"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    links = []
    for line in proc.stdout.splitlines():
        meta, _, path = line.partition("\t")
        if meta.split(" ", 1)[0] == GIT_SYMLINK_MODE:
            links.append(Path(path))
    return links


def check(root: Path, link: Path) -> str | None:
    """Return a complaint about this symlink, or None when it is fine."""
    target = Path((root / link).readlink())
    if target.is_absolute():
        return f"absolute target {target}"
    resolved = (root / link).parent.joinpath(target).resolve()
    if root.resolve() not in resolved.parents and resolved != root.resolve():
        return f"escapes the repository: {target} -> {resolved}"
    return None


def main() -> int:
    """Check every committed symlink and report the bad ones."""
    root = repo_root()
    problems = [
        (link, complaint)
        for link in committed_symlinks(root)
        if (complaint := check(root, link)) is not None
    ]
    if not problems:
        print("OK - every committed symlink is relative and stays in the repo")
        return 0

    print("Committed symlinks must be relative and stay inside the repository.")
    print("An absolute link resolves only on the machine that created it.\n")
    for link, complaint in problems:
        print(f"  {link}\n      {complaint}")
    print(f"\n{len(problems)} bad symlink(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
