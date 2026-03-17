#!/usr/bin/env python3
"""Analyze all uncommitted changes: disk usage, line churn, and classification.

Usage:
    co_triage.py [--config PATH] [--json] [REPO_DIR]

Reads the working tree and emits a sorted table of every uncommitted file with:
  - status (M/D/??)
  - on-disk bytes (or HEAD blob size for deletions)
  - line churn (+/-)
  - classification against workspace config ignore patterns

If --config is not given, looks for .ai/commit-organizer.yml then
.commit-organizer.yml in REPO_DIR.  If neither exists, no ignore
classification is applied.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

import yaml  # PyYAML — available via `uv run --with pyyaml`


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
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


def match_ignore(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
        # also match if any parent directory matches a dir pattern
        if pat.endswith("/**") and path.startswith(pat[:-3]):
            return True
    return False


def collect_status(repo: Path) -> list[dict]:
    """Parse git status --short into structured records."""
    raw = git("status", "--short", "--untracked-files=all", cwd=repo)
    entries = []
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        idx = line[0]
        wt = line[1]
        path = line[3:].strip('"')

        if line.startswith("?? "):
            status = "??"
        elif "D" in (idx, wt):
            status = "D"
        elif "M" in (idx, wt):
            status = "M"
        elif "A" in (idx, wt):
            status = "A"
        elif "R" in (idx, wt):
            status = "R"
        else:
            status = idx + wt
        entries.append({"path": path, "status": status, "staged": idx != " "})
    return entries


def measure_sizes(entries: list[dict], repo: Path) -> None:
    """Add bytes field to each entry."""
    for e in entries:
        p = repo / e["path"]
        if e["status"] == "??":
            if p.is_dir():
                total = 0
                for f in p.rglob("*"):
                    if f.is_file():
                        try:
                            total += f.stat().st_size
                        except OSError:
                            pass
                e["bytes"] = total
                e["is_dir"] = True
            elif p.exists():
                e["bytes"] = p.stat().st_size
                e["is_dir"] = False
            else:
                e["bytes"] = 0
                e["is_dir"] = False
        elif e["status"] == "D":
            # deleted — measure from HEAD
            try:
                raw = git("cat-file", "-s", f"HEAD:{e['path']}", cwd=repo).strip()
                e["bytes"] = int(raw)
            except (ValueError, subprocess.CalledProcessError):
                e["bytes"] = 0
            e["is_dir"] = False
        else:
            if p.exists() and p.is_file():
                e["bytes"] = p.stat().st_size
            else:
                e["bytes"] = 0
            e["is_dir"] = False


def measure_churn(entries: list[dict], repo: Path) -> None:
    """Add add/del line counts from git diff --numstat."""
    churn: dict[str, tuple[int, int]] = {}

    for source in ["diff", "diff --cached"]:
        raw = git(*source.split(), "--numstat", cwd=repo)
        for line in raw.splitlines():
            parts = line.split("\t", 2)
            if len(parts) < 3:
                continue
            add = int(parts[0]) if parts[0] != "-" else 0
            delete = int(parts[1]) if parts[1] != "-" else 0
            path = parts[2]
            if path in churn:
                prev = churn[path]
                churn[path] = (prev[0] + add, prev[1] + delete)
            else:
                churn[path] = (add, delete)

    for e in entries:
        if e["path"] in churn:
            e["lines_add"], e["lines_del"] = churn[e["path"]]
        else:
            e["lines_add"] = 0
            e["lines_del"] = 0


def classify(entries: list[dict], config: dict) -> None:
    """Add classification field based on config ignore patterns."""
    ignore_patterns = config.get("ignore", [])
    for e in entries:
        if ignore_patterns and match_ignore(e["path"], ignore_patterns):
            e["classification"] = "ignorable"
        else:
            e["classification"] = "intentional"


def format_bytes(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def print_table(entries: list[dict]) -> None:
    entries.sort(key=lambda e: e["bytes"], reverse=True)
    header = f"{'Status':<6} {'Bytes':>10} {'Churn':>10} {'Class':>12}  Path"
    print(header)
    print("-" * len(header))
    for e in entries:
        churn = (
            f"+{e['lines_add']}/-{e['lines_del']}"
            if e["lines_add"] or e["lines_del"]
            else ""
        )
        suffix = "/" if e.get("is_dir") else ""
        print(
            f"{e['status']:<6} {format_bytes(e['bytes']):>10} {churn:>10}"
            f" {e['classification']:>12}  {e['path']}{suffix}"
        )

    total = sum(e["bytes"] for e in entries)
    ignorable = sum(e["bytes"] for e in entries if e["classification"] == "ignorable")
    intentional = sum(
        e["bytes"] for e in entries if e["classification"] == "intentional"
    )
    print()
    print(
        f"Total: {format_bytes(total)}  |  ignorable: {format_bytes(ignorable)}  |  intentional: {format_bytes(intentional)}"
    )
    print(
        f"Files: {len(entries)}  |  ignorable: {sum(1 for e in entries if e['classification'] == 'ignorable')}  |  intentional: {sum(1 for e in entries if e['classification'] == 'intentional')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "repo", nargs="?", default=".", help="Repository directory (default: cwd)"
    )
    parser.add_argument("--config", help="Path to commit-organizer config YAML")
    parser.add_argument(
        "--json", action="store_true", help="Output JSON instead of table"
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    config = load_config(repo, args.config)

    entries = collect_status(repo)
    if not entries:
        print("Working tree is clean — nothing to triage.")
        sys.exit(0)

    measure_sizes(entries, repo)
    measure_churn(entries, repo)
    classify(entries, config)

    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        print_table(entries)


if __name__ == "__main__":
    main()
