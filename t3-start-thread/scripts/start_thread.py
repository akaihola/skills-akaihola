#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["websocket-client>=1.8,<2"]
# ///
"""Create, message or settle T3 threads through authenticated commands."""

import argparse
import datetime as dt
import json
import operator
import os
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] - fixed CLI invocations use argument lists.
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import websocket

# Thread settings a new thread takes from its parent or a settings file.
SETTINGS = ("modelSelection", "runtimeMode", "interactionMode")


class SendTargetError(ValueError):
    """A safe-to-display refusal to select a follow-up target."""


def paced_thread(tracker: str, issue: int) -> str:
    """Resolve a tracker reference through Hai and the pacer's launch records."""
    tracker_path = Path(tracker).expanduser().resolve()
    snapshot = json.loads(
        subprocess.check_output(  # ruff: ignore[subprocess-without-shell-equals-true]
            [shutil.which("hai-tasks") or "hai-tasks", "read", str(tracker_path)],
            text=True,
        )
    )
    issues = [
        item
        for item in snapshot["workspace"]["issues"]
        if item.get("sourceReference") == f"[{issue}]"
    ]
    if len(issues) != 1:
        msg = "Expected exactly one Hai issue with this number in the tracker"
        raise SendTargetError(msg)
    records = []
    for path in (Path.home() / ".local/state/kandev-pacer/t3").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if (
            Path(record["tracker"]).expanduser().resolve() == tracker_path
            and record["issue"] == issues[0]["id"]
        ):
            records.append(record)
    if not records:
        msg = (
            "No pacer launch record for this tracker issue; "
            "file a follow-up in the same tracker"
        )
        raise SendTargetError(msg)
    if len(records) != 1:
        msg = "Multiple pacer launch records for this issue; inspect before sending"
        raise SendTargetError(msg)
    thread_id = (records[0].get("thread") or {}).get("id")
    if not isinstance(thread_id, str) or not thread_id:
        msg = "Pacer launch record has no thread; file a follow-up in the same tracker"
        raise SendTargetError(msg)
    return thread_id


class Server:
    """Keep a short-lived bearer session in memory for one invocation."""

    def __init__(self, url: str, base_dir: str | None) -> None:
        """Validate the endpoint and capture a bearer session privately."""
        self.url = url.rstrip("/")
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            msg = "Server URL must use HTTP or HTTPS"
            raise ValueError(msg)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            msg = "Do not put credentials or query parameters in the URL"
            raise ValueError(msg)
        token = os.environ.get("T3_THREAD_AUTH_TOKEN")
        if not token:
            if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                msg = "Remote servers require T3_THREAD_AUTH_TOKEN"
                raise ValueError(msg)
            command = [
                shutil.which("t3") or "t3",
                "auth",
                "session",
                "issue",
                "--ttl",
                "5m",
                "--label",
                "T3 thread handoff",
                "--token-only",
            ]
            if base_dir:
                command.extend(["--base-dir", base_dir])
            token = subprocess.check_output(command, text=True).strip()  # ruff: ignore[subprocess-without-shell-equals-true]
        if not token:
            msg = "No bearer session was issued"
            raise ValueError(msg)
        self.token: str = token

    def call(self, method: str, payload: dict, *, stream: bool = False) -> dict:
        """Read one snapshot or a command acknowledgement, without retrying."""
        request = Request(  # ruff: ignore[suspicious-url-open-usage] - endpoint permits only HTTP(S).
            self.url + "/api/auth/websocket-ticket",
            method="POST",
            headers={"Authorization": "Bearer " + self.token},
        )
        with urlopen(request, timeout=15) as response:  # ruff: ignore[suspicious-url-open-usage] - validated HTTP(S) URL.
            ticket = json.load(response)["ticket"]
        ws_url = re.sub(r"^http", "ws", self.url) + "/ws?wsTicket=" + quote(ticket)
        socket = websocket.create_connection(
            ws_url + "&orchestrationProtocol=2", timeout=45
        )
        request_id = str(uuid.uuid4())
        deadline = time.monotonic() + 45
        try:
            socket.send(
                json.dumps(
                    {
                        "_tag": "Request",
                        "id": request_id,
                        "tag": method,
                        "payload": payload,
                        "headers": [],
                    }
                )
            )
            while time.monotonic() < deadline:
                socket.settimeout(max(0.1, deadline - time.monotonic()))
                message = json.loads(socket.recv())
                if message.get("_tag") == "Ping":
                    socket.send(json.dumps({"_tag": "Pong"}))
                    continue
                if str(message.get("requestId")) != request_id:
                    continue
                if stream and message.get("_tag") == "Chunk":
                    for value in message["values"]:
                        if value.get("kind") == "snapshot":
                            return value.get("snapshot", value)
                if message.get("_tag") == "Exit":
                    result = message["exit"]
                    if result.get("_tag") != "Success":
                        raise RuntimeError("T3 rejected the RPC: " + json.dumps(result))
                    if stream:
                        msg = "T3 ended the stream without a snapshot"
                        raise RuntimeError(msg)
                    return result["value"]
            msg = "T3 did not respond before the deadline"
            raise TimeoutError(msg)
        finally:
            socket.close()

    def snapshot(self) -> dict:
        """Read the shell snapshot without printing other projects or messages."""
        return self.call("orchestration.subscribeShell", {}, stream=True)

    def thread_projection(self, thread_id: str) -> dict:
        """Read one thread to verify a submitted message by its identifier."""
        return self.call(
            "orchestration.subscribeThread", {"threadId": thread_id}, stream=True
        )["projection"]


def all_threads(snapshot: dict) -> list[dict]:
    """Include archived threads when reconciling durable request records."""
    return snapshot["threads"] + snapshot.get("archivedThreads", [])


def dispatch(server: Server, command: dict) -> dict:
    """Translate V1-shaped records to V2 at the wire boundary, preserving IDs."""
    settings = {key: command[key] for key in SETTINGS}
    message = {k: v for k, v in command["message"].items() if k != "role"}
    if "bootstrap" not in command:
        return server.call(
            "orchestration.dispatchCommand",
            {
                "type": "message.dispatch",
                "createdBy": "user",
                "creationSource": "mcp",
                "commandId": command["commandId"],
                "threadId": command["threadId"],
                **message,
                "modelSelection": settings["modelSelection"],
                "dispatchMode": {"type": "queue_after_active"},
            },
        )
    bootstrap = command["bootstrap"]
    strategy = {"type": "root"}
    if "prepareWorktree" in bootstrap:
        worktree = bootstrap["prepareWorktree"]
        strategy = {
            "type": "worktree",
            "baseRef": worktree["baseBranch"],
            "branch": worktree["branch"],
            "startFromOrigin": worktree["startFromOrigin"],
        }
    return server.call(
        "orchestration.launchThread",
        {
            "commandId": command["commandId"],
            "threadId": command["threadId"],
            "projectId": bootstrap["createThread"]["projectId"],
            "title": bootstrap["createThread"]["title"],
            **settings,
            "workspaceStrategy": strategy,
            "initialMessage": message,
        },
    )


def thread_summary(thread: dict) -> dict:
    """Select metadata useful for choosing a parent or verifying a handoff."""
    keys = (
        "id",
        "title",
        "modelSelection",
        "runtimeMode",
        "interactionMode",
        "branch",
        "worktreePath",
        "latestTurn",
        "session",
        "settledAt",
        "status",
        "activeRunId",
        "activityRunStatus",
        "pendingRuntimeRequest",
        "pendingBackgroundTasks",
    )
    summary = {key: thread.get(key) for key in keys}
    summary["active"] = bool(
        thread.get("status") in {"preparing", "starting", "running", "waiting"}
        or thread.get("activeRunId")
        or thread.get("activityRunStatus")
        or thread.get("pendingRuntimeRequest")
        or thread.get("pendingBackgroundTasks")
    )
    return summary


def settle(args: argparse.Namespace, server: Server) -> None:
    """Settle safe targets independently, emitting one JSON result per thread."""
    failed = False
    for thread_id in args.thread:
        result = {"threadId": thread_id, "dryRun": args.dry_run}
        try:  # ruff: ignore[too-many-statements-in-try-clause] - each target must fail independently.
            # Refresh before each command; earlier targets may take time to settle.
            snapshot = server.snapshot()
            thread = next(
                (t for t in all_threads(snapshot) if t["id"] == thread_id), None
            )
            reason = None
            if thread is None:
                reason = "thread not found"
            elif thread.get("archivedAt") or any(
                t["id"] == thread_id for t in snapshot.get("archivedThreads", [])
            ):
                reason = "archived"
            elif thread.get("hasPendingUserInput"):
                reason = "waiting for an answer"
            elif thread.get("hasPendingApprovals"):
                reason = "waiting for approval"
            elif thread.get("pendingRuntimeRequest"):
                reason = "waiting for runtime input or approval"
            elif thread_summary(thread)["active"]:
                reason = "active"
            if reason:
                result.update(status="refused", reason=reason)
                failed = True
            elif thread is not None:
                result["status"] = (
                    "already-settled" if thread.get("settledAt") else "settled"
                )
                if not args.dry_run:
                    server.call(
                        "orchestration.dispatchCommand",
                        {
                            "type": "thread.settle",
                            "commandId": str(uuid.uuid4()),
                            "threadId": thread_id,
                        },
                    )
        except RuntimeError as error:
            # RPC rejection text contains the server error, not transport tickets.
            result.update(status="error", error=str(error))
            failed = True
        except (OSError, ValueError, KeyError, websocket.WebSocketException) as error:
            result.update(status="error", error=type(error).__name__)
            failed = True
        print(json.dumps(result), flush=True)
    if failed:
        raise SystemExit(1)


def save_record(path: Path, record: dict, *, create: bool = False) -> None:
    """Write private handoff state; never store tokens or WebSocket tickets."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if create else os.O_TRUNC)
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(record, output, indent=2)
        output.write("\n")


def submission_result(
    server: Server, command: dict
) -> tuple[dict | None, dict | None, dict | None]:
    """Observe the saved message, returning the shell a launch needed to find it."""
    shell = None
    if "bootstrap" in command:
        shell = server.snapshot()
        if not any(t["id"] == command["threadId"] for t in all_threads(shell)):
            return shell, None, None
    projection = server.thread_projection(command["threadId"])
    message = next(
        (
            m
            for m in projection["messages"]
            if m["id"] == command["message"]["messageId"]
        ),
        None,
    )
    return shell, projection, message


def submitted_thread(command: dict, shell: dict, projection: dict) -> dict:
    """Summarize a launch from its shell; shell fields override a send's projection."""
    thread = next((t for t in all_threads(shell) if t["id"] == command["threadId"]), {})
    return thread if "bootstrap" in command else {**projection["thread"], **thread}


def submit(server: Server, path: Path, record: dict) -> None:
    """Reconcile saved IDs before dispatch and persist acknowledgements before reads."""
    command = record["command"]
    launch = "bootstrap" in command
    shell, projection, message = submission_result(server, command)
    if message is None and record.get("accepted"):
        msg = (
            "Accepted thread or initial message is absent; inspect T3 before retrying"
            if launch
            else "Accepted message is absent; inspect T3 before retrying"
        )
        raise RuntimeError(msg)
    if message is None:
        # Reuse the saved command ID if an earlier request lost its reply.
        record["acknowledgement"] = dispatch(server, command)
        record["accepted"] = True
        save_record(path, record)
        # Observe again so the summary reflects state after the dispatch.
        shell, projection, message = submission_result(server, command)
    if projection is None or message is None:
        missing = (
            ("thread" if projection is None else "initial message")
            if launch
            else "message"
        )
        msg = f"Command accepted but {missing} is not yet visible; resume"
        raise RuntimeError(msg)
    record["accepted"] = True
    record["thread"] = thread_summary(
        submitted_thread(command, shell or server.snapshot(), projection)
    )
    output = {"record": str(path), "thread": record["thread"]}
    if not launch:
        record["messageId"] = command["message"]["messageId"]
        record["messageTurnId"] = message.get("runId")
        output = {
            "record": str(path),
            "messageId": record["messageId"],
            "messageTurnId": record["messageTurnId"],
            "delivered": True,
            "thread": record["thread"],
        }
    save_record(path, record)
    print(json.dumps(output, indent=2))


def send(args: argparse.Namespace, server: Server, snapshot: dict) -> None:
    """Preserve an existing thread's settings when requesting another user turn."""
    workspace = str(Path(args.workspace).resolve())
    projects = [p for p in snapshot["projects"] if p["workspaceRoot"] == workspace]
    if len(projects) != 1:
        msg = "Expected one T3 project for this workspace; inspect first"
        raise ValueError(msg)
    thread = next((t for t in snapshot["threads"] if t["id"] == args.thread), None)
    if thread is None or thread.get("archivedAt"):
        msg = "Target thread is gone or archived; file a follow-up in the same tracker"
        raise SendTargetError(msg)
    if thread["projectId"] != projects[0]["id"]:
        msg = "Target thread must belong to the selected project"
        raise ValueError(msg)
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    if not prompt.strip():
        msg = "Prompt file is empty"
        raise ValueError(msg)
    command = {
        "type": "thread.turn.start",
        "commandId": str(uuid.uuid4()),
        "threadId": thread["id"],
        **{key: thread[key] for key in SETTINGS},
        "createdAt": dt.datetime.now(dt.UTC).isoformat(),
        "message": {
            "messageId": str(uuid.uuid4()),
            "role": "user",
            "text": prompt,
            "attachments": [],
        },
    }
    if args.dry_run:
        # Show the target and settings without exposing the private prompt.
        print(
            json.dumps(
                {
                    "dryRun": True,
                    "thread": thread_summary(thread),
                    "messageCharacters": len(prompt),
                },
                indent=2,
            )
        )
        return
    record = {"url": server.url, "baseDir": args.base_dir, "command": command}
    path = Path.home() / ".local/state/t3-start-thread" / f"{command['commandId']}.json"
    save_record(path, record, create=True)
    print(f"Request record: {path}", flush=True)
    submit(server, path, record)


def start(args: argparse.Namespace, server: Server, snapshot: dict) -> None:
    """Build a turn bootstrap from a parent's settings or a settings file."""
    workspace = str(Path(args.workspace).resolve())
    projects = [p for p in snapshot["projects"] if p["workspaceRoot"] == workspace]
    if len(projects) != 1:
        msg = "Expected one T3 project for this workspace; inspect first"
        raise ValueError(msg)
    project = projects[0]
    if args.settings:
        settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
        if sorted(settings) != sorted(SETTINGS):
            msg = "Settings file must hold exactly " + ", ".join(SETTINGS)
            raise ValueError(msg)
    else:
        parent = next(
            (t for t in snapshot["threads"] if t["id"] == args.parent_thread), None
        )
        if parent is None or parent["projectId"] != project["id"]:
            msg = "Parent thread must belong to the selected project"
            raise ValueError(msg)
        settings = {key: parent[key] for key in SETTINGS}
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    if not prompt.strip():
        msg = "Prompt file is empty"
        raise ValueError(msg)
    thread_id = str(uuid.uuid4())
    now = dt.datetime.now(dt.UTC).isoformat()
    bootstrap = {
        "createThread": {
            "projectId": project["id"],
            "title": args.title,
            **settings,
            "branch": None,
            "worktreePath": None,
            "createdAt": now,
        }
    }
    if not args.shared_checkout:
        base_branch = (
            args.base_branch
            or subprocess.check_output(  # ruff: ignore[subprocess-without-shell-equals-true] - shell-free Git query.
                [
                    shutil.which("git") or "git",
                    "-C",
                    workspace,
                    "symbolic-ref",
                    "--short",
                    "HEAD",
                ],
                text=True,
            ).strip()
        )
        slug = re.sub(r"[^a-z0-9]+", "-", args.title.lower()).strip("-")[:40]
        bootstrap["prepareWorktree"] = {
            "projectCwd": workspace,
            "baseBranch": base_branch,
            "branch": args.branch or f"{slug or 'task'}-{thread_id[:8]}",
            "startFromOrigin": False,
            "requireWorktree": True,
        }
    elif args.branch or args.base_branch:
        msg = "Shared checkout does not support branch arguments"
        raise ValueError(msg)
    command = {
        "type": "thread.turn.start",
        "commandId": str(uuid.uuid4()),
        "threadId": thread_id,
        **settings,
        "createdAt": now,
        "message": {
            "messageId": str(uuid.uuid4()),
            "role": "user",
            "text": prompt,
            "attachments": [],
        },
        "bootstrap": bootstrap,
    }
    record = {"url": server.url, "baseDir": args.base_dir, "command": command}
    path = Path.home() / ".local/state/t3-start-thread" / f"{thread_id}.json"
    save_record(path, record, create=True)
    print(f"Request record: {path}", flush=True)
    submit(server, path, record)


def main() -> None:
    """Parse inspect, start, send, settle, and resume operations."""
    os.umask(0o077)
    os.environ["SHELL"] = shutil.which("bash") or "/bin/bash"
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "start", "send", "settle"):
        command = commands.add_parser(action)
        command.add_argument("--url", default="http://127.0.0.1:3773")
        command.add_argument("--base-dir")
        if action == "settle":
            command.add_argument("--thread", action="append", required=True)
            command.add_argument("--dry-run", action="store_true")
        else:
            command.add_argument("--workspace", required=action != "send")
        if action == "send":
            target = command.add_mutually_exclusive_group(required=True)
            target.add_argument("--thread")
            target.add_argument("--tracker", help="Canonical Hai tracker path")
            command.add_argument("--issue", type=int, help="Tracker issue number")
            command.add_argument("--prompt-file", required=True)
            command.add_argument("--dry-run", action="store_true")
        if action == "start":
            origin = command.add_mutually_exclusive_group(required=True)
            origin.add_argument("--parent-thread")
            origin.add_argument("--settings", help="JSON file of thread settings")
            command.add_argument("--title", required=True)
            command.add_argument("--prompt-file", required=True)
            command.add_argument("--base-branch")
            command.add_argument("--branch")
            command.add_argument("--shared-checkout", action="store_true")
    resume = commands.add_parser("resume")
    resume.add_argument("record", type=Path)
    args = parser.parse_args()
    if args.action == "send":
        if args.tracker:
            if args.issue is None or args.issue < 1:
                parser.error("--tracker requires a positive --issue number")
            args.thread = paced_thread(args.tracker, args.issue)
            args.workspace = args.workspace or str(
                Path(args.tracker).expanduser().resolve().parent
            )
        elif args.issue is not None or not args.workspace:
            parser.error("--thread requires --workspace; --issue requires --tracker")
    if args.action == "resume":
        record = json.loads(args.record.read_text(encoding="utf-8"))
        server = Server(record["url"], record.get("baseDir"))
        submit(server, args.record, record)
        return
    server = Server(args.url, args.base_dir)
    if args.action == "settle":
        settle(args, server)
        return
    snapshot = server.snapshot()
    if args.action == "send":
        send(args, server, snapshot)
        return
    if args.action == "start":
        start(args, server, snapshot)
        return
    workspace = str(Path(args.workspace).resolve())
    projects = [p for p in snapshot["projects"] if p["workspaceRoot"] == workspace]
    project_ids = {p["id"] for p in projects}
    threads = sorted(
        (t for t in snapshot["threads"] if t["projectId"] in project_ids),
        key=operator.itemgetter("updatedAt"),
        reverse=True,
    )[:10]
    print(
        json.dumps(
            {
                "projects": [
                    {k: p[k] for k in ("id", "title", "workspaceRoot")}
                    for p in projects
                ],
                "threads": [thread_summary(t) for t in threads],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except SendTargetError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        subprocess.CalledProcessError,
        websocket.WebSocketException,
    ) as error:
        # WebSocket failures can contain the ticket URL; keep credentials private.
        print(
            f"Error: {type(error).__name__}. Inspect the request record and "
            "server state before retrying.",
            file=sys.stderr,
        )
        sys.exit(1)
