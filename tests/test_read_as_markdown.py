"""Offline cache identity and CLI status regressions with fake converters."""

import importlib.util
import json
import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "read-as-markdown/scripts/read_as_markdown.py"
spec = importlib.util.spec_from_file_location("read_as_markdown", SCRIPT)
assert spec
assert spec.loader
ram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ram)


def test_outside_same_name_documents_have_separate_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equal size and mtime must not let one outside file reuse another's text."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sources = [tmp_path / name / "report.pdf" for name in ("a", "b")]
    calls = []

    def fake_converter(source: Path) -> tuple[str, str]:
        calls.append(source)
        return source.read_text(encoding="utf-8"), "fake 1.0"

    monkeypatch.setitem(ram.BACKENDS, "pdf", [("fake", fake_converter)])
    for source, content in zip(
        sources, ("first document", "other document"), strict=True
    ):
        source.parent.mkdir()
        source.write_text(content, encoding="utf-8")
        os.utime(source, (1700000000, 1700000000))

    paths = [ram.compute_cache_paths(source, workspace) for source in sources]
    assert paths[0][0] != paths[1][0]
    assert paths[0][1] != paths[1][1]
    for source, (markdown, metadata) in zip(sources, paths, strict=True):
        result = ram.convert(source, workspace_root=workspace)
        assert result["cached"] is False
        assert (
            result["content"]
            == source.read_text(encoding="utf-8")
            == markdown.read_text(encoding="utf-8")
        )
        assert metadata.is_file()
        again = ram.convert(source, workspace_root=workspace)
        assert again["cached"] is True
        assert again["content"] == source.read_text(encoding="utf-8")
    assert calls == sources

    alias = tmp_path / "alias.pdf"
    alias.symlink_to(sources[0])
    assert ram.compute_cache_paths(alias, workspace) == paths[0]


def test_workspace_cache_paths_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing workspace-relative Markdown and metadata remain cache hits."""
    source = tmp_path / "documents" / "report.pdf"
    source.parent.mkdir()
    source.write_text("synthetic document", encoding="utf-8")
    markdown = tmp_path / ".cache/markdown/documents/report.pdf.md"
    metadata = markdown.with_suffix(".meta")
    assert ram.compute_cache_paths(source, tmp_path) == (markdown, metadata)
    markdown.parent.mkdir(parents=True)
    markdown.write_text("existing Markdown", encoding="utf-8")
    stat = source.stat()
    metadata.write_text(
        json.dumps({"mtime": stat.st_mtime, "size": stat.st_size}), encoding="utf-8"
    )
    monkeypatch.setitem(
        ram.BACKENDS,
        "pdf",
        [("fake", lambda _: pytest.fail("Existing cache should be reused"))],
    )
    result = ram.convert(source, workspace_root=tmp_path)
    assert result["cached"] is True
    assert result["content"] == "existing Markdown"


@pytest.mark.parametrize("converter_status", [0, 1])
def test_cli_conversion_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, converter_status: int
) -> None:
    """A fake pandoc exercises process exit status and preserves JSON output."""
    binary = tmp_path / "pandoc"
    binary.write_text(
        f"#!{shutil.which('bash')}\n"
        'if [[ $1 == --version ]]; then echo "pandoc fake"; exit 0; fi\n'
        'echo "synthetic conversion failed" >&2; echo "converted"; '
        f"exit {converter_status}\n",
        encoding="utf-8",
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    source = tmp_path / "report.docx"
    source.write_text("synthetic document", encoding="utf-8")
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [sys.executable, str(SCRIPT), str(source), "--workspace-root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    output = json.loads(result.stdout)
    assert result.returncode == converter_status
    if converter_status:
        assert output == {"error": "synthetic conversion failed"}
    else:
        assert output["content"] == "converted"
