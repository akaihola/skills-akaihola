#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Secrets scanner: runs detect-secrets (uvx) and secretlint (bun).

Scans a git repository for leaked credentials and produces a combined
Markdown report, classifying findings as needing review vs. likely false
positives.

Usage:
    ./scan.py [path]              # scan repo at path (default: current directory)
    ./scan.py --json              # emit raw JSON instead of Markdown
    ./scan.py --no-secretlint     # skip secretlint (faster, but misses token patterns)
    ./scan.py --all-files         # scan all files, not just git-tracked ones

Excluded by default: .venv/ .git/ node_modules/ __pycache__ dist/ build/
.ruff_cache/ .mypy_cache/
"""

from __future__ import annotations

import argparse
import json
import subprocess  # noqa: S404
import sys
import tempfile
from pathlib import Path
from textwrap import dedent

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


def is_placeholder(line: str) -> bool:
    """Return True when line looks like a template or documentation example."""
    lower = line.lower()
    return any(p.lower() in lower for p in PLACEHOLDER_INDICATORS)


# -- detect-secrets ------------------------------------------------------------


def run_detect_secrets(repo_path: Path, *, all_files: bool) -> dict:
    """Run `uvx detect-secrets scan` and return the parsed JSON baseline."""
    cmd = ["uvx", "detect-secrets", "scan"]
    if all_files:
        cmd.append("--all-files")
    for pattern in EXCLUDE_DIR_REGEXES:
        cmd += ["--exclude-files", pattern]

    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        cwd=repo_path,
        check=False,
    )

    if result.returncode not in {0, 1}:
        print(f"[detect-secrets] stderr: {result.stderr.strip()}", file=sys.stderr)
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"[detect-secrets] JSON parse error: {exc}", file=sys.stderr)
        return {}


# -- secretlint ----------------------------------------------------------------


def setup_secretlint(tmpdir: Path) -> Path | None:
    """Install secretlint + recommended preset into a temp dir.

    Returns the path to the secretlint binary, or None on failure.
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
    proc = subprocess.run(bun_cmd, capture_output=True, cwd=tmpdir, check=False)  # noqa: S603
    if proc.returncode != 0:
        print(
            f"[secretlint] bun add failed: {proc.stderr.decode()[:200]}",
            file=sys.stderr,
        )
        return None

    sl_bin = tmpdir / "node_modules" / ".bin" / "secretlint"
    return sl_bin if sl_bin.exists() else None


def get_git_tracked_files(repo_path: Path) -> list[str]:
    """Return git-tracked files relative to repo_path, minus excluded dirs."""
    git_cmd = ["git", "ls-files"]
    result = subprocess.run(  # noqa: S603
        git_cmd,
        capture_output=True,
        text=True,
        cwd=repo_path,
        check=False,
    )
    if result.returncode != 0:
        # Not a git repo - fall back to empty list
        return []
    files = result.stdout.strip().splitlines()
    return [f for f in files if not f.startswith(EXCLUDE_DIR_PREFIXES)]


def run_secretlint(
    repo_path: Path, sl_bin: Path, rc_path: Path, files: list[str]
) -> list[dict]:
    """Run secretlint on the given files and return a list of finding dicts.

    Each dict has: file, line, col, rule_id, message_id, message.
    """
    if not files:
        return []

    # secretlint needs absolute paths when run from a temp dir
    abs_files = [str(repo_path / f) for f in files]

    # Run in batches to avoid ARG_MAX limits on large repos
    batch_size = 200
    all_findings: list[dict] = []

    for i in range(0, len(abs_files), batch_size):
        batch = abs_files[i : i + batch_size]
        result = subprocess.run(  # noqa: S603
            [
                str(sl_bin),
                "--format",
                "json",
                "--secretlintrc",
                str(rc_path),
                *batch,
            ],
            capture_output=True,
            text=True,
            cwd=repo_path,
            check=False,
        )

        raw = result.stdout.strip()
        if not raw:
            continue

        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for item in items:
            fp = item.get("filePath", "")
            rel = fp.replace(str(repo_path) + "/", "")
            for msg in item.get("messages", []):
                loc = msg.get("loc", {}).get("start", {})
                all_findings.append(
                    {
                        "file": rel,
                        "line": loc.get("line", 0),
                        "col": loc.get("column", 0),
                        "rule_id": msg.get("ruleId", ""),
                        "message_id": msg.get("messageId", ""),
                        "message": msg.get("message", ""),
                        "docs_url": msg.get("docsUrl", ""),
                    }
                )

    return all_findings


# -- report assembly -----------------------------------------------------------


def classify(line_content: str) -> str:
    """Return 'likely-false-positive' or 'review-required'."""
    return (
        "likely-false-positive" if is_placeholder(line_content) else "review-required"
    )


def build_combined(
    repo_path: Path,
    ds_data: dict,
    sl_findings: list[dict],
) -> dict:
    """Merge detect-secrets and secretlint findings into a unified structure.

    For each finding, read the flagged line so the agent can classify it.
    """
    findings: list[dict] = []

    # detect-secrets findings
    for filename, secrets in (ds_data.get("results") or {}).items():
        abs_path = repo_path / filename
        for secret in secrets:
            ln = secret.get("line_number", 0)
            line_content = read_line(abs_path, ln)
            findings.append(
                {
                    "source": "detect-secrets",
                    "file": filename,
                    "line": ln,
                    "type": secret.get("type", ""),
                    "is_verified": secret.get("is_verified", False),
                    "line_content": line_content,
                    "classification": classify(line_content),
                }
            )

    # secretlint findings
    for f in sl_findings:
        abs_path = repo_path / f["file"]
        line_content = read_line(abs_path, f["line"])
        findings.append(
            {
                "source": "secretlint",
                "file": f["file"],
                "line": f["line"],
                "type": f["message_id"],
                "rule_id": f["rule_id"],
                "message": f["message"],
                "docs_url": f["docs_url"],
                "line_content": line_content,
                "classification": classify(line_content),
            }
        )

    return {
        "repo": str(repo_path),
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
        },
    }


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
        ]
    )

    if not findings:
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
                    "_These matched secret patterns but appear to be placeholders or "
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
    if "message" in f:
        lines.append(f"- **Message:** {f['message']}")
    if f.get("docs_url"):
        lines.append(f"- **Docs:** {f['docs_url']}")
    if f.get("line_content"):
        # Truncate long lines to avoid echoing full secrets into the report
        content = f["line_content"][:200]
        lines.append(f"- **Line:** `{content}`")
    lines.append("")


# -- main ----------------------------------------------------------------------


def main() -> None:
    """Entry point: parse arguments, run scanners, print report."""
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
        sys.exit(1)

    print(f"[scan] repository: {repo_path}", file=sys.stderr)

    # -- detect-secrets -------------------------------------------------------
    print("[scan] running detect-secrets...", file=sys.stderr)
    ds_data = run_detect_secrets(repo_path, all_files=args.all_files)
    ds_count = len(ds_data.get("results") or {})
    print(f"[scan] detect-secrets: {ds_count} files with findings", file=sys.stderr)

    # -- secretlint -----------------------------------------------------------
    sl_findings: list[dict] = []
    if not args.no_secretlint:
        print("[scan] setting up secretlint (bun add)...", file=sys.stderr)
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            sl_bin = setup_secretlint(tmpdir)
            if sl_bin:
                tracked = get_git_tracked_files(repo_path)
                print(
                    f"[scan] running secretlint on {len(tracked)} git-tracked files...",
                    file=sys.stderr,
                )
                sl_findings = run_secretlint(
                    repo_path, sl_bin, tmpdir / ".secretlintrc.json", tracked
                )
                print(
                    f"[scan] secretlint: {len(sl_findings)} findings",
                    file=sys.stderr,
                )
            else:
                print("[scan] secretlint setup failed, skipping", file=sys.stderr)
    else:
        print("[scan] secretlint skipped (--no-secretlint)", file=sys.stderr)

    # -- combine & output -----------------------------------------------------
    combined = build_combined(repo_path, ds_data, sl_findings)

    if args.json:
        print(json.dumps(combined, indent=2))
    else:
        print(render_markdown(combined))

    # Exit 1 when any finding needs human review
    if combined["summary"]["review_required"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
