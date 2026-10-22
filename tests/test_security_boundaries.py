"""Offline regressions for document, attachment and scanner trust boundaries."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: str) -> ModuleType:
    """Load a standalone skill without interfering with other test imports."""
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ram = load_script(
    "security_read_as_markdown", "read-as-markdown/scripts/read_as_markdown.py"
)
email = load_script(
    "security_email_save", "himalaya-email-manager/scripts/email_save.py"
)
scan = load_script("security_scan", "secrets-scan/scripts/scan.py")


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize(
    "name",
    [
        "quote\x27.pdf",
        "invoice\x27$(touch MARKER)\x27.pdf",
        "`touch MARKER`.pdf",
        "semi;colon.pdf",
        "-leading.pdf",
    ],
)
def test_pdf_names_are_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    fallback: bool,
) -> None:
    """Exercise the real shell fallback with fake binaries and hostile names."""
    monkeypatch.chdir(tmp_path)
    source = Path(name)
    source.write_text("synthetic PDF")
    binary = tmp_path / "pdftotext"
    binary.write_text(
        f"#!{shutil.which('bash')}\n"
        "if [[ $1 == -v ]]; then echo pdftotext >&2; exit; fi\n"
        '[[ $1 == -layout && $2 == -- && $3 == "$EXPECTED" && $4 == - ]] || exit 2\n'
        "echo converted\n"
    )
    binary.chmod(0o700)
    nix = tmp_path / "nix-shell"
    nix.write_text(
        f'#!{shutil.which("bash")}\nexec {shutil.which("bash")} -c "${{@: -1}}"\n'
    )
    nix.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("EXPECTED", str(source))
    monkeypatch.setattr(
        ram.shutil,
        "which",
        lambda cmd: None if fallback and cmd == "pdftotext" else str(tmp_path / cmd),
    )
    try:
        text, _ = ram.pdftotext_converter(source)
    except RuntimeError:
        pytest.fail("PDF name was not passed as an argument", pytrace=False)
    assert text.strip() == "converted"
    assert not (tmp_path / "MARKER").exists()


@pytest.mark.parametrize("entry", ["absolute", "traversal", "symlink", "proc"])
def test_planted_cache_index_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    """An index cannot cause an outside read, including through a symlink."""
    source = tmp_path / "paper.pdf"
    source.write_text("synthetic PDF")
    cache = tmp_path / ".cache" / "markdown"
    cache.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside content must not be returned")
    link = cache / "link.md"
    link.symlink_to(outside)
    value = {
        "absolute": str(outside),
        "traversal": "../../outside.md",
        "symlink": "link.md",
        "proc": "/proc/self/environ",
    }[entry]
    (cache / "index.json").write_text(json.dumps({ram.content_hash(source): value}))
    if entry == "proc":
        assert ram.check_hash_index(source, ram.content_hash(source), tmp_path) is None
        return
    monkeypatch.setitem(
        ram.BACKENDS, "pdf", [("stub", lambda _: ("converted", "stub"))]
    )
    result = ram.convert(source, workspace_root=tmp_path)
    assert result.get("content") == "converted"
    assert result["cached"] is False


@pytest.mark.parametrize(
    "component",
    [
        ".cache",
        ".cache/markdown",
        ".cache/markdown/paper.pdf.md",
        ".cache/markdown/paper.pdf.meta",
        ".cache/markdown/index.json",
    ],
)
def test_symlinked_cache_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component: str
) -> None:
    """Neither cached reads nor writes may follow planted symlinks."""
    source = tmp_path / "paper.pdf"
    source.write_text("synthetic PDF")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside if component in {".cache", ".cache/markdown"} else outside / "file"
    if target != outside:
        target.write_text("unchanged")
    link = tmp_path / component
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    monkeypatch.setitem(
        ram.BACKENDS, "pdf", [("stub", lambda _: ("converted", "stub"))]
    )
    assert "error" in ram.convert(source, workspace_root=tmp_path)
    assert sorted(p.name for p in outside.iterdir()) == (
        [] if target == outside else ["file"]
    )
    if target != outside:
        assert target.read_text() == "unchanged"


def test_document_cannot_choose_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A downloaded .claude directory does not select the cache destination."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    download = tmp_path / "download"
    (download / ".claude").mkdir(parents=True)
    source = download / "paper.pdf"
    source.write_text("synthetic PDF")
    monkeypatch.chdir(workspace)
    monkeypatch.setitem(
        ram.BACKENDS, "pdf", [("stub", lambda _: ("converted", "stub"))]
    )
    result = ram.convert(source)
    assert Path(result["cache_path"]).is_relative_to(workspace)
    assert not (download / ".cache").exists()


def test_relative_index_reuses_renamed_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confinement retains content-hash cache reuse and relative entries."""
    source = tmp_path / "paper.pdf"
    source.write_text("synthetic PDF")
    calls = []
    monkeypatch.setitem(
        ram.BACKENDS,
        "pdf",
        [("stub", lambda p: (calls.append(p) or "converted", "stub"))],
    )
    ram.convert(source, workspace_root=tmp_path)
    renamed = source.rename(tmp_path / "renamed.pdf")
    result = ram.convert(renamed, workspace_root=tmp_path)
    assert result["cached"] is True
    assert len(calls) == 1
    index = json.loads((tmp_path / ".cache/markdown/index.json").read_text())
    assert all(not Path(value).is_absolute() for value in index.values())


def test_attachments_are_isolated_and_never_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ignore log paths; stage hostile names and retain every existing file."""
    monkeypatch.chdir(tmp_path)
    names = [
        "CLAUDE.md",
        ".bashrc",
        "$(x).pdf",
        "../x",
        "a?.pdf",
        "a*.pdf",
        "-leading.pdf",
    ]
    for name in ["CLAUDE.md", ".bashrc", "x"]:
        (tmp_path / name).write_text("original")
    destination = tmp_path / "57039-attachments"
    destination.mkdir()
    (destination / "CLAUDE.md").write_text("existing attachment")
    outside = tmp_path / "outside"
    outside.write_text("outside")

    def download(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        staging = (
            Path(args[args.index("-d") + 1])
            if "-d" in args
            else tmp_path / "legacy-download"
        )
        staging.mkdir(exist_ok=True)
        for name in names:
            (staging / Path(name).name).write_text("attachment")
        (staging / "link").symlink_to(outside)
        return subprocess.CompletedProcess(args, 0, f'Downloading "{outside}"…', "")

    monkeypatch.setattr(email, "run_himalaya", download)
    files = email._download_attachments_internal(57039, "INBOX", destination)
    assert len(files) == len(names)
    assert len(set(files)) == len(names)
    assert all(p.parent == destination and p.read_text() == "attachment" for p in files)
    assert all(
        p.name[0].isalnum()
        and all(c.isascii() and (c.isalnum() or c in "._-") for c in p.name)
        for p in files
    )
    assert (destination / "CLAUDE.md").read_text() == "existing attachment"
    assert outside.read_text() == "outside"
    assert all(
        (tmp_path / name).read_text() == "original"
        for name in ["CLAUDE.md", ".bashrc", "x"]
    )


def test_secret_values_stay_out_of_both_reports(tmp_path: Path) -> None:
    """Both scanner sources retain classifications without raw values/messages."""
    token = "ghp_" + "SyntheticOnly0123456789" * 2
    (tmp_path / "config.txt").write_text(f"TOKEN={token}\nTOKEN=your_key_here\n")
    values = [(1, token), (2, "your_key_here")]
    ds = {
        "results": {
            "config.txt": [
                {
                    "line_number": n,
                    "type": "Secret Keyword",
                    "hashed_secret": hashlib.sha1(
                        value.encode(), usedforsecurity=False
                    ).hexdigest(),
                }
                for n, value in values
            ]
        }
    }
    sl = [
        {
            "file": "config.txt",
            "line": n,
            "col": 6,
            "end_line": n,
            "end_col": 6 + len(value),
            "message_id": "TOKEN",
            "rule_id": "rule",
            "message": token,
            "docs_url": token,
        }
        for n, value in values
    ]
    scanners = {"detect-secrets": scan.RAN, "secretlint": scan.RAN}
    combined = scan.build_combined(tmp_path, ds, sl, scanners)
    for report in [json.dumps(combined), scan.render_markdown(combined)]:
        assert token not in report, "Secret appeared in report"
        assert "SyntheticOnly" not in report, "Secret fragment appeared in report"
        assert "your_key_here" not in report, "Raw source appeared in report"
    assert [f["classification"] for f in combined["findings"]] == [
        "review-required",
        "likely-false-positive",
    ] * 2
    assert all(f["file"] == "config.txt" and f["type"] for f in combined["findings"])


@pytest.mark.parametrize("as_json", [False, True])
def test_scanner_cli_redacts_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    as_json: bool,
) -> None:
    """Exercise stdout, stderr and exit status without running external scanners."""
    token = "ghp_" + "OfflineSynthetic123" * 3
    (tmp_path / "config.txt").write_text(f"TOKEN={token}\n")
    baseline = {
        "results": {"config.txt": [{"line_number": 1, "type": "Secret Keyword"}]}
    }
    monkeypatch.setattr(scan, "run_detect_secrets", lambda *a, **k: baseline)
    monkeypatch.setattr(scan, "setup_secretlint", lambda p: p / "secretlint")
    monkeypatch.setattr(scan, "get_git_tracked_files", lambda p: ["config.txt"])
    monkeypatch.setattr(
        scan,
        "run_secretlint",
        lambda *a: (
            [
                {
                    "file": "config.txt",
                    "line": 1,
                    "col": 6,
                    "end_line": 1,
                    "end_col": 6 + len(token),
                    "message_id": "TOKEN",
                    "rule_id": "rule",
                    "message": token,
                    "docs_url": token,
                }
            ],
            None,
        ),
    )
    monkeypatch.setattr(
        sys, "argv", ["scan.py", str(tmp_path), *(["--json"] if as_json else [])]
    )
    assert scan.main() == 1
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err, "Secret appeared in CLI output"
    assert "OfflineSynthetic" not in captured.out + captured.err
    assert "config.txt" in captured.out
    assert "TOKEN" in captured.out


def test_scanner_errors_are_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scanner failures must not copy raw diagnostics into the transcript."""
    token = "synthetic-sensitive-diagnostic"
    commands = []

    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(args, 2, "", token)

    monkeypatch.setattr(scan.subprocess, "run", run)
    with pytest.raises(scan.ScannerError) as ds_error:
        scan.run_detect_secrets(tmp_path, all_files=True)
    assert "--no-verify" in commands[0]
    assert "--all-files" in commands[0]
    with pytest.raises(scan.ScannerError) as sl_error:
        scan.setup_secretlint(tmp_path)
    assert token not in str(ds_error.value) + str(sl_error.value)
    assert token not in capsys.readouterr().err


def test_declining_email_overwrite_skips_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declining a save must happen before any attachment download."""
    output = tmp_path / "message.md"
    output.write_text("original")
    monkeypatch.setattr(
        email,
        "get_message",
        lambda *a, **k: {
            "envelope": {"subject": "synthetic", "date": "2026-01-01"},
            "body": "synthetic",
        },
    )
    monkeypatch.setattr(email.Confirm, "ask", lambda *a, **k: False)
    monkeypatch.setattr(
        email,
        "_process_attachments",
        lambda *a: pytest.fail("Downloaded before confirmation"),
    )
    with pytest.raises(email.typer.Exit):
        email.save(
            57039,
            folder="INBOX",
            output=output,
            output_format="markdown",
            overwrite=False,
            download_attachments=True,
            attachment_dir=None,
            date_prefix=False,
            verbose=False,
        )
    assert output.read_text() == "original"
