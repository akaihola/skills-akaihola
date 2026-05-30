#!/usr/bin/env python3
"""Remind to run /reflect-extensions at the end of a working session.

Handles three hook events (auto-detected from stdin via hook_event_name):
  * Stop / PreCompact -> emit a debounced, non-intrusive reminder
  * SessionEnd        -> clean up this session's marker and prune stale ones

Cross-platform (Windows, macOS, Linux). Mirrors the claude-reflect hook style:
never blocks, always exits 0 on error.

Why debounce on Stop:
  The Stop event fires at the end of EVERY assistant turn, not just when you
  walk away. To approximate "end of a working session" this script:
    1. reminds at most once per session (tracked by a marker file), and
    2. only if the session did meaningful work worth reflecting on
       (a threshold of edits / bash commits / skill / subagent / MCP calls).
  PreCompact fires far less often, so its gate is relaxed. SessionEnd then
  removes the per-session marker so the state dir does not accumulate forever.

Config via env vars:
  REFLECT_EXT_MIN_ACTIONS      Minimum meaningful actions to trigger (default 3)
  REFLECT_EXT_REMIND_ONCE      "1" = at most one reminder per session (default "1")
  REFLECT_EXT_PLAINTEXT        "1" = print plain text instead of JSON systemMessage
  REFLECT_EXT_MARKER_TTL_DAYS  Prune markers older than N days (default 7)
"""
import sys
import os
import json
import time
from pathlib import Path

STATE_DIR = Path(os.path.expanduser("~/.claude/reflect-extensions"))

# Tool names that signal a session worth reflecting on.
MUTATING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
EXTENSION_TOOLS = {"Skill", "Task"}  # skill/command invocation, subagent dispatch


def _read_input() -> dict:
    raw = sys.stdin.read()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _count_meaningful_actions(transcript_path: str) -> int:
    """Scan the JSONL transcript and count meaningful tool actions."""
    if not transcript_path or not os.path.exists(transcript_path):
        return 0
    count = 0
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message", rec)
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "")
                    if (
                        name in MUTATING_TOOLS
                        or name in EXTENSION_TOOLS
                        or name.startswith("mcp__")
                    ):
                        count += 1
                    elif name == "Bash":
                        cmd = (block.get("input") or {}).get("command", "")
                        if "git commit" in cmd:
                            count += 1
    except OSError:
        return 0
    return count


def _marker(session_id: str) -> Path:
    return STATE_DIR / f"reminded-{session_id}.flag"


def _already_reminded(session_id: str) -> bool:
    return _marker(session_id).exists()


def _mark_reminded(session_id: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _marker(session_id).write_text("1", encoding="utf-8")
    except OSError:
        pass  # never block on state-write failure


def _prune_stale_markers(ttl_days: int) -> None:
    """Delete marker files older than ttl_days. Defensive: ignore all errors."""
    if not STATE_DIR.exists():
        return
    cutoff = time.time() - ttl_days * 86400
    try:
        for flag in STATE_DIR.glob("reminded-*.flag"):
            try:
                if flag.stat().st_mtime < cutoff:
                    flag.unlink()
            except OSError:
                continue
    except OSError:
        pass


def _cleanup(session_id: str, ttl_days: int) -> None:
    """SessionEnd: remove this session's marker, then prune stale ones."""
    try:
        m = _marker(session_id)
        if m.exists():
            m.unlink()
    except OSError:
        pass
    _prune_stale_markers(ttl_days)


def _emit(message: str) -> None:
    if os.environ.get("REFLECT_EXT_PLAINTEXT") == "1":
        print()
        print(message)
        print()
        return
    print(json.dumps({"systemMessage": message, "suppressOutput": True}))


def main() -> int:
    data = _read_input()
    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "unknown")
    transcript_path = data.get("transcript_path", "")
    ttl_days = int(os.environ.get("REFLECT_EXT_MARKER_TTL_DAYS", "7"))

    # SessionEnd: clean up and stop. No reminder (the session is over).
    if event == "SessionEnd":
        _cleanup(session_id, ttl_days)
        return 0

    # Stop hooks can re-enter; if we're already inside a stop continuation, bail.
    if data.get("stop_hook_active"):
        return 0

    remind_once = os.environ.get("REFLECT_EXT_REMIND_ONCE", "1") == "1"
    if remind_once and _already_reminded(session_id):
        return 0

    min_actions = int(os.environ.get("REFLECT_EXT_MIN_ACTIONS", "3"))
    actions = _count_meaningful_actions(transcript_path)

    # PreCompact is rare and naturally marks a long session, so relax the gate.
    gate = 1 if event == "PreCompact" else min_actions
    if actions < gate:
        return 0

    msg = (
        f"End of a working session ({actions} meaningful actions). "
        "Run /reflect-extensions to capture learnings (trial-and-error fixes, "
        "reusable scripts, new workflows) and audit which skills, MCP servers, "
        "slash commands, subagents, hooks, and plugins were used \u2014 so they can "
        "be improved or created."
    )
    _emit(msg)

    if remind_once:
        _mark_reminded(session_id)
    # Opportunistic prune so the state dir stays tidy even without SessionEnd.
    _prune_stale_markers(ttl_days)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never block on errors
        print(f"Warning: reflect_extensions_reminder.py error: {e}", file=sys.stderr)
        sys.exit(0)
