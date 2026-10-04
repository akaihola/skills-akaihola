#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["websocket-client>=1.8,<2"]
# ///
"""Create and verify T3 threads using authenticated orchestration commands."""

import argparse
import datetime
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
        socket = websocket.create_connection(ws_url, timeout=45)
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
                            return value["snapshot"]
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
    )
    return {key: thread.get(key) for key in keys}


def save_record(path: Path, record: dict, *, create: bool = False) -> None:
    """Write private handoff state; never store tokens or WebSocket tickets."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if create else os.O_TRUNC)
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(record, output, indent=2)
        output.write("\n")


def submit(server: Server, path: Path, record: dict) -> None:
    """Check for the saved thread first, then submit the unchanged command."""
    thread_id = record["command"]["threadId"]
    snapshot = server.snapshot()
    thread = next((t for t in snapshot["threads"] if t["id"] == thread_id), None)
    if thread is None and record.get("accepted"):
        msg = "Accepted thread is absent; inspect T3 before retrying"
        raise RuntimeError(msg)
    if thread is None:
        record["acknowledgement"] = server.call(
            "orchestration.dispatchCommand",
            record["command"],
        )
        record["accepted"] = True
        save_record(path, record)
        snapshot = server.snapshot()
        thread = next((t for t in snapshot["threads"] if t["id"] == thread_id), None)
    if thread is None:
        msg = "Command accepted but thread is not yet visible; resume"
        raise RuntimeError(msg)
    record["thread"] = thread_summary(thread)
    save_record(path, record)
    print(json.dumps({"record": str(path), "thread": record["thread"]}, indent=2))


def start(args: argparse.Namespace, server: Server, snapshot: dict) -> None:
    """Build a turn bootstrap that inherits the chosen parent's settings."""
    workspace = str(Path(args.workspace).resolve())
    projects = [p for p in snapshot["projects"] if p["workspaceRoot"] == workspace]
    if len(projects) != 1:
        msg = "Expected one T3 project for this workspace; inspect first"
        raise ValueError(msg)
    project = projects[0]
    parent = next(
        (t for t in snapshot["threads"] if t["id"] == args.parent_thread), None
    )
    if parent is None or parent["projectId"] != project["id"]:
        msg = "Parent thread must belong to the selected project"
        raise ValueError(msg)
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    if not prompt.strip():
        msg = "Prompt file is empty"
        raise ValueError(msg)
    thread_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.UTC).isoformat()
    settings = {
        key: parent[key]
        for key in (
            "modelSelection",
            "runtimeMode",
            "interactionMode",
        )
    }
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
    """Parse inspect, start, and resume operations."""
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "start"):
        command = commands.add_parser(action)
        command.add_argument("--url", default="http://127.0.0.1:3773")
        command.add_argument("--base-dir")
        command.add_argument("--workspace", required=True)
        if action == "start":
            command.add_argument("--parent-thread", required=True)
            command.add_argument("--title", required=True)
            command.add_argument("--prompt-file", required=True)
            command.add_argument("--base-branch")
            command.add_argument("--branch")
            command.add_argument("--shared-checkout", action="store_true")
    resume = commands.add_parser("resume")
    resume.add_argument("record", type=Path)
    args = parser.parse_args()
    if args.action == "resume":
        record = json.loads(args.record.read_text(encoding="utf-8"))
        server = Server(record["url"], record.get("baseDir"))
        submit(server, args.record, record)
        return
    server = Server(args.url, args.base_dir)
    snapshot = server.snapshot()
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
