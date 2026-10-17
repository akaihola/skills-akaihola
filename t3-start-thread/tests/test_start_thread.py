"""Exercise interrupted handoffs and messaging without live agent sessions."""

import argparse
import importlib.util
import io
import json
import stat
import tempfile
from pathlib import Path
from typing import Protocol
from unittest.mock import patch
from urllib.request import Request

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
    protocol = 1

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
    protocol = 1

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


class FixtureSocket(Protocol):
    """Socket methods used by the helper transport."""

    def send(self, raw: str) -> None:
        """Accept a serialized RPC."""

    def settimeout(self, timeout: float) -> None:
        """Bound a receive."""

    def close(self) -> None:
        """Release the connection."""

    def recv(self) -> str:
        """Return a serialized reply."""


class WireServer:
    """Serve protocol-shaped RPC replies through the real helper transport."""

    def __init__(self, protocol: int, root: Path) -> None:
        """Keep an isolated project, receipt cache, and connection history."""
        self.protocol = protocol
        self.urls = []
        self.requests = []
        self.tickets = 0
        self.lose_reply = False
        self.project = {"id": "project", "title": "Fixture", "workspaceRoot": str(root)}
        self.settings = {
            "modelSelection": {"instanceId": "codex", "model": "fixture-model"},
            "runtimeMode": "approval-required",
            "interactionMode": "plan",
        }
        self.threads = [self.make_thread("parent")]
        self.archived = []
        self.receipts = {}

    def make_thread(self, thread_id: str) -> dict:
        """Keep V1 and V2 activity fields distinct in fixtures."""
        activity = (
            {"session": {"status": "running"}, "latestTurn": {"state": "running"}}
            if self.protocol == 1
            else {
                "status": "running",
                "activeRunId": "run",
                "activityRunStatus": "running",
            }
        )
        return {
            "id": thread_id,
            "projectId": "project",
            "title": "Fixture",
            "updatedAt": "2026-10-17T00:00:00Z",
            **self.settings,
            **activity,
            "messages": [],
        }

    def ticket(self, request: Request, *, timeout: float) -> io.StringIO:
        """Issue a fresh ticket for each connection attempt."""
        assert timeout == 15
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer fixture-token"
        self.tickets += 1
        return io.StringIO(json.dumps({"ticket": f"ticket-{self.tickets}"}))

    def connect(self, url: str, *, timeout: float) -> "FixtureSocket":
        """Reject V1 upgrades exactly as a V2 server does."""
        assert timeout == 45
        self.urls.append(url)
        if self.protocol == 2 and "orchestrationProtocol=2" not in url:
            msg = "Upgrade rejected"
            raise helper.websocket.WebSocketBadStatusException(
                msg,
                status_code=426,
                resp_body='{"error":"orchestration_protocol_incompatible"}',
            )
        backend = self

        class Socket:
            def send(self, raw: str) -> None:
                self.request = json.loads(raw)

            def settimeout(self, timeout: float) -> None:
                pass

            def close(self) -> None:
                pass

            def recv(self) -> str:
                request = self.request
                method, payload = request["tag"], request["payload"]
                backend.requests.append((method, payload))
                if method == "orchestration.subscribeShell":
                    value = {"projects": [backend.project], "threads": backend.threads}
                    if backend.protocol == 2:
                        value["archivedThreads"] = backend.archived
                elif method == "orchestration.subscribeThread":
                    thread = next(
                        t
                        for t in backend.threads + backend.archived
                        if t["id"] == payload["threadId"]
                    )
                    value = (
                        {"thread": thread}
                        if backend.protocol == 1
                        else {
                            "projection": {
                                "thread": {"id": thread["id"]},
                                "messages": thread["messages"],
                            }
                        }
                    )
                else:
                    value = backend.dispatch(method, payload)
                    if backend.lose_reply:
                        backend.lose_reply = False
                        msg = "Lost accepted reply"
                        raise TimeoutError(msg)
                    return json.dumps(
                        {
                            "_tag": "Exit",
                            "requestId": request["id"],
                            "exit": {"_tag": "Success", "value": value},
                        }
                    )
                return json.dumps(
                    {
                        "_tag": "Chunk",
                        "requestId": request["id"],
                        "values": [
                            {"kind": "snapshot", **value}
                            if backend.protocol == 2
                            and method == "orchestration.subscribeThread"
                            else {"kind": "snapshot", "snapshot": value}
                        ],
                    }
                )

        return Socket()

    def dispatch(self, method: str, command: dict) -> dict:
        """Validate the envelope and deduplicate by command ID."""
        if command["commandId"] in self.receipts:
            return self.receipts[command["commandId"]]
        if self.protocol == 1:
            assert method == "orchestration.dispatchCommand"
            assert command["type"] == "thread.turn.start"
            creation = "bootstrap" in command
            message = command["message"]
        else:
            creation = method == "orchestration.launchThread"
            assert "bootstrap" not in command
            if creation:
                assert command["workspaceStrategy"]["type"] in {"root", "worktree"}
                for key in helper.SETTINGS:
                    assert command[key] == self.settings[key]
                message = command["initialMessage"]
            else:
                assert method == "orchestration.dispatchCommand"
                assert command["type"] == "message.dispatch"
                assert command["createdBy"] == "user"
                assert command["creationSource"] == "mcp"
                assert command["dispatchMode"] == {"type": "queue_after_active"}
                assert command["modelSelection"] == self.settings["modelSelection"]
                message = command
        if creation:
            thread = next(
                (t for t in self.threads if t["id"] == command["threadId"]), None
            )
            if thread is None:
                thread = self.make_thread(command["threadId"])
                self.threads.append(thread)
        else:
            thread = next(t for t in self.threads if t["id"] == command["threadId"])
        thread["messages"].append(
            {
                "id": message["messageId"],
                ("turnId" if self.protocol == 1 else "runId"): "turn",
            }
        )
        result = (
            {"threadId": thread["id"], "projection": {}, "resumed": False}
            if self.protocol == 2 and creation
            else {"sequence": 1}
        )
        self.receipts[command["commandId"]] = result
        return result


@pytest.fixture(params=[1, 2])
def wire_server(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> WireServer:
    """Run the CLI against both protocols without real credentials or sessions."""
    server = WireServer(request.param, tmp_path)
    monkeypatch.setenv("T3_THREAD_AUTH_TOKEN", "fixture-token")
    monkeypatch.setattr(helper, "urlopen", server.ticket)
    monkeypatch.setattr(helper.websocket, "create_connection", server.connect)
    monkeypatch.setattr(helper.Path, "home", lambda: tmp_path)
    return server


def invoke(monkeypatch: pytest.MonkeyPatch, *arguments: str | Path) -> None:
    """Exercise the unchanged public CLI."""
    monkeypatch.setattr(helper.sys, "argv", [str(SCRIPT), *map(str, arguments)])
    helper.main()


def test_inspect_protocol_detection(
    wire_server: WireServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inspect prints compatible summaries, detects once, and hides messages."""
    invoke(monkeypatch, "inspect", "--workspace", tmp_path)
    output = json.loads(capsys.readouterr().out)
    assert output["threads"][0]["active"] is True
    assert "messages" not in output["threads"][0]
    assert output["projects"] == [wire_server.project]
    assert len(wire_server.urls) == wire_server.protocol
    assert len(set(wire_server.urls)) == wire_server.tickets


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("parent", [False, True])
def test_start_and_resume_both_protocols(  # ruff: ignore[too-many-arguments] - fixture matrix.
    wire_server: WireServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    shared: bool,
    parent: bool,
) -> None:
    """Both settings sources and workspace strategies survive a lost reply."""
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Perform the fixture task.")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(wire_server.settings))
    arguments = ["--parent-thread", "parent"] if parent else ["--settings", settings]
    arguments += (
        ["--shared-checkout"]
        if shared
        else ["--base-branch", "main", "--branch", "fixture"]
    )
    wire_server.lose_reply = True
    with pytest.raises(TimeoutError):
        invoke(
            monkeypatch,
            "start",
            "--workspace",
            tmp_path,
            "--title",
            "Fixture",
            "--prompt-file",
            prompt,
            *arguments,
        )
    record = next((tmp_path / ".local/state/t3-start-thread").glob("*.json"))
    saved = json.loads(record.read_text())
    assert not saved.get("accepted")
    requests = [
        (m, p)
        for m, p in wire_server.requests
        if m in {"orchestration.launchThread", "orchestration.dispatchCommand"}
    ]
    assert len(requests) == 1
    _method, command = requests[0]
    if wire_server.protocol == 2:
        assert command["workspaceStrategy"] == (
            {"type": "root"}
            if shared
            else {
                "type": "worktree",
                "baseRef": "main",
                "branch": "fixture",
                "startFromOrigin": False,
            }
        )
    invoke(monkeypatch, "resume", record)
    assert len(wire_server.receipts) == 1
    assert len(wire_server.threads) == 2
    assert json.loads(record.read_text())["thread"]["active"] is True
    assert prompt.read_text() not in capsys.readouterr().out


def test_send_and_resume_both_protocols(
    wire_server: WireServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Send verifies the exact message; resume never submits a second turn."""
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Perform the fixture follow-up.")
    args = [
        "send",
        "--workspace",
        tmp_path,
        "--thread",
        "parent",
        "--prompt-file",
        prompt,
    ]
    invoke(monkeypatch, *args, "--dry-run")
    assert json.loads(capsys.readouterr().out)["dryRun"] is True
    assert not wire_server.receipts
    wire_server.lose_reply = True
    with pytest.raises(TimeoutError):
        invoke(monkeypatch, *args)
    record = next((tmp_path / ".local/state/t3-start-thread").glob("*.json"))
    capsys.readouterr()
    invoke(monkeypatch, "resume", record)
    output = json.loads(capsys.readouterr().out)
    assert output["delivered"] is True
    assert output["thread"]["active"] is True
    assert output["messageTurnId"] == "turn"
    assert len(wire_server.receipts) == 1
    assert len(wire_server.threads[0]["messages"]) == 1


@pytest.mark.parametrize(
    ("fields", "active"),
    [
        ({"session": None, "latestTurn": None}, False),
        ({"session": {"status": "ready"}}, False),
        ({"session": {"activeTurnId": "turn"}}, True),
        ({"latestTurn": {"state": "running"}}, True),
        ({"hasPendingApprovals": True}, True),
        ({"hasPendingUserInput": True}, True),
        ({"backgroundLiveness": "monitoring"}, True),
        ({"status": "idle", "activeRunId": None}, False),
        ({"status": "completed", "activeRunId": None}, False),
        ({"status": "queued", "activeRunId": None}, False),
        ({"status": "starting"}, True),
        ({"status": "waiting"}, True),
        ({"status": "completed", "activeRunId": "run"}, True),
        ({"status": "completed", "activityRunStatus": "preparing"}, True),
        ({"status": "completed", "pendingRuntimeRequest": {"id": "request"}}, True),
        ({"status": "completed", "pendingBackgroundTasks": [{"taskId": "task"}]}, True),
    ],
)
def test_activity(fields: dict, *, active: bool) -> None:
    """Parked runs are idle; approvals, runtime requests and background work count."""
    assert helper.thread_summary(fields)["active"] is active


@pytest.mark.parametrize("action", ["start", "send"])
def test_resume_unsubmitted_v1_record_on_either_protocol(
    wire_server: WireServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    """Old records translate without changing any saved identifier or setting."""
    command = {
        "type": "thread.turn.start",
        "commandId": "saved-command",
        "threadId": "new" if action == "start" else "parent",
        **wire_server.settings,
        "createdAt": "2026-10-17T00:00:00Z",
        "message": {
            "messageId": "saved-message",
            "role": "user",
            "text": "Fixture.",
            "attachments": [],
        },
    }
    if action == "start":
        command["bootstrap"] = {
            "createThread": {
                "projectId": "project",
                "title": "Fixture",
                **wire_server.settings,
            }
        }
    record = tmp_path / "old-record.json"
    record.write_text(json.dumps({"url": "http://127.0.0.1:3773", "command": command}))
    invoke(monkeypatch, "resume", record)
    assert json.loads(record.read_text())["command"] == command
    assert list(wire_server.receipts) == ["saved-command"]
    assert wire_server.threads[-1]["messages"][0]["id"] == "saved-message"
    # Force server-side deduplication too, rather than relying on reconciliation.
    server = helper.Server("http://127.0.0.1:3773", None)
    server.snapshot()
    assert helper.dispatch(server, command) == helper.dispatch(server, command)
    assert len(wire_server.threads[-1]["messages"]) == 1
    # No repeated negotiation within one server instance.
    urls = wire_server.urls[-3:]
    assert all(
        ("orchestrationProtocol=2" in u) == (wire_server.protocol == 2) for u in urls
    )


@pytest.mark.parametrize("wire_server", [2], indirect=True)
def test_resume_partial_v2_launch(
    wire_server: WireServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thread creation alone does not prove that the initial message persisted."""
    command = {
        "type": "thread.turn.start",
        "commandId": "partial-command",
        "threadId": "partial",
        **wire_server.settings,
        "message": {
            "messageId": "initial",
            "role": "user",
            "text": "Fixture.",
            "attachments": [],
        },
        "bootstrap": {"createThread": {"projectId": "project", "title": "Fixture"}},
    }
    wire_server.threads.append(wire_server.make_thread("partial"))
    record = tmp_path / "partial.json"
    record.write_text(json.dumps({"url": "http://127.0.0.1:3773", "command": command}))
    invoke(monkeypatch, "resume", record)
    assert len(wire_server.threads) == 2
    assert wire_server.threads[-1]["messages"] == [{"id": "initial", "runId": "turn"}]
    assert json.loads(record.read_text())["accepted"] is True


@pytest.mark.parametrize("status", [401, 403, 426, 500])
def test_unrelated_handshake_errors_never_trigger_fallback(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """Authentication and generic upgrade failures are not protocol detection."""
    monkeypatch.setenv("T3_THREAD_AUTH_TOKEN", "fixture-token")
    backend = WireServer(1, Path("/fixture"))
    monkeypatch.setattr(helper, "urlopen", backend.ticket)
    error = helper.websocket.WebSocketBadStatusException(
        "Fixture failure", status_code=status, resp_body="unrelated failure"
    )
    with patch.object(
        helper.websocket, "create_connection", side_effect=error
    ) as connect:
        server = helper.Server("http://127.0.0.1:3773", None)
        with pytest.raises(helper.websocket.WebSocketBadStatusException):
            server.snapshot()
    assert connect.call_count == 1
    assert server.protocol is None


@pytest.mark.parametrize("action", ["start", "send"])
def test_accepted_missing_result_is_not_resent(
    wire_server: WireServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    """An acknowledged but absent result requires inspection on either protocol."""
    command = {"threadId": "parent", "message": {"messageId": "missing"}}
    if action == "start":
        command["bootstrap"] = {}
        if wire_server.protocol == 1:
            wire_server.threads.clear()
    record = tmp_path / "accepted.json"
    record.write_text(
        json.dumps(
            {"url": "http://127.0.0.1:3773", "command": command, "accepted": True}
        )
    )
    with pytest.raises(RuntimeError, match="inspect T3 before retrying"):
        invoke(monkeypatch, "resume", record)
    assert not wire_server.receipts


@pytest.mark.parametrize("wire_server", [2], indirect=True)
def test_archived_launch_stays_resumable(
    wire_server: WireServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Archived V2 threads reconcile without a replacement launch."""
    thread = wire_server.threads.pop()
    thread.update(
        {"status": "completed", "activeRunId": None, "activityRunStatus": None}
    )
    thread["messages"] = [{"id": "initial", "runId": "run"}]
    wire_server.archived.append(thread)
    command = {
        "threadId": "parent",
        "message": {"messageId": "initial"},
        "bootstrap": {},
    }
    record = tmp_path / "archived.json"
    record.write_text(
        json.dumps(
            {"url": "http://127.0.0.1:3773", "command": command, "accepted": True}
        )
    )
    invoke(monkeypatch, "resume", record)
    assert json.loads(capsys.readouterr().out)["thread"]["active"] is False
    assert not wire_server.receipts
    invoke(monkeypatch, "inspect", "--workspace", tmp_path)
    assert json.loads(capsys.readouterr().out)["threads"] == []
