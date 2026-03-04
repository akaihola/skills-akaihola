#!/usr/bin/env python3
"""Search Claude Code session JSONL files for a text query.

Usage:
    uv run scripts/search-sessions.py <query> [--dir DIR] [--context N]

Output: one block per matching session file with the session ID, the project
path derived from the directory name, and surrounding message excerpts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from textwrap import dedent

_SESSIONS_DIRS = [
    Path.home() / ".claude" / "projects",
    Path.home() / ".claude" / "transcripts",
]


def _iter_session_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.jsonl"))


def _project_label(path: Path) -> str:
    """Decode the -home-agent-foo directory convention back to /home/agent/foo."""
    parent = path.parent.name.removeprefix("-")
    return "/" + parent.replace("-", "/")


def _extract_text(entry: dict) -> str:  # type: ignore[type-arg]
    """Return all searchable text from one JSONL entry (flat string)."""
    parts: list[str] = []

    if entry.get("type") == "queue-operation":
        c = entry.get("content", "")
        if isinstance(c, str):
            parts.append(c)
        return " ".join(parts)

    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        return ""

    content = msg.get("content", "")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_result":
                c = block.get("content", "")
                if isinstance(c, str):
                    parts.append(c)

    return " ".join(parts)


def _load_entries(path: Path) -> list[dict]:  # type: ignore[type-arg]
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()  # noqa: PLW2901
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _print_match_block(
    session_file: Path,
    entries: list[dict],  # type: ignore[type-arg]
    texts: list[str],
    match_indices: list[int],
    context_lines: int,
) -> None:
    print(f"\n{'=' * 72}")
    print(f"Session : {session_file.stem}")
    print(f"File    : {session_file}")
    print(f"Project : {_project_label(session_file)}")
    print(f"Matches : {len(match_indices)}")
    print(f"{'=' * 72}")

    shown: set[int] = set()
    for mi in match_indices:
        lo = max(0, mi - context_lines)
        hi = min(len(entries) - 1, mi + context_lines)
        for i in range(lo, hi + 1):
            if i in shown:
                continue
            shown.add(i)
            e = entries[i]
            ts = e.get("timestamp", "")[:19]
            etype = e.get("type", "?")
            role = ""
            msg = e.get("message")
            if isinstance(msg, dict):
                role = msg.get("role", "")
            label = f"{etype}/{role}" if role else etype
            marker = ">>>" if i == mi else "   "
            excerpt = texts[i][:200].replace("\n", " ")
            print(f"{marker} [{i:4d}] {ts} {label:20s} {excerpt}")


def search(query: str, dirs: list[Path], context_lines: int) -> None:
    """Search all session files under dirs for query, printing context blocks."""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    found_any = False

    for root in dirs:
        for session_file in _iter_session_files(root):
            try:
                entries = _load_entries(session_file)
            except OSError:
                continue

            texts = [_extract_text(e) for e in entries]
            match_indices = [i for i, t in enumerate(texts) if pattern.search(t)]

            if not match_indices:
                continue

            found_any = True
            _print_match_block(
                session_file, entries, texts, match_indices, context_lines
            )

    if not found_any:
        print(f"No sessions found containing: {query!r}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Parse arguments and run the search."""
    parser = argparse.ArgumentParser(
        description=dedent("""\
            Search Claude Code session JSONL files for a text query.
            Searches ~/.claude/projects/ and ~/.claude/transcripts/ by default.
        """),
    )
    parser.add_argument("query", help="Text to search for (case-insensitive)")
    parser.add_argument(
        "--dir",
        metavar="DIR",
        action="append",
        dest="extra_dirs",
        default=[],
        help="Additional directory to search (repeatable)",
    )
    parser.add_argument(
        "--context",
        metavar="N",
        type=int,
        default=2,
        help="Number of surrounding entries to show per match (default: 2)",
    )
    args = parser.parse_args()

    dirs = _SESSIONS_DIRS + [Path(d) for d in args.extra_dirs]
    search(args.query, dirs, args.context)


if __name__ == "__main__":
    main()
