#!/usr/bin/env python3
"""Queue candidate learnings as they happen, for /reflect-extensions to drain.

Wired as a `UserPromptSubmit` hook. Every user prompt is matched against cheap
regexes for correction / preference / failure / praise signals. A match appends
one JSONL record to a per-session queue; `/reflect-extensions` reads that queue
in Phase 2a and applies semantic validation before anything is written anywhere.

Why regex here and judgement there (the "hybrid detection" split):
  The hook runs on every prompt and must be fast and free, so it may only cheaply
  *nominate* candidates — it deliberately over-captures. The model drains the
  queue later and throws out the false positives, which is the step that costs
  tokens and therefore must not run per prompt.

Why capture at all, rather than only reading the transcript at reflection time:
  Corrections are lost when a session is compacted, abandoned, or simply never
  reflected on. The queue outlives the context window.

Never blocks, never writes to stdout (UserPromptSubmit stdout is injected into
the model's context), always exits 0.

Config via env vars:
  REFLECT_EXT_CAPTURE      "0" = disable capture entirely (default "1")
  REFLECT_EXT_QUEUE_MAX    Max records kept per session (default 200)
  REFLECT_EXT_EXCERPT_LEN  Max characters of prompt stored per record (default 300)
"""

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

STATE_DIR = Path("~/.claude/reflect-extensions").expanduser()

# (kind, base confidence, pattern). Patterns are matched case-insensitively
# against the raw prompt. English and Finnish, since prompts mix both.
#
# Confidences are deliberately conservative: they gate *which surface* a learning
# may reach (see the command's confidence gate), so an over-eager 0.9 here would
# push unconfirmed noise into always-on context files.
SIGNALS: list[tuple[str, float, str]] = [
    # Explicit "do it this way instead" — the strongest signal there is.
    ("correction", 0.90, r"\bno,?\s+(use|do|run|try|call|read)\b"),
    ("correction", 0.90, r"\b(use|do|run)\b[^.!?\n]{0,60}\binstead of\b"),
    ("correction", 0.90, r"\bdon'?t\s+(use|run|do|call|write|create)\b"),
    ("correction", 0.90, r"\bstop\s+(using|doing|running)\b"),
    ("correction", 0.90, r"\bälä\s+(käytä|aja|tee|kirjoita|luo)\b"),
    ("correction", 0.90, r"\bei\s*,?\s*vaan\b"),
    # Standing rules — high value, but only when repeated (the gate enforces that).
    ("preference", 0.85, r"\bfrom now on\b|\bgoing forward\b|\bin future\b"),
    ("preference", 0.85, r"\b(always|never)\s+(use|run|do|prefer|avoid|ask|check)\b"),
    ("preference", 0.85, r"\b(aina|jatkossa)\b[^.!?\n]{0,40}\b(käytä|aja|tee)\b"),
    ("preference", 0.85, r"\bälä koskaan\b"),
    # Something the agent produced did not work — a trial→error→solution seed.
    ("failure", 0.75, r"\bthat (did\s?n'?t|does\s?n'?t|doesn'?t) work\b"),
    ("failure", 0.75, r"\bstill (broken|failing|fails|not working)\b"),
    ("failure", 0.75, r"\b(that'?s|this is) (wrong|incorrect)\b"),
    ("failure", 0.75, r"\bei (toimi|onnistu)\b|\bedelleen (rikki|väärin)\b"),
    # Weak positive signal: worth keeping the pattern that just worked.
    ("praise", 0.60, r"\b(exactly|perfect|that'?s it|much better)\b"),
    ("praise", 0.60, r"\b(juuri noin|täydellinen|paljon parempi)\b"),
]

# Applied to the excerpt before it is written to disk. The queue is a plain file
# that the model later reads back, so a leaked token would end up in context and
# potentially in a proposed extension file.
SECRET_PATTERNS: list[str] = [
    r"(sk-|ghp_|gho_|github_pat_|xox[baprs]-|AKIA|AIza)[A-Za-z0-9_\-]{8,}",
    (
        r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----\s+"
        r"(?:(?!-----BEGIN |-----END ).)*?\s+-----END \1-----"
    ),
    r"(?i)\b(authorization|bearer)\b\s*:?\s*\S+",
    r"(?i)\b(token|password|passwd|secret|api[_-]?key)\b\s*[:=]\s*\S+",
]


def _read_input() -> dict:
    """Parse the hook payload from stdin, tolerating empty or malformed JSON."""
    raw = sys.stdin.read()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _queue_dir() -> Path:
    """Return the queue directory (derived at call time so tests can patch)."""
    return STATE_DIR / "queue"


def queue_path(session_id: str) -> Path:
    """Return the queue file for one session."""
    return _queue_dir() / f"{session_id}.jsonl"


def redact(text: str) -> str:
    """Replace anything that looks like a credential with a placeholder."""
    for pattern in SECRET_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text)
    return text


def match_signals(prompt: str) -> list[tuple[str, float]]:
    """Return the distinct (kind, confidence) signals present in a prompt."""
    hits: dict[str, float] = {}
    for kind, confidence, pattern in SIGNALS:
        if re.search(pattern, prompt, re.IGNORECASE):
            hits[kind] = max(hits.get(kind, 0.0), confidence)
    return sorted(hits.items(), key=lambda item: -item[1])


def score(hits: list[tuple[str, float]]) -> float:
    """Score a prompt: the strongest signal, nudged up when signals corroborate."""
    if not hits:
        return 0.0
    best = hits[0][1]
    return min(0.95, best + 0.05) if len(hits) > 1 else best


def excerpt(prompt: str, limit: int) -> str:
    """Collapse whitespace, redact secrets, and truncate to `limit` characters."""
    text = redact(" ".join(prompt.split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def queue_depth(session_id: str) -> int:
    """Count queued records for a session. Returns 0 if the queue is unreadable."""
    path = queue_path(session_id)
    try:
        with path.open(encoding="utf-8", errors="ignore") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def append(session_id: str, record: dict, queue_max: int) -> None:
    """Append one record, unless the session queue is already at its cap."""
    if queue_depth(session_id) >= queue_max:
        return
    try:
        _queue_dir().mkdir(parents=True, exist_ok=True)
        with queue_path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # never block a prompt on a state-write failure


def main() -> int:
    """Match the submitted prompt and queue it when it carries a signal."""
    if os.environ.get("REFLECT_EXT_CAPTURE", "1") != "1":
        return 0

    data = _read_input()
    prompt = data.get("prompt", "")
    if not prompt or prompt.lstrip().startswith("/"):
        return 0  # slash-command invocations are not corrections

    hits = match_signals(prompt)
    if not hits:
        return 0

    session_id = data.get("session_id", "unknown")
    excerpt_len = int(os.environ.get("REFLECT_EXT_EXCERPT_LEN", "300"))
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "session_id": session_id,
        "cwd": data.get("cwd", ""),
        "kinds": [kind for kind, _ in hits],
        "confidence": round(score(hits), 2),
        "excerpt": excerpt(prompt, excerpt_len),
    }
    append(session_id, record, int(os.environ.get("REFLECT_EXT_QUEUE_MAX", "200")))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - a hook must never break the session
        print(f"Warning: capture_learning.py error: {exc}", file=sys.stderr)
        sys.exit(0)
