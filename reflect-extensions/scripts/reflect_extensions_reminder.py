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
import json
import os
import sys
import time
from pathlib import Path

import capture_learning

STATE_DIR = Path("~/.claude/reflect-extensions").expanduser()

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


def _count_block(block: dict) -> int:
    """Return 1 if a content block is a meaningful tool call, else 0."""
    if block.get("type") != "tool_use":
        return 0
    name = block.get("name", "")
    if name in MUTATING_TOOLS or name in EXTENSION_TOOLS or name.startswith("mcp__"):
        return 1
    if name == "Bash" and "git commit" in (block.get("input") or {}).get("command", ""):
        return 1
    return 0


def _count_line(line: str) -> int:
    """Count meaningful tool_use blocks in one transcript JSONL line."""
    if not line.strip():
        return 0
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return 0
    msg = rec.get("message", rec)
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return 0
    return sum(_count_block(b) for b in content if isinstance(b, dict))


def _count_meaningful_actions(transcript_path: str) -> int:
    """Scan the JSONL transcript and count meaningful tool actions."""
    if not transcript_path or not Path(transcript_path).exists():
        return 0
    try:
        with Path(transcript_path).open(encoding="utf-8", errors="ignore") as fh:
            return sum(_count_line(line) for line in fh)
    except OSError:
        return 0


def _marker(session_id: str) -> Path:
    return STATE_DIR / f"reminded-{session_id}.flag"


def _mark_reminded(session_id: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _marker(session_id).write_text("1", encoding="utf-8")
    except OSError:
        pass  # never block on state-write failure


def _prune_stale(directory: Path, patterns: tuple[str, ...], ttl_days: int) -> None:
    """Delete matching files older than ttl_days. Defensive: ignore all errors."""
    if not directory.exists():
        return
    cutoff = time.time() - ttl_days * 86400
    try:
        for pattern in patterns:
            for path in directory.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue
    except OSError:
        pass


def _prune_stale_state(ttl_days: int) -> None:
    """Prune expired reminder markers and capture queues.

    Queues deliberately outlive the session that produced them: /reflect-extensions
    can be run later against an earlier session. They are only dropped once they are
    older than the marker TTL, at which point nobody is going to reflect on them.
    """
    _prune_stale(STATE_DIR, ("reminded-*.flag",), ttl_days)
    _prune_stale(STATE_DIR / "queue", ("*.jsonl", "*.jsonl.done"), ttl_days)


def _cleanup(session_id: str, ttl_days: int) -> None:
    """SessionEnd: remove this session's marker, then prune stale state."""
    try:
        m = _marker(session_id)
        if m.exists():
            m.unlink()
    except OSError:
        pass
    _prune_stale_state(ttl_days)


def _emit(message: str) -> None:
    if os.environ.get("REFLECT_EXT_PLAINTEXT") == "1":
        print()
        print(message)
        print()
        return
    print(json.dumps({"systemMessage": message, "suppressOutput": True}))


def main() -> int:
    """Route the hook event to a reminder or to state cleanup."""
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
    if remind_once and _marker(session_id).exists():
        return 0

    min_actions = int(os.environ.get("REFLECT_EXT_MIN_ACTIONS", "3"))
    actions = _count_meaningful_actions(transcript_path)
    queued = capture_learning.queue_depth(session_id)

    # PreCompact is rare and naturally marks a long session, so relax the gate.
    gate = 1 if event == "PreCompact" else min_actions
    # A queued correction is worth reflecting on even in an otherwise quiet session.
    if actions < gate and queued == 0:
        return 0

    queued_note = f", {queued} queued learning(s)" if queued else ""
    msg = (
        f"End of a working session ({actions} meaningful actions{queued_note}). "
        "Run /reflect-extensions to capture learnings (trial-and-error fixes, "
        "reusable scripts, new workflows) and audit which skills, MCP servers, "
        "slash commands, subagents, hooks, and plugins were used \u2014 so they can "
        "be improved or created."
    )
    _emit(msg)

    if remind_once:
        _mark_reminded(session_id)
    # Opportunistic prune so the state dir stays tidy even without SessionEnd.
    _prune_stale_state(ttl_days)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - a hook must never break the session
        print(f"Warning: reflect_extensions_reminder.py error: {e}", file=sys.stderr)
        sys.exit(0)
