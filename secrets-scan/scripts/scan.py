#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Secrets scanner: runs detect-secrets (uvx) and secretlint (bun).

Scans a git repository for leaked credentials and produces a combined
Markdown report, classifying findings as needing review vs. likely false
positives, and recording whether each scanner ran, was skipped or failed.

Usage:
    ./scan.py [path]              # scan repo at path (default: current directory)
    ./scan.py --json              # emit raw JSON instead of Markdown
    ./scan.py --no-secretlint     # skip secretlint (faster, but misses token patterns)
    ./scan.py --all-files         # scan all files, not just git-tracked ones

Exit status: 0 when every requested scanner finished and nothing needs review,
1 when every requested scanner finished and a finding needs review, 2 when a
requested scanner failed or the arguments are invalid.

Excluded by default: .venv/ .git/ node_modules/ __pycache__ dist/ build/
.ruff_cache/ .mypy_cache/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
from pathlib import Path
from textwrap import dedent
from typing import TypeVar

# -- configuration -------------------------------------------------------------

EXCLUDE_DIR_REGEXES = [
    r"\.venv/",
    r"\.git/",
    r"node_modules/",
    r"__pycache__/",
    r"\.ruff_cache/",
    r"\.mypy_cache/",
    r"dist/",
    r"build/",
    r"\.eggs/",
    r"\.tox/",
    r"\.hg/",
    r"\.svn/",
    r"\.DS_Store",
]

EXCLUDE_DIR_PREFIXES = (
    ".venv/",
    ".git/",
    "node_modules/",
    "__pycache__/",
    ".ruff_cache/",
    ".mypy_cache/",
    "dist/",
    "build/",
)

SECRETLINT_CONFIG = {"rules": [{"id": "@secretlint/secretlint-rule-preset-recommend"}]}

# Paths per secretlint invocation, to stay below ARG_MAX on large repos
SECRETLINT_BATCH_SIZE = 200

# Longest line searched for the value behind a detect-secrets hash
MAX_HASH_SEARCH_LINE = 1000

# Strings that strongly indicate a placeholder / documentation example
PLACEHOLDER_INDICATORS = [
    "your_key_here",
    "your-key-here",
    "your_actual_key",
    "your-api-key",
    "your-token",
    "your_token",
    "your-secret",
    "your_secret",
    "changeme",
    "placeholder",
    "example.com",
    "your-slack-bot-token-here",
    "username:password@",  # generic connection string template
    "AKIAIOSFODNN7EXAMPLE",  # canonical AWS docs example key
    "wJalrXUtnFEMI/K7MDENG",  # canonical AWS docs secret key
    "<your",
    "[your",
    "INSERT_",
    "TODO:",
    "FIXME:",
]

EXIT_CLEAN = 0
EXIT_REVIEW = 1
EXIT_INCOMPLETE = 2

RAN = {"status": "ran"}


class ScannerError(Exception):
    """A requested scanner did not finish; the message is a redacted reason."""


def failed(reason: str) -> dict:
    """Return the outcome of a requested scanner that did not finish."""
    return {"status": "failed", "reason": reason}


JSON_TYPES: dict[type, str] = {
    dict: "object",
    list: "list",
    str: "string",
    int: "integer",
}
T = TypeVar("T")


# Type parameter syntax needs Python 3.12; this script supports 3.10
def expect(value: object, kind: type[T], what: str) -> T:  # ruff: ignore[non-pep695-generic-function]
    """Return value if it has the JSON type kind; else raise a ScannerError.

    The reason names what was malformed, never the value.
    """
    if not isinstance(value, kind):
        msg = f"{what} was not a JSON {JSON_TYPES[kind]}"
        raise ScannerError(msg)
    return value


# -- helpers -------------------------------------------------------------------


def read_line(filepath: Path, line_number: int) -> str:
    """Return the content of a specific line, empty string on any error."""
    try:
        with filepath.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                if i == line_number:
                    return line.rstrip()
    except OSError:
        pass
    return ""


def is_placeholder(value: str) -> bool:
    """Return True when a detected value looks like a template or example."""
    lower = value.lower()
    return any(p.lower() in lower for p in PLACEHOLDER_INDICATORS)


def detect_secrets_value(line: str, hashed_secret: str) -> str | None:
    """Return the part of line whose SHA-1 is detect-secrets' hashed_secret.

    Candidates start and end at the line ends or beside a non-alphanumeric
    character. Return None when nothing matches or the line is too long.
    """
    if not hashed_secret or len(line) > MAX_HASH_SEARCH_LINE:
        return None
    bounds = sorted(
        {0, len(line)}
        | {k for i, ch in enumerate(line) if not ch.isalnum() for k in (i, i + 1)}
    )
    for n, start in enumerate(bounds):
        for end in bounds[n + 1 :]:
            value = line[start:end]
            digest = hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest()
            if digest == hashed_secret:
                return value
    return None


def secretlint_value(line: str, finding: dict) -> str | None:
    """Return the span secretlint flagged on line (0-based columns)."""
    end = finding["end_col"] if finding["end_line"] == finding["line"] else len(line)
    return line[finding["col"] : end] or None


def run_tool(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a scanner command; raise ScannerError when it cannot start."""
    try:
        return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            cmd, capture_output=True, text=True, cwd=cwd, check=False
        )
    except OSError as exc:
        msg = f"could not start {Path(cmd[0]).name}"
        raise ScannerError(msg) from exc


# -- detect-secrets ------------------------------------------------------------


def run_detect_secrets(repo_path: Path, *, all_files: bool) -> dict:
    """Run `uvx detect-secrets scan` and return the parsed JSON baseline."""
    cmd = ["uvx", "detect-secrets", "scan", "--no-verify"]
    if all_files:
        cmd.append("--all-files")
    for pattern in EXCLUDE_DIR_REGEXES:
        cmd += ["--exclude-files", pattern]

    result = run_tool(cmd, repo_path)
    if result.returncode not in {0, 1}:
        msg = f"exit status {result.returncode}"
        raise ScannerError(msg)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        msg = "output was not valid JSON"
        raise ScannerError(msg) from exc
    if not isinstance(data, dict) or not isinstance(data.get("results"), dict):
        msg = "output had no results object"
        raise ScannerError(msg)
    for secrets in data["results"].values():
        for secret in expect(secrets, list, "a results entry"):
            expect(secret, dict, "a finding")
    return data


# -- secretlint ----------------------------------------------------------------


def setup_secretlint(tmpdir: Path) -> Path:
    """Install secretlint + recommended preset into a temp dir.

    Returns the path to the secretlint binary.
    """
    (tmpdir / "package.json").write_text(
        '{"name":"sl-check","version":"1.0.0","private":true}'
    )
    (tmpdir / ".secretlintrc.json").write_text(json.dumps(SECRETLINT_CONFIG, indent=2))

    bun_cmd = [
        "bun",
        "add",
        "--silent",
        "secretlint",
        "@secretlint/secretlint-rule-preset-recommend",
    ]
    proc = run_tool(bun_cmd, tmpdir)
    if proc.returncode != 0:
        msg = f"bun add failed (exit {proc.returncode})"
        raise ScannerError(msg)

    sl_bin = tmpdir / "node_modules" / ".bin" / "secretlint"
    if not sl_bin.exists():
        msg = "bun add did not install the secretlint binary"
        raise ScannerError(msg)
    return sl_bin


def get_git_tracked_files(repo_path: Path) -> list[str]:
    """Return git-tracked files relative to repo_path, minus excluded dirs."""
    result = run_tool(["git", "ls-files"], repo_path)
    if result.returncode != 0:
        msg = f"git ls-files failed (exit {result.returncode})"
        raise ScannerError(msg)
    files = result.stdout.strip().splitlines()
    return [f for f in files if not f.startswith(EXCLUDE_DIR_PREFIXES)]


def parse_secretlint_batch(
    result: subprocess.CompletedProcess[str], repo_path: Path
) -> list[dict]:
    """Return the findings of one secretlint run; raise if it failed.

    secretlint exits 0 when clean (its output may be empty) and 1 with
    findings; any other result, or JSON of an unexpected shape, means the
    batch was not scanned. Each dict has: file, line, col, end_line, end_col,
    rule_id, message_id, message, docs_url.
    """
    if result.returncode not in {0, 1}:
        msg = f"exit status {result.returncode}"
        raise ScannerError(msg)
    raw = result.stdout.strip()
    if not raw:
        if result.returncode == 0:
            return []
        msg = "exit status 1 without JSON output"
        raise ScannerError(msg)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = "output was not valid JSON"
        raise ScannerError(msg) from exc
    findings: list[dict] = []
    for item in expect(items, list, "output"):
        expect(item, dict, "a result item")
        fp = expect(item.get("filePath", ""), str, "filePath")
        for msg in expect(item.get("messages", []), list, "messages"):
            expect(msg, dict, "a message")
            loc = expect(msg.get("loc", {}), dict, "loc")
            start = expect(loc.get("start", {}), dict, "loc.start")
            end = expect(loc.get("end", {}), dict, "loc.end")
            line, col, end_line, end_col = (
                expect(pos.get(key, 0), int, "a position")
                for pos in (start, end)
                for key in ("line", "column")
            )
            findings.append(
                {
                    "file": fp.replace(str(repo_path) + "/", ""),
                    "line": line,
                    "col": col,
                    "end_line": end_line,
                    "end_col": end_col,
                    "rule_id": msg.get("ruleId", ""),
                    "message_id": msg.get("messageId", ""),
                    "message": msg.get("message", ""),
                    "docs_url": msg.get("docsUrl", ""),
                }
            )
    return findings


def run_secretlint(
    repo_path: Path, sl_bin: Path, rc_path: Path, files: list[str]
) -> tuple[list[dict], str | None]:
    """Run secretlint on the given files in batches.

    Return the findings of parse_secretlint_batch() and a failure reason, or
    None when every batch was scanned.
    """
    # secretlint needs absolute paths when run from a temp dir
    abs_files = [str(repo_path / f) for f in files]
    batches = [
        abs_files[i : i + SECRETLINT_BATCH_SIZE]
        for i in range(0, len(abs_files), SECRETLINT_BATCH_SIZE)
    ]
    all_findings: list[dict] = []
    failures: list[str] = []

    for batch in batches:
        cmd = [str(sl_bin), "--format", "json", "--secretlintrc", str(rc_path), *batch]
        try:
            all_findings += parse_secretlint_batch(run_tool(cmd, repo_path), repo_path)
        except ScannerError as exc:
            failures.append(str(exc))

    if failures:
        return all_findings, (
            f"{len(failures)} of {len(batches)} batches not scanned "
            f"(first: {failures[0]})"
        )
    return all_findings, None


def scan_with_secretlint(repo_path: Path) -> tuple[list[dict], dict]:
    """Install and run secretlint; return its findings and outcome."""
    print("[scan] setting up secretlint (bun add)...", file=sys.stderr)
    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        try:
            sl_bin = setup_secretlint(tmpdir)
            tracked = get_git_tracked_files(repo_path)
        except ScannerError as exc:
            return [], failed(str(exc))
        print(
            f"[scan] running secretlint on {len(tracked)} git-tracked files...",
            file=sys.stderr,
        )
        findings, failure = run_secretlint(
            repo_path, sl_bin, tmpdir / ".secretlintrc.json", tracked
        )
    print(f"[scan] secretlint: {len(findings)} findings", file=sys.stderr)
    return findings, failed(failure) if failure else RAN


# -- report assembly -----------------------------------------------------------


def classify(value: str | None) -> str:
    """Return 'likely-false-positive' or 'review-required' for a detected value."""
    if value and is_placeholder(value):
        return "likely-false-positive"
    return "review-required"


def build_combined(
    repo_path: Path,
    ds_data: dict,
    sl_findings: list[dict],
    scanners: dict[str, dict],
) -> dict:
    """Merge detect-secrets and secretlint findings into a unified structure.

    Read flagged lines internally for classification; never return their values.
    """
    findings: list[dict] = []

    # detect-secrets findings
    for filename, secrets in (ds_data.get("results") or {}).items():
        abs_path = repo_path / filename
        for secret in secrets:
            ln = secret.get("line_number", 0)
            value = detect_secrets_value(
                read_line(abs_path, ln), secret.get("hashed_secret", "")
            )
            findings.append(
                {
                    "source": "detect-secrets",
                    "file": filename,
                    "line": ln,
                    "type": secret.get("type", ""),
                    "is_verified": secret.get("is_verified", False),
                    "classification": classify(value),
                }
            )

    # secretlint findings
    for f in sl_findings:
        abs_path = repo_path / f["file"]
        value = secretlint_value(read_line(abs_path, f["line"]), f)
        findings.append(
            {
                "source": "secretlint",
                "file": f["file"],
                "line": f["line"],
                "type": f["message_id"],
                "rule_id": f["rule_id"],
                "classification": classify(value),
            }
        )

    return {
        "repo": str(repo_path),
        "scanners": scanners,
        "findings": findings,
        "summary": {
            "total": len(findings),
            "review_required": sum(
                1 for f in findings if f["classification"] == "review-required"
            ),
            "likely_false_positive": sum(
                1 for f in findings if f["classification"] == "likely-false-positive"
            ),
            "detect_secrets_count": sum(
                1 for f in findings if f["source"] == "detect-secrets"
            ),
            "secretlint_count": sum(1 for f in findings if f["source"] == "secretlint"),
            "failed_scanners": [
                name for name, o in scanners.items() if o["status"] == "failed"
            ],
        },
    }


def exit_status(combined: dict) -> int:
    """Return 2 for a failed scanner, else 1 when a finding needs review, else 0."""
    summary = combined["summary"]
    if summary["failed_scanners"]:
        return EXIT_INCOMPLETE
    return EXIT_REVIEW if summary["review_required"] else EXIT_CLEAN


def render_markdown(combined: dict) -> str:
    """Format the combined findings as a Markdown report."""
    findings = combined["findings"]
    summary = combined["summary"]
    lines: list[str] = []

    lines.extend(
        [
            "# Secrets Scan Report\n",
            f"**Repository:** `{combined['repo']}`\n",
            (
                f"**Total findings:** {summary['total']}  "
                f"({summary['review_required']} need review, "
                f"{summary['likely_false_positive']} likely false positives)\n"
            ),
            "**Scanners:**\n",
        ]
    )
    labels = {"ran": "ran", "skipped": "skipped on request", "failed": "**failed**"}
    for name, outcome in combined["scanners"].items():
        reason = f" — {outcome['reason']}" if "reason" in outcome else ""
        lines.append(f"- `{name}`: {labels[outcome['status']]}{reason}")
    lines.append("")

    if summary["failed_scanners"]:
        names = ", ".join(f"`{n}`" for n in summary["failed_scanners"])
        lines.append(
            f"\n❌ **Scan incomplete:** {names} did not finish, "
            "so findings may be missing.\n"
        )

    if not findings:
        if not summary["failed_scanners"]:
            lines.append("\n✅ **No secrets detected.**")
        return "\n".join(lines)

    # Group by classification
    needs_review = [f for f in findings if f["classification"] == "review-required"]
    false_positives = [
        f for f in findings if f["classification"] == "likely-false-positive"
    ]

    if needs_review:
        lines.extend(
            [
                "\n---\n",
                f"## ⚠️ Needs Review ({len(needs_review)} findings)\n",
            ]
        )
        for f in needs_review:
            _append_finding(lines, f)

    if false_positives:
        lines.extend(
            [
                "\n---\n",
                f"## ✅ Likely False Positives ({len(false_positives)} findings)\n",
                (
                    "_The detected values look like placeholders or "
                    "documentation examples. Verify manually._\n"
                ),
            ]
        )
        for f in false_positives:
            _append_finding(lines, f)

    lines.append(
        "\n---\n"
        "_Generated by `secrets-scan` skill using "
        "`detect-secrets` (uvx) + `secretlint` (bun)_"
    )
    return "\n".join(lines)


def _append_finding(lines: list[str], f: dict) -> None:
    source_badge = f"`[{f['source']}]`"
    lines.extend(
        [
            f"### `{f['file']}` line {f['line']}\n",
            f"- **Type:** {f['type']}  {source_badge}",
        ]
    )
    if "rule_id" in f:
        lines.append(f"- **Rule:** {f['rule_id']}")
    lines.append("")


# -- main ----------------------------------------------------------------------


def main() -> int:
    """Entry point: parse arguments, run scanners, print report, return status."""
    parser = argparse.ArgumentParser(
        description="Scan a git repository for leaked credentials.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            Examples:
              ./scan.py                   # scan current directory
              ./scan.py /path/to/repo     # scan another repo
              ./scan.py --json            # JSON output for programmatic use
              ./scan.py --no-secretlint   # detect-secrets only (faster)
              ./scan.py --all-files       # include non-git-tracked files

            Exit status:
              0  every requested scanner finished; nothing needs review
              1  every requested scanner finished; a finding needs review
              2  a requested scanner failed, or the arguments are invalid
        """),
    )
    parser.add_argument(
        "path", nargs="?", default=".", help="Repository path (default: .)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output raw JSON instead of Markdown"
    )
    parser.add_argument("--no-secretlint", action="store_true", help="Skip secretlint")
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Pass --all-files to detect-secrets (scan non-git-tracked files too)",
    )
    args = parser.parse_args()

    repo_path = Path(args.path).resolve()
    if not repo_path.is_dir():
        print(f"error: {repo_path} is not a directory", file=sys.stderr)
        return EXIT_INCOMPLETE

    print(f"[scan] repository: {repo_path}", file=sys.stderr)
    scanners: dict[str, dict] = {}

    # -- detect-secrets -------------------------------------------------------
    print("[scan] running detect-secrets...", file=sys.stderr)
    try:
        ds_data = run_detect_secrets(repo_path, all_files=args.all_files)
        scanners["detect-secrets"] = RAN
    except ScannerError as exc:
        ds_data = {}
        scanners["detect-secrets"] = failed(str(exc))
    ds_count = len(ds_data.get("results") or {})
    print(f"[scan] detect-secrets: {ds_count} files with findings", file=sys.stderr)

    # -- secretlint -----------------------------------------------------------
    sl_findings: list[dict] = []
    if args.no_secretlint:
        scanners["secretlint"] = {"status": "skipped", "reason": "--no-secretlint"}
    else:
        sl_findings, scanners["secretlint"] = scan_with_secretlint(repo_path)

    for name, outcome in scanners.items():
        if outcome["status"] != "ran":
            print(
                f"[scan] {name} {outcome['status']}: {outcome['reason']}",
                file=sys.stderr,
            )

    # -- combine & output -----------------------------------------------------
    combined = build_combined(repo_path, ds_data, sl_findings, scanners)

    if args.json:
        print(json.dumps(combined, indent=2))
    else:
        print(render_markdown(combined))

    return exit_status(combined)


if __name__ == "__main__":
    sys.exit(main())
