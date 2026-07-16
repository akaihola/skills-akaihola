#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Report coding-agent project activity since the previous scan.

Scans Claude Code and Codex session logs, groups the sessions by git
repository, enriches each with commit activity, and lists the tracking
documents already in the vault — so the agent can decide which docs to
create or refresh.

Usage:
    uv run scripts/scan.py                      # since the recorded scan
    uv run scripts/scan.py --since 2026-06-18   # explicit window
    uv run scripts/scan.py --json               # machine-readable
    uv run scripts/scan.py --record             # stamp this scan as done
    uv run scripts/scan.py --show-state         # print the stored timestamp

The timestamp is per-machine: session logs live on the host that ran the
agent, so a scan on one host says nothing about work done on another. State
is stored outside this repo (see --state-file) because it names private
projects.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess  # noqa: S404
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent

DEFAULT_WINDOW_DAYS = 28
MIN_TAIL_LINES = 2
DOC_FIELD_COUNT = 3
CWD_PREAMBLE_LINES = 5
SUBJECT_SAMPLE = 5
STALE_SAMPLE = 10

TS_RE = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"')
CWD_RE = re.compile(rb'"cwd"\s*:\s*"([^"]+)"')
SID_RE = re.compile(rb'"session_?[Ii]d"\s*:\s*"([^"]+)"')

VAULT_LIST_SH = dedent(
    """
    cd "$1"/pages/Projects 2>/dev/null || exit 0
    for f in *.md; do
        [ -e "$f" ] || continue
        s=$(sed -n 's/^status:[[:space:]]*//p' "$f" | head -1)
        u=$(sed -n 's/^last_updated:[[:space:]]*//p' "$f" | head -1)
        printf '%s\\t%s\\t%s\\n' "${f%.md}" "$s" "$u"
    done
    """
)


@dataclass
class Doc:
    """A tracking document already present in the vault."""

    name: str
    status: str
    last_updated: str


@dataclass
class Project:
    """One project's agent activity within the scan window."""

    root: str
    name: str
    harnesses: list[str]
    sessions: int
    last_activity: str | None
    exists: bool
    worktrees: list[str]
    doc: str | None
    commits: int
    last_commit: str | None
    subjects: list[str]


@dataclass
class Report:
    """The full scan result."""

    since: str
    host: str
    generated: str
    projects: list[Project]
    vault_docs: list[Doc]


@dataclass
class Session:
    """One agent session log found in the scan window."""

    ident: str
    cwd: str
    last: datetime
    harness: str = ""


@dataclass
class Activity:
    """Sessions accumulated for one resolved project root."""

    root: str
    harnesses: set[str] = field(default_factory=set)
    idents: set[str] = field(default_factory=set)
    last: datetime | None = None
    worktrees: set[str] = field(default_factory=set)


def _state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / "project-tracking-scan" / "state.json"


def _parse_ts(raw: str) -> datetime | None:
    """Parse an ISO-8601 stamp into an aware UTC datetime, or None."""
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _search(pattern: re.Pattern[bytes], blob: bytes) -> str | None:
    match = pattern.search(blob)
    return match.group(1).decode("utf-8", "replace") if match else None


def _tail_last_timestamp(path: Path) -> tuple[datetime | None, bytes]:
    """Find the newest timestamp in a session log, reading from the end.

    Returns (timestamp, tail_bytes). Growing chunks are read from the end
    until a timestamp is found or the file is exhausted. Scanning the whole
    tail rather than only the final line matters: trailing records such as
    summaries carry no timestamp of their own, and stopping at the last
    line would drop those sessions from the report entirely.
    """
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        if end == 0:
            return None, b""
        size = 0
        chunk = 1 << 16
        while size < end:
            size = min(size + chunk, end)
            fh.seek(end - size)
            tail = fh.read(size)
            stamps = TS_RE.findall(tail)
            if stamps:
                return _parse_ts(stamps[-1].decode("utf-8", "replace")), tail
            chunk *= 8
    return None, b""


def _find_cwd(path: Path, head: bytes, tail: bytes) -> str | None:
    """Locate the session's working directory.

    Claude repeats cwd on most records; Codex states it once in the
    session_meta preamble, so fall back to scanning the first few lines.
    """
    cwd = _search(CWD_RE, head) or _search(CWD_RE, tail)
    if cwd:
        return cwd
    with path.open("rb") as fh:
        for _, line in zip(range(CWD_PREAMBLE_LINES), fh, strict=False):
            cwd = _search(CWD_RE, line)
            if cwd:
                return cwd
    return None


def _file_activity(path: Path, since: datetime) -> Session | None:
    """Return the session's identity and activity if it falls in window."""
    last, tail = _tail_last_timestamp(path)
    if last is None or last < since:
        return None
    with path.open("rb") as fh:
        head = fh.readline()
    cwd = _find_cwd(path, head, tail)
    if not cwd:
        return None
    # Sidechain and subagent logs repeat their parent's session id; keying on
    # it stops one conversation from counting as several.
    ident = _search(SID_RE, head) or _search(SID_RE, tail) or str(path)
    return Session(ident=ident, cwd=cwd, last=last)


def _scan_logs(root: Path, harness: str, since: datetime) -> list[Session]:
    """Return in-window sessions found under a harness log root.

    Every file is read: mtime is not a usable prefilter here. Whole log
    directories routinely carry fresh mtimes (a sync, a copy, or the harness
    rewriting sidecars), which would wave through hundreds of stale files —
    and any prefilter that can be wrong in the other direction would hide
    real work. The in-file timestamps are the only trustworthy source.
    """
    out: list[Session] = []
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*.jsonl")):
        try:
            found = _file_activity(path, since)
        except OSError:
            continue
        if found:
            found.harness = harness
            out.append(found)
    return out


def _git(cwd: str, *args: str) -> str | None:
    try:
        res = subprocess.run(  # noqa: S603
            ["git", "-C", cwd, *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.strip() if res.returncode == 0 else None


def _repo_root(cwd: str) -> tuple[str, bool]:
    """Resolve a working directory to its main repository root.

    Returns (root, is_worktree). Linked worktrees resolve to the main
    checkout so a branched worktree does not masquerade as its own project:
    every worktree of a repo shares one common git dir.
    """
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        root = str(Path(common).parent)
        top = _git(cwd, "rev-parse", "--show-toplevel")
        return root, bool(top) and top != root
    # git cannot answer for a directory that no longer exists — the usual case
    # being a deleted worktree. Walk up to the nearest surviving repo so those
    # sessions land on their parent project instead of masquerading as one
    # ghost project per worktree. If nothing survives (the whole repo is gone,
    # or it was scratch work under /tmp), keep the path and let it show as
    # missing rather than guessing.
    for parent in Path(cwd).parents:
        if not parent.exists():
            continue
        ancestor = _git(str(parent), "rev-parse", "--show-toplevel")
        if ancestor:
            return ancestor, True
        break
    return cwd, False


def _commit_stats(root: str, since: datetime) -> tuple[int, str | None, list[str]]:
    """Return (commit_count, last_commit_date, sample_subjects)."""
    log = _git(root, "log", f"--since={since.isoformat()}", "--format=%cI\t%s")
    if not log:
        return 0, None, []
    rows = [ln.split("\t", 1) for ln in log.splitlines() if "\t" in ln]
    if not rows:
        return 0, None, []
    return len(rows), rows[0][0][:10], [s for _, s in rows[:SUBJECT_SAMPLE]]


def _vault_docs(vault: str) -> list[Doc]:
    """List tracking docs from a local path or [user@]host:path.

    The live vault often lives on another machine, so remote listing is part
    of the deterministic step rather than something the agent improvises.
    """
    host, _, path = vault.rpartition(":")
    remote = bool(host) and not Path(vault).exists()
    cmd = (
        ["ssh", "-o", "BatchMode=yes", host, "sh", "-s", "--", path]
        if remote
        else ["sh", "-s", "--", vault]
    )
    try:
        res = subprocess.run(  # noqa: S603
            cmd,
            input=VAULT_LIST_SH,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    docs: list[Doc] = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == DOC_FIELD_COUNT and parts[0]:
            docs.append(
                Doc(
                    name=parts[0],
                    status=parts[1],
                    last_updated=parts[2].strip("'\""),
                )
            )
    return docs


def _match(root: str, docs: list[Doc]) -> str | None:
    """Best-effort repo-to-doc hint; the agent confirms or overrides it."""
    base = Path(root).name.lower()
    for doc in docs:
        name = doc.name.lower()
        if name == base or base in name.split():
            return doc.name
    return None


def collect(since: datetime, args: argparse.Namespace) -> Report:
    """Scan both harnesses and build the report."""
    raw: list[Session] = []
    raw += _scan_logs(Path(args.claude_dir).expanduser(), "claude", since)
    raw += _scan_logs(Path(args.codex_dir).expanduser(), "codex", since)

    acts: dict[str, Activity] = {}
    for ses in raw:
        root, is_worktree = _repo_root(ses.cwd)
        act = acts.setdefault(root, Activity(root=root))
        act.harnesses.add(ses.harness)
        act.idents.add(ses.ident)
        if is_worktree:
            act.worktrees.add(Path(ses.cwd).name)
        if act.last is None or ses.last > act.last:
            act.last = ses.last

    docs = _vault_docs(args.vault) if args.vault else []
    ordered = sorted(acts.values(), key=lambda a: a.last or since, reverse=True)
    projects: list[Project] = []
    for act in ordered:
        commits, last_commit, subjects = _commit_stats(act.root, since)
        projects.append(
            Project(
                root=act.root,
                name=Path(act.root).name,
                harnesses=sorted(act.harnesses),
                sessions=len(act.idents),
                last_activity=act.last.isoformat() if act.last else None,
                exists=Path(act.root).exists(),
                worktrees=sorted(act.worktrees),
                doc=_match(act.root, docs),
                commits=commits,
                last_commit=last_commit,
                subjects=subjects,
            )
        )
    return Report(
        since=since.isoformat(),
        host=socket.gethostname(),
        generated=datetime.now(UTC).isoformat(),
        projects=projects,
        vault_docs=docs,
    )


def render(report: Report) -> str:
    """Render the report as Markdown for the agent to act on."""
    lines = [
        f"# Project activity since {report.since[:10]}",
        "",
        f"Host: {report.host} · {len(report.projects)} project(s) with sessions.",
        "",
    ]
    if not report.projects:
        lines.append("No agent sessions recorded in this window.")
        return "\n".join(lines)

    lines += [
        "| Project | Harness | Sessions | Last | Commits | Tracking doc |",
        "|---|---|---|---|---|---|",
    ]
    for p in report.projects:
        doc = p.doc or "— none —"
        gone = "" if p.exists else " *(dir gone)*"
        last = (p.last_activity or "")[:10]
        lines.append(
            f"| `{p.name}`{gone} | {','.join(p.harnesses)} | {p.sessions} "
            f"| {last} | {p.commits} | {doc} |"
        )

    lines += ["", "## Detail", ""]
    for p in report.projects:
        lines.append(f"### {p.name} — `{p.root}`")
        if p.worktrees:
            lines.append(f"- worktrees seen: {', '.join(p.worktrees)}")
        if not p.exists:
            lines.append("- **directory no longer exists** — scratch, moved or renamed")
        if p.commits:
            lines.append(f"- {p.commits} commit(s), last {p.last_commit}:")
            lines += [f"  - {s}" for s in p.subjects]
        else:
            lines.append("- no commits in window — sessions may not have landed")
        lines.append("")

    if report.vault_docs:
        stale = sorted(report.vault_docs, key=lambda d: d.last_updated or "")
        lines += ["## Stalest tracking docs", ""]
        lines += [
            f"- {d.name} — {d.status or '?'}, updated {d.last_updated or '?'}"
            for d in stale[:STALE_SAMPLE]
        ]
    return "\n".join(lines)


def _load_state(state_file: Path) -> dict[str, str]:
    if not state_file.exists():
        return {}
    try:
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _resolve_since(
    args: argparse.Namespace, state: dict[str, str], now: datetime
) -> datetime | None:
    default = now - timedelta(days=DEFAULT_WINDOW_DAYS)
    if args.since:
        return _parse_ts(args.since)
    if state.get("last_scan"):
        return _parse_ts(state["last_scan"]) or default
    return default


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Scan agent activity by project.")
    ap.add_argument("--since", help="ISO date/time; overrides recorded state")
    ap.add_argument("--record", action="store_true", help="save this scan's stamp")
    ap.add_argument("--record-time", help="ISO stamp to record instead of now")
    ap.add_argument("--show-state", action="store_true", help="print state, exit")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--vault", default=os.environ.get("VAULT_ROOT", "~/my-knowledge"))
    ap.add_argument("--claude-dir", default="~/.claude/projects")
    ap.add_argument("--codex-dir", default="~/.codex/sessions")
    ap.add_argument("--state-file", default=None)
    return ap


def main() -> int:
    """Run the scan and optionally record its timestamp."""
    args = _build_parser().parse_args()
    state_file = (
        Path(args.state_file).expanduser() if args.state_file else _state_path()
    )
    state = _load_state(state_file)

    if args.show_state:
        print(json.dumps(state, indent=2) if state else "no state recorded")
        return 0

    started = datetime.now(UTC)
    since = _resolve_since(args, state, started)
    if since is None:
        print(f"unparseable --since: {args.since}", file=sys.stderr)
        return 2

    if args.vault.startswith("~"):
        args.vault = str(Path(args.vault).expanduser())

    report = collect(since, args)
    print(json.dumps(asdict(report), indent=2) if args.json else render(report))

    if args.record:
        stamp = args.record_time or started.isoformat()
        if _parse_ts(stamp) is None:
            print(f"unparseable --record-time: {stamp}", file=sys.stderr)
            return 2
        state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_scan": stamp,
            "host": socket.gethostname(),
            "previous_scan": state.get("last_scan"),
        }
        state_file.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nRecorded scan at {stamp} → {state_file}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
