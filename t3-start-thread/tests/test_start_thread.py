"""Exercise interrupted handoffs and messaging without live agent sessions."""

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
            settings=None,
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


def test_settings_file_replaces_parent() -> None:
    """A settings file starts a thread when no parent thread is available."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        prompt = root / "prompt.txt"
        prompt.write_text("Perform the scheduled fixture task.", encoding="utf-8")
        settings = {
            "modelSelection": {"instanceId": "claudeAgent", "model": "fixture"},
            "runtimeMode": "full-access",
            "interactionMode": "default",
        }
        settings_file = root / "settings.json"
        settings_file.write_text(json.dumps(settings), encoding="utf-8")
        snapshot = {
            "projects": [{"id": "project", "workspaceRoot": str(root)}],
            "threads": [],
        }
        server = LostReplyServer(snapshot)
        args = argparse.Namespace(
            workspace=str(root),
            parent_thread=None,
            settings=str(settings_file),
            prompt_file=str(prompt),
            title="Scheduled task",
            base_dir=None,
            shared_checkout=True,
            branch=None,
            base_branch=None,
        )
        with (
            patch.object(helper.Path, "home", return_value=root),
            pytest.raises(TimeoutError),
        ):
            helper.start(args, server, snapshot)
        command = server.commands[0]
        for key, value in settings.items():
            assert command[key] == value
            assert command["bootstrap"]["createThread"][key] == value
        assert "prepareWorktree" not in command["bootstrap"]

        settings_file.write_text(json.dumps({"runtimeMode": "x"}), encoding="utf-8")
        with pytest.raises(ValueError, match="Settings file must hold exactly"):
            helper.start(args, server, snapshot)
        assert len(server.commands) == 1


def test_accepted_but_missing_thread_is_not_recreated() -> None:
    """A removed or temporarily hidden accepted thread is not resurrected."""
    server = LostReplyServer({"threads": []})
    record = {
        "command": {"threadId": "missing", "bootstrap": {}},
        "accepted": True,
    }
    with pytest.raises(RuntimeError):
        helper.submit(server, Path("unused.json"), record)
    assert server.commands == []


class MessageServer:
    """Track messages separately from the already existing target thread."""

    url = "http://127.0.0.1:3773"

    def __init__(self, thread: dict) -> None:
        """Keep a target and switches for transport failures around acceptance."""
        self.thread = thread
        self.commands: list[dict] = []
        self.lose_before_accept = False
        self.lose_after_accept = False

    def thread_snapshot(self, thread_id: str) -> dict:
        """Return the target's persisted messages."""
        assert thread_id == self.thread["id"]
        return self.thread

    def call(self, method: str, command: dict) -> dict:
        """Persist a message, with optional simulated transport loss.

        :raises TimeoutError: When simulating loss before or after acceptance.
        """  # ruff: ignore[docstring-missing-exception] - Sphinx field is above.
        assert method == "orchestration.dispatchCommand"
        assert command["threadId"] == self.thread["id"]
        assert "bootstrap" not in command
        self.commands.append(command)
        if self.lose_before_accept:
            msg = "Connection lost before acceptance"
            raise TimeoutError(msg)
        message = command["message"]
        self.thread["messages"].append(
            {
                "id": message["messageId"],
                "role": message["role"],
                "text": message["text"],
                "turnId": "fixture-turn",
            }
        )
        if self.lose_after_accept:
            msg = "Connection lost after acceptance"
            raise TimeoutError(msg)
        return {"accepted": True}


@pytest.fixture
def message_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[argparse.Namespace, dict, MessageServer]:
    """Scope private request files and an existing thread to one fixture."""
    prompt = tmp_path / "message.txt"
    text = "Hand off the shared fixture resource."
    prompt.write_text(text, encoding="utf-8")
    thread = {
        "id": "target",
        "projectId": "project",
        "title": "Fixture target",
        "modelSelection": {
            "instanceId": "codex",
            "model": "fixture-model",
            "options": [{"id": "reasoningEffort", "value": "xhigh"}],
        },
        "runtimeMode": "approval-required",
        "interactionMode": "plan",
        # Identical text from an earlier send must not count as this delivery.
        "messages": [{"id": "earlier", "role": "user", "text": text}],
    }
    snapshot = {
        "projects": [{"id": "project", "workspaceRoot": str(tmp_path)}],
        "threads": [thread],
    }
    args = argparse.Namespace(
        workspace=str(tmp_path),
        thread="target",
        prompt_file=str(prompt),
        base_dir=None,
        dry_run=False,
    )
    monkeypatch.setattr(helper.Path, "home", lambda: tmp_path)
    return args, snapshot, MessageServer(thread)


def test_send_preserves_settings_and_verifies_exact_message(
    message_setup: tuple[argparse.Namespace, dict, MessageServer],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sending to an existing thread preserves settings and confirms persistence."""
    args, snapshot, server = message_setup
    helper.send(args, server, snapshot)
    command = server.commands[0]
    for key in helper.SETTINGS:
        assert command[key] == server.thread[key]
    assert command["message"]["text"] == Path(args.prompt_file).read_text(
        encoding="utf-8"
    )
    assert len(snapshot["threads"]) == 1
    assert len(server.thread["messages"]) == 2
    path = next((tmp_path / ".local/state/t3-start-thread").glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "token" not in record
    assert record["messageId"] == command["message"]["messageId"]
    assert record["messageTurnId"] == "fixture-turn"
    result = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert result["delivered"] is True
    assert result["messageId"] != "earlier"
    assert command["message"]["text"] not in json.dumps(result)


def test_send_dry_run_has_no_submission_record_or_prompt_output(
    message_setup: tuple[argparse.Namespace, dict, MessageServer],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A capability probe validates its target without sending or leaking text."""
    args, snapshot, server = message_setup
    args.dry_run = True
    helper.send(args, server, snapshot)
    output = capsys.readouterr().out
    assert json.loads(output)["dryRun"] is True
    assert json.loads(output)["thread"]["id"] == args.thread
    assert server.commands == []
    assert not (tmp_path / ".local/state/t3-start-thread").exists()
    assert Path(args.prompt_file).read_text(encoding="utf-8") not in output


def test_send_rejects_missing_target(
    message_setup: tuple[argparse.Namespace, dict, MessageServer],
) -> None:
    """A nonexistent thread never becomes a new thread implicitly."""
    args, snapshot, server = message_setup
    args.thread = "missing"
    with pytest.raises(ValueError, match="Target thread must belong"):
        helper.send(args, server, snapshot)
    assert server.commands == []


def test_send_rejects_target_in_another_project(
    message_setup: tuple[argparse.Namespace, dict, MessageServer],
) -> None:
    """A valid ID cannot bypass the workspace restriction."""
    args, snapshot, server = message_setup
    server.thread["projectId"] = "other-project"
    with pytest.raises(ValueError, match="Target thread must belong"):
        helper.send(args, server, snapshot)
    assert server.commands == []


def test_send_rejects_empty_prompt(
    message_setup: tuple[argparse.Namespace, dict, MessageServer],
) -> None:
    """Whitespace never starts an accidental empty user turn."""
    args, snapshot, server = message_setup
    Path(args.prompt_file).write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError, match="Prompt file is empty"):
        helper.send(args, server, snapshot)
    assert server.commands == []


def test_resume_send_after_lost_reply_does_not_duplicate_message(
    message_setup: tuple[argparse.Namespace, dict, MessageServer], tmp_path: Path
) -> None:
    """A lost acknowledgement is recovered by the exact persisted message ID."""
    args, snapshot, server = message_setup
    server.lose_after_accept = True
    with pytest.raises(TimeoutError):
        helper.send(args, server, snapshot)
    path = next((tmp_path / ".local/state/t3-start-thread").glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    helper.submit(server, path, record)
    assert len(server.commands) == 1
    assert len(server.thread["messages"]) == 2
    assert record["accepted"] is True


def test_resume_send_before_acceptance_reuses_command_and_message_ids(
    message_setup: tuple[argparse.Namespace, dict, MessageServer], tmp_path: Path
) -> None:
    """Resuming a failed attempt does not generate a fresh user turn request."""
    args, snapshot, server = message_setup
    server.lose_before_accept = True
    with pytest.raises(TimeoutError):
        helper.send(args, server, snapshot)
    path = next((tmp_path / ".local/state/t3-start-thread").glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    server.lose_before_accept = False
    helper.submit(server, path, record)
    assert len(server.commands) == 2
    assert server.commands[0] == server.commands[1]
    assert len(server.thread["messages"]) == 2


def test_resume_accepted_but_missing_message_does_not_resend(
    message_setup: tuple[argparse.Namespace, dict, MessageServer], tmp_path: Path
) -> None:
    """Removing an acknowledged message does not trigger a replacement turn."""
    args, snapshot, server = message_setup
    helper.send(args, server, snapshot)
    path = next((tmp_path / ".local/state/t3-start-thread").glob("*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    server.thread["messages"].pop()
    with pytest.raises(RuntimeError, match="Accepted message is absent"):
        helper.submit(server, path, record)
    assert len(server.commands) == 1
