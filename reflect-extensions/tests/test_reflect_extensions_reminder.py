#!/usr/bin/env python3
"""Tests for the reflect-extensions reminder/cleanup hook script.

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "pytest>=7.0.0",
# ]
# ///
"""

import io
import json
import sys
import time
from pathlib import Path

import pytest

# Add parent scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import capture_learning as cl  # noqa: E402
import reflect_extensions_reminder as rer  # noqa: E402


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Redirect the module's marker directory into a temp dir.

    capture_learning too: the reminder reads the queue through it.
    """
    d = tmp_path / "state"
    monkeypatch.setattr(rer, "STATE_DIR", d)
    monkeypatch.setattr(cl, "STATE_DIR", d)
    return d


def _write_transcript(tmp_path, blocks):
    """Write a JSONL transcript of assistant messages with given tool_use blocks."""
    path = tmp_path / "transcript.jsonl"
    lines = []
    for name, cmd in blocks:
        inp = {"command": cmd} if cmd is not None else {}
        rec = {"message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}
        lines.append(json.dumps(rec))
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _run_main(monkeypatch, payload):
    """Feed a hook payload on stdin and run main(), returning its exit code."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return rer.main()


# --- _count_meaningful_actions -------------------------------------------------

def test_count_includes_edits_mcp_and_git_commit(tmp_path) -> None:
    path = _write_transcript(
        tmp_path,
        [
            ("Edit", None),
            ("Write", None),
            ("mcp__github__create_pr", None),
            ("Bash", "git commit -m x"),
        ],
    )
    assert rer._count_meaningful_actions(path) == 4


def test_count_ignores_non_mutating_and_non_commit_bash(tmp_path) -> None:
    path = _write_transcript(
        tmp_path,
        [
            ("Read", None),
            ("Grep", None),
            ("Bash", "ls -la"),  # not a commit -> ignored
        ],
    )
    assert rer._count_meaningful_actions(path) == 0


def test_count_missing_file_is_zero() -> None:
    assert rer._count_meaningful_actions("/nonexistent/transcript.jsonl") == 0


def test_count_skips_malformed_lines(tmp_path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(
        "not json\n"
        + json.dumps({"message": {"content": [{"type": "tool_use", "name": "Edit"}]}})
        + "\n",
        encoding="utf-8",
    )
    assert rer._count_meaningful_actions(str(path)) == 1


# --- markers, debounce, prune, cleanup ----------------------------------------

def test_mark_and_already_reminded(state_dir) -> None:
    assert rer._already_reminded("s1") is False
    rer._mark_reminded("s1")
    assert rer._already_reminded("s1") is True


def test_prune_stale_markers_removes_old_keeps_new(state_dir) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    old = state_dir / "reminded-old.flag"
    new = state_dir / "reminded-new.flag"
    old.write_text("1", encoding="utf-8")
    new.write_text("1", encoding="utf-8")
    # Backdate the "old" marker by 10 days.
    ten_days_ago = time.time() - 10 * 86400
    import os

    os.utime(old, (ten_days_ago, ten_days_ago))
    rer._prune_stale_state(ttl_days=7)
    assert not old.exists()
    assert new.exists()


def test_cleanup_removes_session_marker(state_dir) -> None:
    rer._mark_reminded("s2")
    assert rer._already_reminded("s2") is True
    rer._cleanup("s2", ttl_days=7)
    assert rer._already_reminded("s2") is False


# --- main() dispatch -----------------------------------------------------------

def test_main_stop_above_threshold_emits_and_marks(
    tmp_path, state_dir, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("REFLECT_EXT_PLAINTEXT", "1")
    transcript = _write_transcript(
        tmp_path, [("Edit", None), ("Write", None), ("MultiEdit", None)]
    )
    payload = {
        "hook_event_name": "Stop",
        "session_id": "live1",
        "transcript_path": transcript,
        "stop_hook_active": False,
    }
    assert _run_main(monkeypatch, payload) == 0
    out = capsys.readouterr().out
    assert "/reflect-extensions" in out
    assert rer._already_reminded("live1") is True


def test_main_stop_debounced_on_second_call(
    tmp_path, state_dir, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("REFLECT_EXT_PLAINTEXT", "1")
    transcript = _write_transcript(
        tmp_path, [("Edit", None), ("Write", None), ("MultiEdit", None)]
    )
    payload = {
        "hook_event_name": "Stop",
        "session_id": "live2",
        "transcript_path": transcript,
        "stop_hook_active": False,
    }
    _run_main(monkeypatch, payload)
    capsys.readouterr()  # clear first reminder
    _run_main(monkeypatch, payload)
    assert capsys.readouterr().out.strip() == ""


def test_main_stop_below_threshold_silent(
    tmp_path, state_dir, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("REFLECT_EXT_PLAINTEXT", "1")
    transcript = _write_transcript(tmp_path, [("Edit", None)])  # 1 < default 3
    payload = {
        "hook_event_name": "Stop",
        "session_id": "live3",
        "transcript_path": transcript,
        "stop_hook_active": False,
    }
    _run_main(monkeypatch, payload)
    assert capsys.readouterr().out.strip() == ""
    assert rer._already_reminded("live3") is False


def test_main_precompact_relaxed_gate_fires_on_one_action(
    tmp_path, state_dir, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("REFLECT_EXT_PLAINTEXT", "1")
    transcript = _write_transcript(tmp_path, [("Edit", None)])  # 1 action
    payload = {
        "hook_event_name": "PreCompact",
        "session_id": "live4",
        "transcript_path": transcript,
        "trigger": "auto",
    }
    _run_main(monkeypatch, payload)
    assert "/reflect-extensions" in capsys.readouterr().out


def test_main_stop_active_is_silent(tmp_path, state_dir, monkeypatch, capsys) -> None:
    monkeypatch.setenv("REFLECT_EXT_PLAINTEXT", "1")
    transcript = _write_transcript(
        tmp_path, [("Edit", None), ("Write", None), ("MultiEdit", None)]
    )
    payload = {
        "hook_event_name": "Stop",
        "session_id": "live5",
        "transcript_path": transcript,
        "stop_hook_active": True,
    }
    _run_main(monkeypatch, payload)
    assert capsys.readouterr().out.strip() == ""


def test_main_session_end_cleans_marker(state_dir, monkeypatch, capsys) -> None:
    rer._mark_reminded("live6")
    payload = {
        "hook_event_name": "SessionEnd",
        "session_id": "live6",
        "reason": "clear",
    }
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().out.strip() == ""
    assert rer._already_reminded("live6") is False
