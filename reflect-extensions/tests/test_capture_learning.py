"""Tests for the reflect-extensions learning-capture hook script.

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
from pathlib import Path

import pytest

# Add parent scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import capture_learning as cl  # ty: ignore[unresolved-import]


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module's state directory into a temp dir."""
    d = tmp_path / "state"
    monkeypatch.setattr(cl, "STATE_DIR", d)
    return d


def _run(monkeypatch: pytest.MonkeyPatch, payload: dict) -> int:
    """Feed a hook payload to main() via stdin and return its exit code."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return cl.main()


def _records(state_dir: Path, session_id: str = "s1") -> list[dict]:
    """Read back the queued records for a session."""
    path = state_dir / "queue" / f"{session_id}.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


@pytest.mark.parametrize(
    ("prompt", "kind"),
    [
        ("no, use uv run instead of pip", "correction"),
        ("don't use os.path here", "correction"),
        ("älä käytä pip:iä", "correction"),
        ("from now on always run nextest", "preference"),
        ("that didn't work, still failing", "failure"),
        ("exactly, that's what I meant", "praise"),
    ],
)
def test_signal_kinds_are_detected(prompt: str, kind: str) -> None:
    """Each signal family is recognised, in English and in Finnish."""
    assert kind in [k for k, _ in cl.match_signals(prompt)]


def test_neutral_prompt_is_not_queued(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ordinary request produces no queue file at all."""
    payload = {"prompt": "add a test for the parser", "session_id": "s1"}
    assert _run(monkeypatch, payload) == 0
    assert _records(state_dir) == []


def test_correction_is_queued(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A correction is queued with its kind, confidence, and origin."""
    payload = {"prompt": "no, use ripgrep instead", "session_id": "s1", "cwd": "/repo"}
    _run(monkeypatch, payload)
    (record,) = _records(state_dir)
    assert record["kinds"] == ["correction"]
    assert record["confidence"] == pytest.approx(0.90)
    assert record["cwd"] == "/repo"


def test_corroborating_signals_raise_confidence() -> None:
    """Two distinct signal families score higher than either alone."""
    single = cl.score(cl.match_signals("no, use uv"))
    both = cl.score(cl.match_signals("that didn't work — no, use uv instead"))
    assert both > single


def test_slash_commands_are_ignored(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invoking a command is not a correction, even with trigger words in it."""
    payload = {"prompt": "/reflect-extensions don't use the cache", "session_id": "s1"}
    _run(monkeypatch, payload)
    assert _records(state_dir) == []


def test_capture_can_be_disabled(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REFLECT_EXT_CAPTURE=0 turns the hook into a no-op."""
    monkeypatch.setenv("REFLECT_EXT_CAPTURE", "0")
    _run(monkeypatch, {"prompt": "no, use ripgrep instead", "session_id": "s1"})
    assert _records(state_dir) == []


def test_secrets_are_redacted(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials never reach the queue file."""
    payload = {"prompt": "no, use token=ghp_abcdefghijklmnop1234", "session_id": "s1"}
    _run(monkeypatch, payload)
    (record,) = _records(state_dir)
    assert "ghp_" not in record["excerpt"]
    assert "[REDACTED]" in record["excerpt"]


def test_complete_pem_private_key_block_is_redacted(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A multiline PEM private-key block is removed from the queued excerpt."""
    pem_body = "SYNTHETIC-PEM-BODY-DO-NOT-LEAK"
    prompt = (
        "no, use the secure setting instead; before the key;\n"
        "-----BEGIN PRIVATE KEY-----\n"
        f"{pem_body}\n"
        "-----END PRIVATE KEY-----\n"
        "after the key"
    )
    _run(monkeypatch, {"prompt": prompt, "session_id": "s1"})
    (record,) = _records(state_dir)

    assert "before the key" in record["excerpt"]
    assert "after the key" in record["excerpt"]
    assert "[REDACTED]" in record["excerpt"]
    assert record["excerpt"].count("[REDACTED]") == 1
    assert pem_body not in record["excerpt"]
    assert "-----BEGIN PRIVATE KEY-----" not in record["excerpt"]
    assert "-----END PRIVATE KEY-----" not in record["excerpt"]


def test_pem_redaction_does_not_cross_an_unrelated_pem_delimiter(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed key candidate does not consume an unrelated PEM block."""
    unrelated_body = "SYNTHETIC-CERTIFICATE-BODY-MUST-REMAIN"
    prompt = (
        "no, use the secure setting instead;\n"
        "-----BEGIN PRIVATE KEY-----\n"
        "SYNTHETIC-KEY-BODY\n"
        "-----BEGIN X9.42 DH PARAMETERS-----\n"
        f"{unrelated_body}\n"
        "-----END X9.42 DH PARAMETERS-----\n"
        "-----END PRIVATE KEY-----"
    )
    _run(monkeypatch, {"prompt": prompt, "session_id": "s1"})
    (record,) = _records(state_dir)

    assert unrelated_body in record["excerpt"]
    assert "[REDACTED]" not in record["excerpt"]


def test_excerpt_is_truncated(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Long prompts are stored truncated, not in full."""
    monkeypatch.setenv("REFLECT_EXT_EXCERPT_LEN", "40")
    _run(monkeypatch, {"prompt": "no, use " + "x" * 500, "session_id": "s1"})
    (record,) = _records(state_dir)
    assert len(record["excerpt"]) == 40


def test_queue_is_capped(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-session queue stops growing at REFLECT_EXT_QUEUE_MAX."""
    monkeypatch.setenv("REFLECT_EXT_QUEUE_MAX", "2")
    for _ in range(5):
        _run(monkeypatch, {"prompt": "no, use ripgrep instead", "session_id": "s1"})
    assert len(_records(state_dir)) == 2


def test_malformed_stdin_is_survivable(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garbage on stdin exits cleanly without writing anything."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert cl.main() == 0
    assert _records(state_dir) == []


def test_queue_depth_counts_records(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """queue_depth reports the number the reminder hook will surface."""
    assert cl.queue_depth("s1") == 0
    _run(monkeypatch, {"prompt": "no, use ripgrep instead", "session_id": "s1"})
    assert cl.queue_depth("s1") == 1
    assert (state_dir / "queue" / "s1.jsonl").exists()
