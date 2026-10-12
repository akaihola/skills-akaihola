"""Tests for show_ref.py, which prints the dump lines behind an evidence ref."""

from __future__ import annotations

import subprocess
import sys

import pytest
from androiddiag.source import Workdir
from conftest import SCRIPTS
from show_ref import resolve

LIVE = "".join(f"line {n}\n" for n in range(1, 11))


@pytest.fixture
def workdir(workdir_factory):
    root = workdir_factory(
        live={"battery": LIVE},
        sections={"KERNEL LOG (dmesg)": "[  1.0] first\n[  2.0] second"},
        members={"lshal-debug/android.hardware.health@2.1.txt": "a\nb\nc"},
    )
    return Workdir(root)


def show(workdir: Workdir, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "show_ref.py"), str(workdir.root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_live_ref_with_context(workdir):
    proc = show(workdir, "live/battery.txt:5", "-C", "1")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        "== live/battery.txt:5",
        "        4  line 4",
        ">       5  line 5",
        "        6  line 6",
    ]


def test_bugreport_section_and_member_refs(workdir):
    br = workdir.bugreport
    assert br is not None
    dmesg = br.section("KERNEL LOG")
    assert dmesg is not None
    found = resolve(workdir, dmesg.ref(1))
    assert found is not None
    lines, line = found
    assert lines[line - 1] == "[  2.0] second"
    found = resolve(workdir, "bugreport:lshal-debug/android.hardware.health@2.1.txt:3")
    assert found == (["a", "b", "c"], 3)


@pytest.mark.parametrize(
    "ref",
    [
        "live/battery.txt:11",
        "live/battery.txt:0",
        "live/missing.txt:1",
        "live/../live/battery.txt:1",
        "elsewhere:1",
        "live/battery.txt",
    ],
)
def test_unresolvable_refs(workdir, ref):
    assert resolve(workdir, ref) is None


def test_cli_reports_unresolvable_ref(workdir):
    proc = show(workdir, "live/battery.txt:2", "live/battery.txt:99")
    assert proc.returncode == 2
    assert "== live/battery.txt:2" in proc.stdout
    assert "cannot resolve 'live/battery.txt:99'" in proc.stderr
