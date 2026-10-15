"""Synthetic permission and unsafe-destination checks, without a device."""

from __future__ import annotations

import os
import stat
import sys
from datetime import datetime

import collect
import pytest
from androiddiag.readonly import Run, run_adb, save_output, write_json
from androiddiag.storage import private_directory, write_private

pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="POSIX permissions required"),
    pytest.mark.usefixtures("capture_umask"),
]


@pytest.fixture(params=[0o022, 0o002, 0])
def capture_umask(request):
    """Restore the process umask even when a check fails."""
    previous = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(previous)


def mode(path):
    """Return only the permission bits."""
    return stat.S_IMODE(path.stat().st_mode)


def test_capture_modes_before_writing(tmp_path, monkeypatch):
    """Workdirs and temporary files are private before any data is written."""
    root = tmp_path / "output"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    workdir = collect.make_workdir(root, "Example Phone", datetime(2026, 1, 1))
    assert mode(root) == 0o755
    assert mode(workdir) == mode(workdir / "live") == 0o700
    real_fdopen = os.fdopen
    temporary_modes = []

    def checked_fdopen(fd, *args, **kwargs):
        temporary_modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        assert temporary_modes[-1] == 0o600
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", checked_fdopen)
    save_output(workdir / "live", "example", Run(b"synthetic", b"error", 0, 0, ""))
    write_json(workdir / "manifest.json", {"synthetic": True})
    write_json(workdir / "manifest.json", {"synthetic": False})
    assert len(temporary_modes) == 4
    for path in workdir.rglob("*"):
        assert mode(path) == (0o700 if path.is_dir() else 0o600)
    assert not list(workdir.glob(".manifest.json.*"))


def test_existing_directory_policy(tmp_path):
    """Reuse private storage, reject public storage without changing it."""
    destination = tmp_path / "destination"
    destination.mkdir(mode=0o700)
    private_directory(destination)
    destination.chmod(0o755)
    with pytest.raises(ValueError, match="0700"):
        save_output(destination, "example", Run(b"synthetic", b"", 0, 0, ""))
    assert mode(destination) == 0o755
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public"])
def test_unsafe_files_are_not_written(tmp_path, kind):
    """Never follow links, truncate shared files or repair their permissions."""
    target = tmp_path / "unrelated"
    target.write_bytes(b"unchanged")
    target.chmod(0o644)
    destination = tmp_path / "capture"
    if kind == "symlink":
        destination.symlink_to(target)
    elif kind == "hardlink":
        destination.hardlink_to(target)
    else:
        destination.write_bytes(b"unchanged")
        destination.chmod(0o644)
    with pytest.raises(ValueError, match="capture file must"):
        write_private(destination, b"synthetic")
    assert target.read_bytes() == destination.read_bytes() == b"unchanged"
    assert mode(target) == 0o644


def test_directory_links_and_writable_parents_are_rejected(tmp_path):
    """An attacker cannot redirect a capture through a directory link."""
    target = tmp_path / "unrelated"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="not a link"):
        private_directory(link / "capture")
    assert list(target.iterdir()) == []
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o777)
    with pytest.raises(ValueError, match="writable parent"):
        private_directory(parent / "capture")
    assert not (parent / "capture").exists()


def test_manifest_does_not_follow_predictable_temp_link(tmp_path):
    """A leftover predictable temporary path is never opened."""
    target = tmp_path / "unrelated"
    target.write_bytes(b"unchanged")
    (tmp_path / "manifest.json.tmp").symlink_to(target)
    write_json(tmp_path / "manifest.json", {})
    assert target.read_bytes() == b"unchanged"
    assert mode(tmp_path / "manifest.json") == 0o600


def test_adb_child_creates_private_archive(tmp_path):
    """Even an adb implementation that replaces the archive inherits umask 077."""
    archive = tmp_path / "bugreport.zip"
    write_private(archive, b"")
    script = (
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        "p.unlink(); p.write_bytes(b'synthetic')"
    )
    run = run_adb(sys.executable, ["-c", script, str(archive)], 10)
    assert run.ok
    assert mode(archive) == 0o600


@pytest.mark.parametrize("valid", [True, False])
def test_bugreport_is_private_before_adb(tmp_path, monkeypatch, valid):
    """The archive is private before adb writes, including on failure."""
    import zipfile

    def fake_adb(_adb, args, _timeout):
        archive = tmp_path / "bugreport.zip"
        assert args[-1] == str(archive)
        assert mode(archive) == 0o600
        assert archive.read_bytes() == b""
        if valid:
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("synthetic.txt", "synthetic")
        else:
            archive.write_bytes(b"partial")
        return Run(b"", b"", 0 if valid else 1, 0, "" if valid else "failed")

    monkeypatch.setattr(collect, "run_adb", fake_adb)
    collector = collect.Collector("fake", "synthetic", tmp_path, {}, 1)
    assert collector.bugreport() is valid
    archive = tmp_path / ("bugreport.zip" if valid else "bugreport.zip.partial")
    assert mode(archive) == mode(tmp_path / "manifest.json") == 0o600
