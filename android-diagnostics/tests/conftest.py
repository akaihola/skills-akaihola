"""Shared fixtures: build synthetic bugreport zips and workdirs from text snippets.

All fixture data is invented. Lines follow the formats of real dumps, but every
number, name, address, version and date in them is made up. Never paste lines
from a real phone's dumps, here or in tests/fixtures/: they contain serials,
MAC and IP addresses, network names and app usage, and even an anonymised line
can identify the phone through its counters.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from textwrap import dedent

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

HEADER = dedent(
    """\
    ========================================================
    == dumpstate: 2026-01-15 12:00:00
    ========================================================

    Build: TEST.1.0
    Build fingerprint: 'Vendor/product/device:15/TEST.1.0/1:user/release-keys'
    Android SDK version: 35
    """,
)


def bugreport_text(
    sections: dict[str, str] | None = None,
    services: dict[str, str] | None = None,
) -> str:
    """Return a dumpstate main text with the given sections and service dumps.

    Section keys are full titles such as ``"KERNEL LOG (dmesg)"``.
    """
    parts = [HEADER]
    for title, body in (sections or {}).items():
        parts.append(f"------ {title} ------\n{body.rstrip()}\n")
    if services:
        parts.append("------ DUMPSYS (/system/bin/dumpsys) ------\n")
        for name, body in services.items():
            parts.append(
                f"DUMP OF SERVICE {name}:\n{body.rstrip()}\n"
                f"--------- 0.010s was the duration of dumpsys {name}, "
                "ending at: 2026-01-15 12:00:05\n",
            )
    parts.append("------ 0.001s was the duration of 'DUMPSYS' ------\n")
    return "\n".join(parts)


def make_bugreport(
    path: Path,
    sections: dict[str, str] | None = None,
    services: dict[str, str] | None = None,
    members: dict[str, str] | None = None,
) -> Path:
    """Write a bugreport zip with a main text and extra members; return its path."""
    main = "bugreport-product-TEST.1.0-2026-01-15-12-00-00.txt"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("main_entry.txt", main)
        zf.writestr("version.txt", "2.0")
        zf.writestr(main, bugreport_text(sections, services))
        for name, body in (members or {}).items():
            zf.writestr(name, body)
    return path


def make_workdir(
    root: Path,
    live: dict[str, str] | None = None,
    **bugreport: dict[str, str] | None,
) -> Path:
    """Create a workdir with ``live/<key>.txt`` files and optionally a bugreport.

    Keyword arguments ``sections``, ``services`` and ``members`` go to
    :func:`make_bugreport`; without any of them no zip is written.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "live").mkdir(exist_ok=True)
    for key, body in (live or {}).items():
        (root / "live" / f"{key}.txt").write_text(body)
    if any(bugreport.values()):
        make_bugreport(root / "bugreport-test.zip", **bugreport)
    return root


@pytest.fixture
def workdir_factory(tmp_path):
    """Return a function that builds a fresh workdir under ``tmp_path``."""
    counter = iter(range(1000))

    def factory(live=None, **bugreport):
        return make_workdir(tmp_path / f"wd{next(counter)}", live, **bugreport)

    return factory


@pytest.fixture
def context_factory(workdir_factory):
    """Return a function that builds an analyzer Context over a synthetic workdir."""
    from androiddiag.common import PackageMap
    from androiddiag.model import Context, Windows
    from androiddiag.source import Sources, Workdir

    def factory(live=None, packages=None, windows=None, **bugreport):
        sources = Sources(Workdir(workdir_factory(live, **bugreport)))
        return Context(
            sources=sources,
            packages=PackageMap.from_pm_list(packages or ""),
            windows=windows or Windows(),
        )

    return factory
