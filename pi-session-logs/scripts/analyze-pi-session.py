#!/usr/bin/env python3
"""Analyze a Pi agent session JSONL file.

Usage:
    uv run scripts/analyze-pi-session.py <session-file-or-id>
    uv run scripts/analyze-pi-session.py <session-file-or-id> --mode timeline
    uv run scripts/analyze-pi-session.py <session-file-or-id> --mode transcript
    uv run scripts/analyze-pi-session.py <session-file-or-id> --mode tools

Modes:
    timeline   (default) — one line per entry, streaming tokens merged
    transcript — full conversation turn by turn
    tools      — only tool calls and their results

The session argument may be:
  - A full path to a .jsonl file
  - A session UUID (searched under ~/.pi/agent/sessions/)
  - A timestamp prefix like "2026-03-07T10" (matched against filename)

Pi session files are at:
    ~/.pi/agent/sessions/<encoded-cwd>/<timestamp>_<uuid>.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from textwrap import dedent

_SESSIONS_ROOT = Path.home() / ".pi" / "agent" / "sessions"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _find_session_file(id_or_path: str) -> Path:
    p = Path(id_or_path)
    if p.exists():
        return p
    # Search under sessions root for matching filename stem or prefix
    for candidate in sorted(_SESSIONS_ROOT.rglob("*.jsonl")):
        stem = candidate.stem  # e.g. 2026-03-07T10-58-20-235Z_6d2bfa98-...
        if id_or_path in stem or stem.startswith(id_or_path):
            return candidate
        # Also match just the UUID part
        if "_" in stem and id_or_path in stem.split("_", 1)[1]:
            return candidate
    raise FileNotFoundError(f"Session not found: {id_or_path!r}")


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


# ---------------------------------------------------------------------------
# Entry parsing helpers
# ---------------------------------------------------------------------------

# Pi block types (camelCase, unlike Claude Code's snake_case)
#   text, toolCall, thinking  — in assistant messages
#   text                      — in user / toolResult messages


def _entry_label(e: dict) -> str:
    etype = e.get("type", "?")
    if etype == "message":
        msg = e.get("message", {})
        role = msg.get("role", "") if isinstance(msg, dict) else ""
        return f"message/{role}" if role else "message"
    ct = e.get("customType", "")
    if ct:
        return f"{etype}/{ct}"
    return etype


def _content_blocks(e: dict) -> list[dict]:
    msg = e.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content", [])
    if isinstance(content, list):
        return content
    if isinstance(content, str) and content:
        return [{"type": "text", "text": content}]
    return []


def _flat_text(e: dict) -> str:
    """Single-line text summary of a Pi session entry (for timeline mode)."""
    etype = e.get("type", "")

    if etype == "session":
        return f"cwd={e.get('cwd', '')} version={e.get('version', '')}"
    if etype == "session_info":
        return f"name={e.get('name', '')}"
    if etype == "model_change":
        return f"{e.get('provider', '')} / {e.get('modelId', '')}"
    if etype == "thinking_level_change":
        return e.get("thinkingLevel", "")
    if etype == "compaction":
        return e.get("summary", "")[:200]
    if etype in {"custom", "custom_message"}:
        data = e.get("data") or e.get("content", "")
        return str(data)[:200]

    msg = e.get("message", {})
    if not isinstance(msg, dict):
        return ""

    role = msg.get("role", "")
    parts = []

    if role == "toolResult":
        parts.append(
            f"[RESULT for {msg.get('toolName', '?')} id={msg.get('toolCallId', '?')[-8:]}]"
        )

    for block in _content_blocks(e):
        btype = block.get("type", "")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "toolCall":
            name = block.get("name", "?")
            args = json.dumps(block.get("arguments", {}), ensure_ascii=False)
            parts.append(f"[TOOL:{name} {args[:120]}]")
        elif btype == "thinking":
            parts.append(f"[THINKING: {block.get('thinking', '')[:80]}]")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Mode: timeline
# ---------------------------------------------------------------------------


def _mode_timeline(entries: list[dict]) -> None:
    for i, e in enumerate(entries):
        ts = e.get("timestamp", "")[:19]
        label = _entry_label(e)
        text = _flat_text(e).replace("\n", " ")[:200]
        print(f"  [{i:4d}] {ts} {label:24s} {text}")


# ---------------------------------------------------------------------------
# Mode: transcript
# ---------------------------------------------------------------------------


def _mode_transcript(entries: list[dict]) -> None:
    current_role: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        body = "".join(buf).strip()
        bar = "─" * 72
        print(f"\n{bar}")
        print(f"  {(current_role or '?').upper()}")
        print(bar)
        print(body)

    for e in entries:
        etype = e.get("type", "")

        # Surface compaction summaries as context
        if etype == "compaction":
            flush()
            buf.clear()
            current_role = "compaction"
            buf.append(e.get("summary", ""))
            flush()
            buf.clear()
            current_role = None
            continue

        if etype != "message":
            continue

        msg = e.get("message", {})
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "?")

        if role != current_role:
            flush()
            buf.clear()
            current_role = role

        if role == "toolResult":
            tid = msg.get("toolCallId", "?")
            tname = msg.get("toolName", "?")
            buf.append(f"\n\n[TOOL RESULT: {tname}  id={tid[-8:]}]\n")

        for block in _content_blocks(e):
            btype = block.get("type", "")
            if btype == "text":
                buf.append(block.get("text", ""))
            elif btype == "toolCall":
                name = block.get("name", "?")
                tid = block.get("id", "?")
                args = json.dumps(
                    block.get("arguments", {}), indent=2, ensure_ascii=False
                )
                buf.append(f"\n\n[TOOL CALL: {name}  id={tid[-8:]}]\n{args}\n")
            elif btype == "thinking":
                thought = block.get("thinking", "")
                buf.append(f"\n[THINKING]\n{thought}\n[/THINKING]\n")

    flush()


# ---------------------------------------------------------------------------
# Mode: tools
# ---------------------------------------------------------------------------


def _mode_tools(entries: list[dict]) -> None:
    pending: dict[str, str] = {}  # toolCallId → toolName

    for idx, e in enumerate(entries):
        ts = e.get("timestamp", "")[:19]
        etype = e.get("type", "")
        if etype != "message":
            continue

        msg = e.get("message", {})
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")

        if role == "toolResult":
            tid = msg.get("toolCallId", "?")
            tname = msg.get("toolName", pending.get(tid, "?"))
            content_blocks = _content_blocks(e)
            text = "\n".join(
                b.get("text", "") for b in content_blocks if b.get("type") == "text"
            )
            print(f"\n[{idx:4d}] {ts} RESULT  {tname}  (id={tid[-8:]})")
            print(text[:600])
            continue

        for block in _content_blocks(e):
            if block.get("type") == "toolCall":
                name = block.get("name", "?")
                tid = block.get("id", "?")
                args = json.dumps(
                    block.get("arguments", {}), indent=2, ensure_ascii=False
                )
                pending[tid] = name
                print(f"\n[{idx:4d}] {ts} CALL    {name}  (id={tid[-8:]})")
                print(args[:600])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=dedent("""\
            Analyze a Pi agent session JSONL file.
            Accepts a full path, session UUID, or timestamp prefix.
        """),
    )
    parser.add_argument("session", help="Session file path, UUID, or timestamp prefix")
    parser.add_argument(
        "--mode",
        choices=["timeline", "transcript", "tools"],
        default="timeline",
        help="Output mode (default: timeline)",
    )
    args = parser.parse_args()

    try:
        path = _find_session_file(args.session)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    entries = _load_entries(path)

    # Print header
    cwd = ""
    name = ""
    model = ""
    for e in entries[:10]:
        if e.get("type") == "session":
            cwd = e.get("cwd", "")
        if e.get("type") == "session_info":
            name = e.get("name", "")
        if e.get("type") == "model_change" and not model:
            model = f"{e.get('provider', '')}/{e.get('modelId', '')}"

    print(f"Session : {path.stem}")
    print(f"File    : {path}")
    print(f"CWD     : {cwd}")
    if name:
        print(f"Name    : {name}")
    if model:
        print(f"Model   : {model}")
    print(f"Entries : {len(entries)}")
    print()

    if args.mode == "timeline":
        _mode_timeline(entries)
    elif args.mode == "transcript":
        _mode_transcript(entries)
    elif args.mode == "tools":
        _mode_tools(entries)


if __name__ == "__main__":
    main()
