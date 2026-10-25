"""Offline secrets-scan runs with fake uvx, bun, git and secretlint executables."""

import copy
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "secrets_scan", ROOT / "secrets-scan/scripts/scan.py"
)
assert spec
assert spec.loader
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

# GitHub token shape (ghp_ + 36 characters), never a real credential
TOKEN = "ghp_" + "Fake0Synthetic9" * 2 + "Value1"

CLEAN_UVX = """echo '{"results": {}}'"""
CLEAN_BUN = """\
[[ $1 == add ]] || exit 99
mkdir -p node_modules/.bin && cp "$FAKE_SECRETLINT" node_modules/.bin/secretlint
"""
CLEAN_SECRETLINT = "echo '[]'"
FORMATS = pytest.mark.parametrize("fmt", [[], ["--json"]], ids=["markdown", "json"])


def write_script(path: Path, body: str) -> None:
    """Write an executable bash script."""
    path.write_text(f"#!{shutil.which('bash')}\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


class Harness:
    """A repository plus fake scanners placed first on PATH."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Create the repository and the fake bin directory."""
        self.tmp = tmp_path
        self.monkeypatch = monkeypatch
        self.capsys = capsys
        self.repo = (tmp_path / "repo").resolve()
        self.repo.mkdir()
        for name in ["a.txt", "b.txt"]:
            (self.repo / name).write_text("nothing to see\n", encoding="utf-8")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        # Every repository file counts as tracked
        write_script(self.bin / "git", "[[ $1 == ls-files ]] || exit 99; ls")
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_SECRETLINT", str(tmp_path / "secretlint"))
        # One file per secretlint batch, so two files make two batches
        monkeypatch.setattr(scan, "SECRETLINT_BATCH_SIZE", 1)

    def cat(self, name: str, data: object) -> str:
        """Store data as JSON and return a script body that prints it."""
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return f"cat {shlex.quote(str(path))}"

    def install(
        self,
        uvx: str = CLEAN_UVX,
        bun: str = CLEAN_BUN,
        secretlint: str = CLEAN_SECRETLINT,
    ) -> None:
        """Write the fake uvx, bun and secretlint scripts."""
        write_script(self.bin / "uvx", uvx)
        write_script(self.bin / "bun", bun)
        write_script(self.tmp / "secretlint", secretlint)

    def run(self, *args: str) -> tuple[int, str]:
        """Run scan.main() on the repository; return exit status and stdout."""
        self.monkeypatch.setattr(sys, "argv", ["scan.py", str(self.repo), *args])
        status = scan.main()
        captured = self.capsys.readouterr()
        assert TOKEN not in captured.out + captured.err, "Secret appeared in output"
        return status, captured.out


@pytest.fixture
def harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Harness:
    """Return a fresh repository with fake scanners."""
    return Harness(tmp_path, monkeypatch, capsys)


@FORMATS
def test_clean_complete_run_exits_0(harness: Harness, fmt: list[str]) -> None:
    """Both scanners finish with nothing to report."""
    harness.install()
    status, out = harness.run(*fmt)
    assert status == 0
    if fmt:
        report = json.loads(out)
        assert report["scanners"] == {
            "detect-secrets": {"status": "ran"},
            "secretlint": {"status": "ran"},
        }
        assert report["summary"]["failed_scanners"] == []
    else:
        assert "- `secretlint`: ran" in out
        assert "No secrets detected" in out
        assert "incomplete" not in out


def test_skip_on_request_is_not_a_failure(harness: Harness) -> None:
    """--no-secretlint reports a skip and never starts bun."""
    harness.install(bun="exit 99")
    status, out = harness.run("--no-secretlint", "--json")
    assert status == 0
    assert json.loads(out)["scanners"]["secretlint"] == {
        "status": "skipped",
        "reason": "--no-secretlint",
    }
    status, out = harness.run("--no-secretlint")
    assert status == 0
    assert "- `secretlint`: skipped on request — --no-secretlint" in out


FAILURES = {
    "detect-secrets process failure": (
        {"uvx": "echo partial; exit 3"},
        "detect-secrets",
        "exit status 3",
    ),
    "detect-secrets malformed JSON": (
        {"uvx": """echo '{"results": '"""},
        "detect-secrets",
        "output was not valid JSON",
    ),
    "secretlint setup failure": (
        {"bun": "exit 1"},
        "secretlint",
        "bun add failed (exit 1)",
    ),
    "secretlint skipped batch": (
        {"secretlint": """[[ " $* " == *"/b.txt "* ]] && echo 'not json'; echo '[]'"""},
        "secretlint",
        "1 of 2 batches not scanned (first: output was not valid JSON)",
    ),
    "secretlint process failure": (
        {"secretlint": "exit 2"},
        "secretlint",
        "2 of 2 batches not scanned (first: exit status 2)",
    ),
}


@FORMATS
@pytest.mark.parametrize("case", FAILURES.values(), ids=FAILURES)
def test_failed_scanner_exits_2_and_is_named(
    harness: Harness,
    case: tuple[dict[str, str], str, str],
    fmt: list[str],
) -> None:
    """A requested scanner that does not finish makes the scan incomplete."""
    fakes, name, reason = case
    harness.install(**fakes)
    status, out = harness.run(*fmt)
    assert status == 2
    if fmt:
        report = json.loads(out)
        assert report["scanners"][name] == {"status": "failed", "reason": reason}
        assert report["summary"]["failed_scanners"] == [name]
        other = ({"detect-secrets", "secretlint"} - {name}).pop()
        assert report["scanners"][other] == {"status": "ran"}
    else:
        assert f"- `{name}`: **failed** — {reason}" in out
        assert f"Scan incomplete:** `{name}`" in out
        assert "No secrets detected" not in out


# A well-formed secretlint result flagging the token on line 1 of a.txt
FLAGGED = {
    "filePath": "a.txt",
    "messages": [
        {
            "ruleId": "@secretlint/secretlint-rule-github",
            "messageId": "GITHUB_TOKEN",
            "message": "found",
            "loc": {
                "start": {"line": 1, "column": 6},
                "end": {"line": 1, "column": 6 + len(TOKEN)},
            },
        }
    ],
}
MESSAGE = (0, "messages", 0)
LOC = (*MESSAGE, "loc")

# Where a malformed value replaces part of [FLAGGED], and the reason
MALFORMED_SECRETLINT = {
    "null item": ((0,), None, "a result item was not a JSON object"),
    "scalar item": ((0,), TOKEN, "a result item was not a JSON object"),
    "list item": ((0,), [TOKEN], "a result item was not a JSON object"),
    "filePath not a string": (
        (0, "filePath"),
        [TOKEN],
        "filePath was not a JSON string",
    ),
    "messages not a list": ((0, "messages"), TOKEN, "messages was not a JSON list"),
    "message not an object": (MESSAGE, [TOKEN], "a message was not a JSON object"),
    "loc not an object": (LOC, TOKEN, "loc was not a JSON object"),
    "start not an object": ((*LOC, "start"), None, "loc.start was not a JSON object"),
    "end not an object": ((*LOC, "end"), [TOKEN], "loc.end was not a JSON object"),
    "column not an integer": (
        (*LOC, "start", "column"),
        TOKEN,
        "a position was not a JSON integer",
    ),
}

MALFORMED_DETECT_SECRETS = {
    "results not a mapping": ([TOKEN], "output had no results object"),
    "entry not a list": (
        {"a.txt": [], "b.txt": TOKEN},
        "a results entry was not a JSON list",
    ),
    "finding not an object": (
        {"a.txt": [], "b.txt": [TOKEN]},
        "a finding was not a JSON object",
    ),
}


def replaced(path: tuple, value: object) -> list:
    """Return [FLAGGED] with the part at path replaced by value."""
    data = copy.deepcopy([FLAGGED])
    *parents, last = path
    target: Any = data
    for key in parents:
        target = target[key]
    target[last] = value
    return data


def secretlint_by_file(b_output: object) -> str:
    """Return a fake secretlint printing [FLAGGED] for a.txt and b_output for b.txt."""
    a, b = (shlex.quote(json.dumps(x)) for x in ([FLAGGED], b_output))
    return f"""[[ " $* " == *"/b.txt "* ]] && echo {b} || echo {a}"""


def assert_incomplete_but_kept(
    harness: Harness, fmt: list[str], name: str, reason: str
) -> None:
    """Exit 2 names the failed scanner; the well-formed a.txt finding is listed."""
    for path in [harness.repo / "a.txt", harness.repo / "b.txt"]:
        path.write_text(f"TOKEN={TOKEN}\n", encoding="utf-8")
    status, out = harness.run(*fmt)
    assert status == 2
    if fmt:
        report = json.loads(out)
        assert report["scanners"][name] == {"status": "failed", "reason": reason}
        assert report["summary"]["failed_scanners"] == [name]
        assert [(f["source"], f["file"]) for f in report["findings"]] == [
            ("secretlint", "a.txt")
        ]
    else:
        assert f"- `{name}`: **failed** — {reason}" in out
        assert f"Scan incomplete:** `{name}`" in out
        assert "`a.txt` line 1" in out
        assert "Needs Review (1 findings)" in out


@FORMATS
@pytest.mark.parametrize(
    "case", MALFORMED_SECRETLINT.values(), ids=MALFORMED_SECRETLINT
)
def test_malformed_secretlint_batch_fails_the_scanner(
    harness: Harness, case: tuple[tuple, object, str], fmt: list[str]
) -> None:
    """A batch with a malformed nested shape is not scanned; others are kept."""
    path, value, reason = case
    harness.install(secretlint=secretlint_by_file(replaced(path, value)))
    assert_incomplete_but_kept(
        harness, fmt, "secretlint", f"1 of 2 batches not scanned (first: {reason})"
    )


@FORMATS
@pytest.mark.parametrize(
    "case", MALFORMED_DETECT_SECRETS.values(), ids=MALFORMED_DETECT_SECRETS
)
def test_malformed_detect_secrets_results_fail_the_scanner(
    harness: Harness, case: tuple[object, str], fmt: list[str]
) -> None:
    """Malformed detect-secrets results fail it; secretlint findings are kept."""
    results, reason = case
    harness.install(
        uvx=harness.cat("baseline.json", {"results": results}),
        secretlint=secretlint_by_file([]),
    )
    assert_incomplete_but_kept(harness, fmt, "detect-secrets", reason)


def test_failure_outranks_findings(harness: Harness) -> None:
    """Findings from the finished scanner are listed, yet the exit is 2."""
    (harness.repo / "a.txt").write_text(f"TOKEN={TOKEN}\n", encoding="utf-8")
    baseline = {"results": {"a.txt": [{"line_number": 1, "type": "Secret Keyword"}]}}
    harness.install(uvx=harness.cat("baseline.json", baseline), bun="exit 1")
    status, out = harness.run()
    assert status == 2
    assert "`a.txt` line 1" in out
    assert "Needs Review (1 findings)" in out


def test_placeholder_is_judged_from_the_detected_value(harness: Harness) -> None:
    """A real-format value beside a placeholder word still needs review."""
    placeholder = "your_key_here"
    config = harness.repo / "config.txt"
    config.write_text(
        f"TOKEN={TOKEN}  # replace with {placeholder}\nTOKEN={placeholder}\n",
        encoding="utf-8",
    )
    spans = [(1, TOKEN), (2, placeholder)]
    baseline = {
        "results": {
            "config.txt": [
                {
                    "line_number": line,
                    "type": "Secret Keyword",
                    "hashed_secret": hashlib.sha1(
                        value.encode(), usedforsecurity=False
                    ).hexdigest(),
                }
                for line, value in spans
            ]
        }
    }
    messages = [
        {
            "ruleId": "@secretlint/secretlint-rule-github",
            "messageId": "GITHUB_TOKEN",
            "message": f"found: {value}",
            "loc": {
                "start": {"line": line, "column": 6},
                "end": {"line": line, "column": 6 + len(value)},
            },
        }
        for line, value in spans
    ]
    results = harness.cat(
        "secretlint.json", [{"filePath": str(config), "messages": messages}]
    )
    harness.install(
        uvx=harness.cat("baseline.json", baseline),
        secretlint=f"""[[ " $* " == *"/config.txt "* ]] && {results} || echo '[]'""",
    )
    status, out = harness.run("--json")
    assert status == 1
    report = json.loads(out)
    assert report["summary"]["failed_scanners"] == []
    labels = [(f["source"], f["line"], f["classification"]) for f in report["findings"]]
    assert labels == [
        ("detect-secrets", 1, "review-required"),
        ("detect-secrets", 2, "likely-false-positive"),
        ("secretlint", 1, "review-required"),
        ("secretlint", 2, "likely-false-positive"),
    ]
    assert placeholder not in out, "Raw source appeared in report"


def test_unrecoverable_value_needs_review() -> None:
    """Without a matching hash, a placeholder word cannot excuse a line."""
    line = f"TOKEN={TOKEN}  # your_key_here"
    assert scan.detect_secrets_value(line, "0" * 40) is None
    assert scan.detect_secrets_value(line, "") is None
    assert scan.classify(None) == "review-required"
