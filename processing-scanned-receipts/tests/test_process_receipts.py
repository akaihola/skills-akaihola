"""Verify receipt previews and processing using synthetic inputs only."""

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parents[1] / "process_receipts.py"
SPEC = importlib.util.spec_from_file_location("process_receipts", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
receipts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipts)

METADATA = {
    "date": "2026-01-02",
    "payee": "Unknown supplier",
    "description": "synthetic purchase",
}
BASE = "2026-01-02 Unknown supplier synthetic purchase"


def snapshot(root: Path) -> dict:
    """Record directories and file hashes to detect preview side effects."""
    return {
        str(path.relative_to(root)): (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        for path in root.rglob("*")
    }


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("custom_cache", [False, True])
def test_preview_cached_and_uncached(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *,
    force: bool, custom_cache: bool,
) -> None:
    """Preview JSON without JPGs, skip misses, and preserve every input."""
    target = tmp_path / "inputs"
    target.mkdir()
    work = tmp_path / "cache" if custom_cache else target / ".receipt-work"
    work.mkdir()
    for name in ("cached", "duplicate", "uncached"):
        (target / f"{name}.pdf").write_bytes(b"synthetic PDF")
    for name in ("cached", "duplicate"):
        (work / f"{name}.json").write_text(json.dumps(METADATA), encoding="utf-8")
    before = snapshot(tmp_path)
    args = [str(SCRIPT), str(target), "--dry-run"]
    if force:
        args.append("--force")
    if custom_cache:
        args.extend(["--work-dir", str(work)])
    with (
        patch("sys.argv", args),
        patch.object(receipts.subprocess, "run") as subprocess_run,
        patch.object(receipts, "process_one") as process_one,
    ):
        receipts.main()
    subprocess_run.assert_not_called()
    process_one.assert_not_called()
    output = capsys.readouterr().out
    assert f"→ {BASE}.{{pdf,jpg,txt}}" in output
    assert f"→ {BASE} (2).{{pdf,jpg,txt}}" in output
    assert "Cache miss: uncached.pdf" in output
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("empty", [False, True])
def test_preview_never_creates_missing_cache(tmp_path: Path, *, empty: bool) -> None:
    """An absent nested work directory stays absent, including with no PDFs."""
    if not empty:
        (tmp_path / "uncached.pdf").write_bytes(b"synthetic PDF")
    before = snapshot(tmp_path)
    with (
        patch("sys.argv", [str(SCRIPT), str(tmp_path), "--dry-run",
                           "--work-dir", str(tmp_path / "missing" / "cache")]),
        patch.object(receipts.subprocess, "run") as subprocess_run,
    ):
        if empty:
            with pytest.raises(SystemExit, match="No PDF files"):
                receipts.main()
        else:
            receipts.main()
    subprocess_run.assert_not_called()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("metadata", [b"invalid JSON", b"[]", b"\xff"])
def test_preview_invalid_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], metadata: bytes,
) -> None:
    """Invalid metadata is reported without attempting repairs or OCR."""
    (tmp_path / "scan.pdf").write_bytes(b"synthetic PDF")
    work = tmp_path / ".receipt-work"
    work.mkdir()
    (work / "scan.json").write_bytes(metadata)
    before = snapshot(tmp_path)
    with (
        patch("sys.argv", [str(SCRIPT), str(tmp_path), "--dry-run"]),
        patch.object(receipts.subprocess, "run") as subprocess_run,
    ):
        receipts.main()
    subprocess_run.assert_not_called()
    assert "Cache error: scan.pdf" in capsys.readouterr().err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("force", [False, True])
def test_normal_processing_with_mocked_ocr(tmp_path: Path, *, force: bool) -> None:
    """Normal processing still extracts, caches, renders, copies and renames."""
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"synthetic PDF")
    work = tmp_path / ".receipt-work"
    if force:
        work.mkdir()
        (work / "scan-000.jpg").write_bytes(b"old synthetic image")
        (work / "scan.json").write_text("{}", encoding="utf-8")

    def extract(pdf: Path, cache: Path) -> Path:
        assert pdf == source
        assert cache.is_dir()
        image = cache / "scan-000.jpg"
        image.write_bytes(b"synthetic image")
        return image

    args = [str(SCRIPT), str(tmp_path)]
    if force:
        args.append("--force")
    with (
        patch("sys.argv", args),
        patch.object(
            receipts, "extract_jpg_from_pdf", side_effect=extract,
        ) as extraction,
        patch.object(receipts, "ocr_receipt", return_value=METADATA) as ocr,
        patch.object(receipts.subprocess, "run") as subprocess_run,
    ):
        receipts.main()
    extraction.assert_called_once_with(source, work)
    ocr.assert_called_once_with(work / "scan-000.jpg", receipts.DEFAULT_MODEL)
    subprocess_run.assert_not_called()
    assert json.loads((work / "scan.json").read_text(encoding="utf-8")) == METADATA
    assert not source.exists()
    assert (tmp_path / f"{BASE}.pdf").read_bytes() == b"synthetic PDF"
    assert (tmp_path / f"{BASE}.jpg").read_bytes() == b"synthetic image"
    assert (tmp_path / f"{BASE}.txt").read_text(encoding="utf-8") == (
        receipts.make_receipt_text(METADATA)
    )
