"""Integration tests across the two reflect-extensions hooks.

capture_learning.py writes the queue; reflect_extensions_reminder.py reads it to
decide whether to remind and what to say. These tests cover that seam.

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "pytest>=7.0.0",
# ]
# ///
"""

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

# Add parent scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import capture_learning as cl  # ty: ignore[unresolved-import]
import reflect_extensions_reminder as rer  # ty: ignore[unresolved-import]


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point both hook modules at the same temp state dir."""
    d = tmp_path / "state"
    monkeypatch.setattr(cl, "STATE_DIR", d)
    monkeypatch.setattr(rer, "STATE_DIR", d)
    monkeypatch.setenv("REFLECT_EXT_PLAINTEXT", "1")
    return d


def _capture(
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    session_id: str = "s1",
) -> None:
    """Run the capture hook on one prompt."""
    payload = {"prompt": prompt, "session_id": session_id}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    cl.main()


def _remind(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    session_id: str = "s1",
    transcript: str = "",
) -> str:
    """Run the reminder hook on a Stop event and return what it printed."""
    payload = {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "transcript_path": transcript,
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rer.main()
    return capsys.readouterr().out


def test_quiet_session_with_a_queued_learning_still_reminds(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A correction is worth reflecting on even with no file edits or commits."""
    assert not _remind(monkeypatch, capsys)  # nothing happened yet
    _capture(monkeypatch, "no, use ripgrep instead")
    out = _remind(monkeypatch, capsys)
    assert "1 queued learning(s)" in out
    assert state_dir.exists()


def test_reminder_reports_the_queue_depth(
    state_dir: Path,  # noqa: ARG001 - patches module state
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The count in the reminder matches what was queued."""
    for prompt in ("no, use uv", "don't use pip", "from now on always run nextest"):
        _capture(monkeypatch, prompt)
    assert "3 queued learning(s)" in _remind(monkeypatch, capsys)
    assert rer._queue_depth("s1") == 3  # noqa: SLF001


def test_queues_survive_session_end(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh queue outlives its session so it can be drained later."""
    _capture(monkeypatch, "no, use ripgrep instead")
    rer._cleanup("s1", ttl_days=7)  # noqa: SLF001
    assert (state_dir / "queue" / "s1.jsonl").exists()


def test_stale_queues_are_pruned(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A queue nobody reflected on within the TTL is dropped."""
    _capture(monkeypatch, "no, use ripgrep instead")
    queue = state_dir / "queue" / "s1.jsonl"
    old = time.time() - 30 * 86400
    os.utime(queue, (old, old))
    rer._cleanup("s1", ttl_days=7)  # noqa: SLF001
    assert not queue.exists()


def test_stale_drained_queues_are_pruned(
    state_dir: Path,
) -> None:
    """A drained queue is pruned after it exceeds the TTL."""
    queue_dir = state_dir / "queue"
    queue_dir.mkdir(parents=True)
    old_queue = queue_dir / "s1.jsonl.done"
    fresh_queue = queue_dir / "s2.jsonl.done"
    old_queue.write_text("drained\n", encoding="utf-8")
    fresh_queue.write_text("drained\n", encoding="utf-8")
    old = time.time() - 30 * 86400
    os.utime(old_queue, (old, old))

    rer._cleanup("s1", ttl_days=7)  # noqa: SLF001

    assert not old_queue.exists()
    assert fresh_queue.exists()
