#!/usr/bin/env python3
"""Analyze a Claude Code session JSONL file.

Usage:
    uv run scripts/analyze-session.py <session-file-or-id>
    uv run scripts/analyze-session.py <session-file-or-id> --mode timeline
    uv run scripts/analyze-session.py <session-file-or-id> --mode transcript
    uv run scripts/analyze-session.py <session-file-or-id> --mode tools

Modes:
    timeline   (default) — one line per entry; groups streaming tokens
    transcript — full reconstructed conversation, turn by turn
    tools      — only tool calls and their results

The session file may be:
  - A full path to a .jsonl file
  - A session ID (stem of the filename, e.g. a01cdfa4-5944-…)
    The script searches ~/.claude/ recursively for a matching file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from textwrap import dedent

_SEARCH_ROOT = Path.home() / ".claude"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _find_session_file(id_or_path: str) -> Path:
    p = Path(id_or_path)
    if p.exists():
        return p
    # Search by stem (session ID)
    for candidate in _SEARCH_ROOT.rglob("*.jsonl"):
        if id_or_path in {candidate.stem, candidate.name}:
            return candidate
    msg = f"Session not found: {id_or_path!r}"
    raise FileNotFoundError(msg)


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


# ---------------------------------------------------------------------------
# Entry parsing helpers
# ---------------------------------------------------------------------------


def _entry_label(e: dict) -> str:  # type: ignore[type-arg]
    etype = e.get("type", "?")
    msg = e.get("message")
    role = msg.get("role", "") if isinstance(msg, dict) else ""
    if etype == "queue-operation":
        op = e.get("operation", "?")
        return f"queue/{op}"
    return f"{etype}/{role}" if role else etype


def _content_blocks(e: dict) -> list[dict]:  # type: ignore[type-arg]
    """Return the content block list from an entry, normalising all shapes."""
    msg = e.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content", "")
    if isinstance(content, list):
        return content  # type: ignore[return-value]
    if isinstance(content, str) and content:
        return [{"type": "text", "text": content}]
    return []


def _flat_text(e: dict) -> str:  # type: ignore[type-arg]
    """Single-line text summary of the entry (for timeline mode)."""
    if e.get("type") == "queue-operation":
        c = e.get("content", "")
        return str(c)[:300] if c else ""
    parts = []
    for block in _content_blocks(e):
        btype = block.get("type", "")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_use":
            name = block.get("name", "?")
            inp = json.dumps(block.get("input", {}), ensure_ascii=False)
            parts.append(f"[TOOL:{name} {inp[:120]}]")
        elif btype == "tool_result":
            tid = block.get("tool_use_id", "?")[-8:]
            c = block.get("content", "")
            preview = str(c)[:120] if c else ""
            parts.append(f"[RESULT:{tid} {preview}]")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Mode: timeline
# ---------------------------------------------------------------------------


def _mode_timeline(entries: list[dict]) -> None:  # type: ignore[type-arg]
    """Print one line per entry, merging consecutive streaming text tokens."""
    i = 0
    while i < len(entries):
        e = entries[i]
        ts = e.get("timestamp", "")[:19]
        label = _entry_label(e)

        # Merge consecutive same-role single-token assistant text entries
        if e.get("type") == "assistant":
            blocks = _content_blocks(e)
            if len(blocks) == 1 and blocks[0].get("type") == "text":
                # Accumulate streaming tokens
                buf = [blocks[0].get("text", "")]
                j = i + 1
                while j < len(entries):
                    ne = entries[j]
                    nb = _content_blocks(ne)
                    if (
                        ne.get("type") == "assistant"
                        and len(nb) == 1
                        and nb[0].get("type") == "text"
                        and len(nb[0].get("text", "")) < 10  # noqa: PLR2004
                    ):
                        buf.append(nb[0].get("text", ""))
                        j += 1
                    else:
                        break
                merged = "".join(buf).replace("\n", " ")[:200]
                end_ts = entries[j - 1].get("timestamp", "")[:19]
                span = f"{ts}-{end_ts[11:]}" if j - 1 > i else ts
                count = j - i
                suffix = f" ({count} tokens)" if count > 1 else ""
                print(f"  [{i:4d}] {span} {label:20s} {merged}{suffix}")
                i = j
                continue

        text = _flat_text(e).replace("\n", " ")[:200]
        print(f"  [{i:4d}] {ts} {label:20s} {text}")
        i += 1


# ---------------------------------------------------------------------------
# Mode: transcript
# ---------------------------------------------------------------------------


def _mode_transcript(entries: list[dict]) -> None:  # type: ignore[type-arg]
    """Print the full reconstructed conversation, grouped by turn."""
    current_role: str | None = None
    text_buf: list[str] = []

    def flush() -> None:
        if not text_buf:
            return
        label = current_role or "?"
        body = "".join(text_buf).strip()
        bar = "─" * 72
        print(f"\n{bar}")
        print(f"  {label.upper()}")
        print(bar)
        print(body)

    for e in entries:
        etype = e.get("type", "")

        if etype == "queue-operation" and e.get("operation") == "enqueue":
            flush()
            text_buf.clear()
            current_role = "user (queued)"
            text_buf.append(str(e.get("content", "")))
            continue

        if etype not in {"user", "assistant"}:
            continue

        msg = e.get("message", {})
        role = msg.get("role", "") if isinstance(msg, dict) else ""

        if role != current_role:
            flush()
            text_buf.clear()
            current_role = role

        for block in _content_blocks(e):
            btype = block.get("type", "")
            if btype == "text":
                text_buf.append(block.get("text", ""))
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = json.dumps(block.get("input", {}), indent=2, ensure_ascii=False)
                text_buf.append(f"\n\n[TOOL CALL: {name}]\n{inp}\n")
            elif btype == "tool_result":
                tid = block.get("tool_use_id", "?")
                c = block.get("content", "")
                preview = str(c)[:500]
                text_buf.append(f"\n\n[TOOL RESULT for {tid}]\n{preview}\n")

    flush()


# ---------------------------------------------------------------------------
# Mode: tools
# ---------------------------------------------------------------------------


def _mode_tools(entries: list[dict]) -> None:  # type: ignore[type-arg]
    """Print only tool calls and results."""
    pending: dict[
        str, dict
    ] = {}  # tool_use_id → tool_use block  # type: ignore[type-arg]

    for idx, e in enumerate(entries):
        ts = e.get("timestamp", "")[:19]
        for block in _content_blocks(e):
            btype = block.get("type", "")
            if btype == "tool_use":
                tid = block.get("id", "?")
                name = block.get("name", "?")
                inp = json.dumps(block.get("input", {}), indent=2, ensure_ascii=False)
                print(f"\n[{idx:4d}] {ts} TOOL CALL: {name}  (id={tid[-8:]})")
                print(inp[:600])
                pending[tid] = block
            elif btype == "tool_result":
                tid = block.get("tool_use_id", "?")
                c = block.get("content", "")
                call_name = pending.get(tid, {}).get("name", "?")
                print(f"\n[{idx:4d}] {ts} TOOL RESULT: {call_name}  (id={tid[-8:]})")
                print(str(c)[:600])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and dispatch to the selected analysis mode."""
    parser = argparse.ArgumentParser(
        description=dedent("""\
            Analyze a Claude Code session JSONL file.
            Accepts a full path or just the session ID (searched under ~/.claude/).
        """),
    )
    parser.add_argument("session", help="Session file path or session ID stem")
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

    print(f"Session : {path.stem}")
    print(f"File    : {path}")
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
