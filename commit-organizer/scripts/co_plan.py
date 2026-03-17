#!/usr/bin/env python3
"""Propose commit groups from uncommitted changes, ordered by oldest file mtime.

Usage:
    co_plan.py [--config PATH] [--json] [REPO_DIR]

Reads the working tree and workspace config, assigns files to grouping
buckets, computes mtimes, and emits a proposed commit plan ordered from
oldest to newest group.

Files not matching any config bucket are placed in an "ungrouped" bucket
for the agent to handle manually.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml


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


def match_ignore(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
        if pat.endswith("/**") and path.startswith(pat[:-3]):
            return True
    return False


def match_bucket(path: str, bucket: dict) -> bool:
    """Check if a path matches any pattern in a grouping bucket."""
    for pat in bucket.get("paths", []):
        if fnmatch.fnmatch(path, pat):
            return True
        if pat.endswith("/**") and path.startswith(pat[:-3]):
            return True
    return False


def collect_uncommitted(repo: Path) -> list[dict]:
    """Collect all uncommitted files with status."""
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
        elif "D" in {idx, wt}:
            status = "D"
        elif "M" in {idx, wt}:
            status = "M"
        elif "A" in {idx, wt}:
            status = "A"
        else:
            status = idx + wt

        entries.append({"path": path, "status": status})
    return entries


def compute_mtimes(entries: list[dict], repo: Path) -> None:
    """Add mtime and mtime_str fields to each entry."""
    for e in entries:
        p = repo / e["path"]
        if p.exists():
            mt = p.stat().st_mtime
            e["mtime"] = mt
            e["mtime_str"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt))
        elif e["status"] == "D":
            # deleted file — use last commit time
            raw = git("log", "-1", "--format=%ct", "--", e["path"], cwd=repo).strip()
            if raw:
                mt = float(raw)
                e["mtime"] = mt
                e["mtime_str"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt))
            else:
                e["mtime"] = 0.0
                e["mtime_str"] = "unknown"
        else:
            e["mtime"] = 0.0
            e["mtime_str"] = "unknown"


def assign_buckets(entries: list[dict], config: dict) -> dict[str, list[dict]]:
    """Assign entries to config-defined buckets or 'ungrouped'."""
    buckets: dict[str, list[dict]] = {}
    ignore_patterns = config.get("ignore", [])
    grouping = config.get("grouping", {})
    bucket_defs = grouping.get("buckets", [])

    for e in entries:
        # skip ignored files
        if match_ignore(e["path"], ignore_patterns):
            e["bucket"] = "_ignored"
            buckets.setdefault("_ignored", []).append(e)
            continue

        matched = False
        for bdef in bucket_defs:
            if match_bucket(e["path"], bdef):
                name = bdef["name"]
                e["bucket"] = name
                e["defaultType"] = bdef.get("defaultType", "chore")
                e["defaultScope"] = bdef.get("defaultScope", "")
                buckets.setdefault(name, []).append(e)
                matched = True
                break

        if not matched:
            e["bucket"] = "_ungrouped"
            buckets.setdefault("_ungrouped", []).append(e)

    return buckets


def build_plan(buckets: dict[str, list[dict]], config: dict) -> list[dict]:
    """Build ordered commit plan from buckets."""
    naming = config.get("naming", {})
    plan = []

    for name, entries in buckets.items():
        if name == "_ignored":
            continue

        oldest_mtime = min(e["mtime"] for e in entries)
        oldest_str = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(oldest_mtime))
            if oldest_mtime > 0
            else "unknown"
        )

        if name in naming:
            suggested_prefix = naming[name]
        elif name == "_ungrouped":
            suggested_prefix = "chore"
        else:
            dt = entries[0].get("defaultType", "chore")
            ds = entries[0].get("defaultScope", "")
            suggested_prefix = f"{dt}({ds})" if ds else dt

        plan.append(
            {
                "bucket": name,
                "suggested_prefix": suggested_prefix,
                "oldest_mtime": oldest_str,
                "file_count": len(entries),
                "files": [
                    {"path": e["path"], "status": e["status"], "mtime": e["mtime_str"]}
                    for e in sorted(entries, key=lambda x: x["mtime"])
                ],
            }
        )

    # sort by oldest mtime
    plan.sort(key=lambda g: g["oldest_mtime"])
    return plan


def print_plan(plan: list[dict]) -> None:
    print("Proposed commit groups, oldest to newest:\n")
    for i, group in enumerate(plan, 1):
        bucket = group["bucket"]
        prefix = group["suggested_prefix"]
        label = f"(ungrouped)" if bucket == "_ungrouped" else bucket
        print(f"{i}. `{prefix}: ...`  [{label}, {group['file_count']} files]")
        print(f"   oldest mtime: {group['oldest_mtime']}")
        for f in group["files"]:
            print(f"   {f['status']:<4} {f['mtime']:<20} {f['path']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("repo", nargs="?", default=".", help="Repository directory")
    parser.add_argument("--config", help="Path to commit-organizer config YAML")
    parser.add_argument(
        "--json", action="store_true", help="Output JSON instead of text"
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    config = load_config(repo, args.config)

    entries = collect_uncommitted(repo)
    if not entries:
        print("Working tree is clean — nothing to plan.")
        sys.exit(0)

    compute_mtimes(entries, repo)
    buckets = assign_buckets(entries, config)
    plan = build_plan(buckets, config)

    ignored = buckets.get("_ignored", [])

    if args.json:
        output = {"plan": plan}
        if ignored:
            output["ignored"] = [
                {"path": e["path"], "status": e["status"]} for e in ignored
            ]
        print(json.dumps(output, indent=2))
    else:
        print_plan(plan)
        if ignored:
            print(f"({len(ignored)} files skipped — match ignore patterns)")


if __name__ == "__main__":
    main()
