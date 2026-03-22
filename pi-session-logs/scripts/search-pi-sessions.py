#!/usr/bin/env python3
"""Search Pi agent session JSONL files for a text query.

Usage:
    uv run scripts/search-pi-sessions.py <query> [--dir DIR] [--context N]

Output: one block per matching session file with the session ID, the CWD
decoded from the directory name, and surrounding entry excerpts.

Pi session files live at:
    ~/.pi/agent/sessions/<encoded-cwd>/<timestamp>_<uuid>.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from textwrap import dedent

_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"


def _iter_session_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.jsonl"))


def _decode_cwd(session_file: Path) -> str:
    """Best-effort decode of encoded directory name back to a path.

    Pi encodes the cwd by replacing each '/' with '-' and wrapping in '--'.
    Example: --home-agent-repos-ai-pi-pi-mono-- → /home/agent/repos/ai/pi/pi-mono
    """
    name = session_file.parent.name
    # Strip leading/trailing '--' or '-'
    stripped = name.strip("-")
    return "/" + stripped.replace("-", "/")


def _extract_text(entry: dict) -> str:
    """Return all searchable text from one Pi JSONL entry (flat string)."""
    parts: list[str] = []

    etype = entry.get("type", "")

    # session metadata
    if etype == "session":
        parts.append(entry.get("cwd", ""))
        return " ".join(parts)

    # compaction summary
    if etype == "compaction":
        parts.append(entry.get("summary", ""))
        return " ".join(parts)

    # session name
    if etype == "session_info":
        parts.append(entry.get("name", ""))
        return " ".join(parts)

    # custom messages (orchestrator-agents, etc.)
    if etype == "custom_message":
        parts.append(str(entry.get("content", "")))
        return " ".join(parts)

    # standard messages (user / assistant / toolResult)
    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        return ""

    role = msg.get("role", "")
    content = msg.get("content", [])

    # toolResult: top-level toolName searchable, content blocks below
    if role == "toolResult":
        parts.append(msg.get("toolName", ""))

    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "toolCall":
                parts.append(block.get("name", ""))
                parts.append(json.dumps(block.get("arguments", {})))
            elif btype == "thinking":
                parts.append(block.get("thinking", ""))
    elif isinstance(content, str):
        parts.append(content)

    return " ".join(parts)


def _entry_label(entry: dict) -> str:
    etype = entry.get("type", "?")
    msg = entry.get("message")
    if isinstance(msg, dict):
        role = msg.get("role", "")
        if role:
            return f"message/{role}"
    ct = entry.get("customType", "")
    if ct:
        return f"{etype}/{ct}"
    return etype


def _load_entries(path: Path) -> list[dict]:
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _print_match_block(
    session_file: Path,
    entries: list[dict],
    texts: list[str],
    match_indices: list[int],
    context_lines: int,
) -> None:
    # Get CWD from session entry if present
    cwd = ""
    for e in entries[:5]:
        if e.get("type") == "session":
            cwd = e.get("cwd", "")
            break
    if not cwd:
        cwd = _decode_cwd(session_file)

    # Get session name if set
    name = ""
    for e in entries:
        if e.get("type") == "session_info":
            name = e.get("name", "")
            break

    ts_clean = session_file.name[:16].replace("T", " ").replace("-", ":", 2)

    print(f"\n{'=' * 72}")
    print(f"Session : {session_file.stem}")
    print(f"File    : {session_file}")
    print(f"CWD     : {cwd}")
    if name:
        print(f"Name    : {name}")
    print(f"Started : {ts_clean.replace(':', '-', 2)}")
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
            label = _entry_label(e)
            marker = ">>>" if i == mi else "   "
            excerpt = texts[i][:200].replace("\n", " ")
            print(f"{marker} [{i:4d}] {ts} {label:22s} {excerpt}")


def search(query: str, dirs: list[Path], context_lines: int) -> None:
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
    parser = argparse.ArgumentParser(
        description=dedent("""\
            Search Pi agent session JSONL files for a text query.
            Searches ~/.pi/agent/sessions/ by default.
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
    parser.add_argument(
        "--recent",
        metavar="N",
        type=int,
        default=0,
        help="Only search the N most recent sessions (0 = all)",
    )
    args = parser.parse_args()

    dirs = [_SESSIONS_DIR] + [Path(d) for d in args.extra_dirs]
    search(args.query, dirs, args.context)


if __name__ == "__main__":
    main()
