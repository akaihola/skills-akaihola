#!/usr/bin/env python3
"""Propose .gitignore additions and git-rm-cached commands based on triage output.

Usage:
    co_ignore.py [--config PATH] [--dry-run] [REPO_DIR]

Reads the workspace config ignore patterns and the current .gitignore,
then emits:
  1. A proposed .gitignore patch (new patterns not already covered)
  2. A list of `git rm --cached` commands for tracked files matching
     ignore patterns

With --dry-run (default), only prints what would be done.
Without --dry-run, applies the .gitignore patch and runs git rm --cached.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

import yaml


KERNEL_NOTE = """\
# Kernel note: .gitignore only prevents new files from being tracked – it does
# not affect files already in Git history. Use `git rm --cached <path>` to keep
# generated files on disk while removing them from version control."""


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def load_config(repo: Path, explicit: str | None) -> dict:
    if explicit:
        p = Path(explicit)
    else:
        for candidate in [".ai/commit-organizer.yml", ".commit-organizer.yml"]:
            p = repo / candidate
            if p.exists():
                break
        else:
            return {}
    if p.exists():
        return yaml.safe_load(p.read_text()) or {}
    return {}


def read_gitignore(repo: Path) -> list[str]:
    gi = repo / ".gitignore"
    if gi.exists():
        return gi.read_text().splitlines()
    return []


def pattern_covered(pattern: str, existing_lines: list[str]) -> bool:
    """Check if a pattern is already in .gitignore (exact or as glob)."""
    stripped = [
        l.strip() for l in existing_lines if l.strip() and not l.strip().startswith("#")
    ]
    # exact match
    if pattern in stripped:
        return True
    # check if existing broader pattern covers it
    for existing in stripped:
        if fnmatch.fnmatch(pattern, existing):
            return True
    return False


def match_ignore(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
        if pat.endswith("/**") and path.startswith(pat[:-3]):
            return True
    return False


def find_tracked_ignorable(repo: Path, ignore_patterns: list[str]) -> list[str]:
    """Find tracked files that match ignore patterns."""
    raw = git("ls-files", cwd=repo)
    matched = []
    for path in raw.splitlines():
        if match_ignore(path, ignore_patterns):
            matched.append(path)
    return matched


def find_untracked_ignorable(repo: Path, ignore_patterns: list[str]) -> list[str]:
    """Find untracked files/dirs that match ignore patterns but aren't yet in .gitignore."""
    raw = git("status", "--short", "--untracked-files=all", cwd=repo)
    matched = []
    for line in raw.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip('"')
        if match_ignore(path, ignore_patterns):
            matched.append(path)
    return matched


def propose_gitignore_patch(
    ignore_patterns: list[str],
    existing_lines: list[str],
) -> list[str]:
    """Return new .gitignore lines to add."""
    new_lines = []
    for pat in ignore_patterns:
        # normalize: sessions/** -> sessions/ for gitignore
        gi_pat = pat.rstrip("*").rstrip("/") + "/" if pat.endswith("/**") else pat
        if not pattern_covered(gi_pat, existing_lines):
            new_lines.append(gi_pat)
    return new_lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("repo", nargs="?", default=".", help="Repository directory")
    parser.add_argument("--config", help="Path to commit-organizer config YAML")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Only print proposed changes (default)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to .gitignore and run git rm --cached",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    config = load_config(repo, args.config)
    ignore_patterns = config.get("ignore", [])

    if not ignore_patterns:
        print("No ignore patterns in config — nothing to propose.")
        sys.exit(0)

    existing_lines = read_gitignore(repo)

    # 1. Propose .gitignore additions
    new_patterns = propose_gitignore_patch(ignore_patterns, existing_lines)
    tracked_hits = find_tracked_ignorable(repo, ignore_patterns)
    untracked_hits = find_untracked_ignorable(repo, ignore_patterns)

    print("=== .gitignore additions ===")
    if new_patterns:
        # check if kernel note exists
        has_kernel = any("git rm --cached" in line for line in existing_lines)
        if not has_kernel:
            print(KERNEL_NOTE)
            print()
        print("# Generated/temporary files (from commit-organizer config)")
        for p in new_patterns:
            print(p)
    else:
        print("(all config ignore patterns are already covered)")

    print()
    print("=== git rm --cached (tracked files matching ignore patterns) ===")
    if tracked_hits:
        for f in tracked_hits:
            print(f"git rm --cached -- {f}")
    else:
        print("(no tracked files match ignore patterns)")

    print()
    print("=== untracked files already matching ignore patterns ===")
    if untracked_hits:
        for f in untracked_hits:
            print(f"  {f}")
        print("(these will be ignored once .gitignore is updated)")
    else:
        print("(none)")

    if args.apply:
        print()
        print("=== Applying changes ===")

        if new_patterns:
            gi_path = repo / ".gitignore"
            content = gi_path.read_text() if gi_path.exists() else ""
            additions = []
            has_kernel = "git rm --cached" in content
            if not has_kernel:
                additions.append("")
                additions.append(KERNEL_NOTE)
            additions.append("")
            additions.append(
                "# Generated/temporary files (from commit-organizer config)"
            )
            additions.extend(new_patterns)
            gi_path.write_text(
                content.rstrip("\n") + "\n" + "\n".join(additions) + "\n"
            )
            print(f"  Updated {gi_path}")

        if tracked_hits:
            subprocess.run(
                ["git", "rm", "--cached", "--"] + tracked_hits,
                cwd=repo,
                check=True,
            )
            print(f"  Untracked {len(tracked_hits)} files via git rm --cached")

        print("  Done. Stage .gitignore and commit the cleanup.")


if __name__ == "__main__":
    main()
