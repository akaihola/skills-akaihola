"""Exercise interrupted handoffs without creating live agent sessions."""

import argparse
import importlib.util
import json
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/start_thread.py"
SPEC = importlib.util.spec_from_file_location("start_thread", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class LostReplyServer:
    """Accept the first request, then lose its reply as a transport could."""

    url = "http://127.0.0.1:3773"

    def __init__(self, snapshot: dict) -> None:
        """Keep only the scoped fixture snapshot and submitted commands."""
        self.data = snapshot
        self.commands: list[dict] = []

    def snapshot(self) -> dict:
        """Return fixture state, including any accepted thread."""
        return self.data

    def call(self, method: str, command: dict) -> dict:
        """Simulate acceptance followed by a lost reply."""  # ruff: ignore[docstring-missing-exception]
        if method != "orchestration.dispatchCommand":
            msg = "Unexpected test method"
            raise ValueError(msg)
        self.commands.append(command)
        thread = dict(command["bootstrap"]["createThread"])
        thread["id"] = command["threadId"]
        thread["latestTurn"] = {"state": "running"}
        self.data["threads"].append(thread)
        msg = "Connection lost after acceptance"
        raise TimeoutError(msg)


def test_resume_after_lost_reply_does_not_submit_again() -> None:
    """An accepted request survives a lost reply without a second turn."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        prompt = root / "prompt.txt"
        prompt.write_text("Perform the requested fixture task.", encoding="utf-8")
        settings = {
            "modelSelection": {
                "instanceId": "codex",
                "model": "fixture-model",
                "options": [{"id": "reasoningEffort", "value": "medium"}],
            },
            "runtimeMode": "approval-required",
            "interactionMode": "plan",
        }
        snapshot = {
            "projects": [{"id": "project", "workspaceRoot": str(root)}],
            "threads": [{"id": "parent", "projectId": "project", **settings}],
        }
        server = LostReplyServer(snapshot)
        args = argparse.Namespace(
            workspace=str(root),
            parent_thread="parent",
            prompt_file=str(prompt),
            title="Fixture task",
            base_dir=None,
            shared_checkout=False,
            branch="fixture-task",
            base_branch="main",
        )
        with (
            patch.object(helper.Path, "home", return_value=root),
            pytest.raises(TimeoutError),
        ):
            helper.start(args, server, snapshot)
        record_path = next((root / ".local/state/t3-start-thread").glob("*.json"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert stat.S_IMODE(record_path.stat().st_mode) == 0o600
        assert "token" not in record
        command = record["command"]
        for key, value in settings.items():
            assert command[key] == value
            assert command["bootstrap"]["createThread"][key] == value
        assert command["bootstrap"]["prepareWorktree"]["requireWorktree"]
        with patch("builtins.print"):
            helper.submit(server, record_path, record)
        assert len(server.commands) == 1
        assert record["thread"]["latestTurn"]["state"] == "running"


def test_accepted_but_missing_thread_is_not_recreated() -> None:
    """A removed or temporarily hidden accepted thread is not resurrected."""
    server = LostReplyServer({"threads": []})
    record = {"command": {"threadId": "missing"}, "accepted": True}
    with pytest.raises(RuntimeError):
        helper.submit(server, Path("unused.json"), record)
    assert server.commands == []
