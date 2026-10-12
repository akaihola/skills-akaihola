#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Print the dump lines behind an evidence reference from analysis.json.

References look like ``live/batterystats_charged.txt:462``,
``bugreport:KERNEL LOG:123456`` (a line of the bugreport's main text) or
``bugreport:lshal-debug/android.hardware.health@2.1.txt:12`` (a line inside
a zip member). Use this to check a finding against its cited evidence.

Exit codes:
  0  lines printed
  2  usage error, or the reference does not resolve
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from androiddiag.source import Workdir


def resolve(workdir: Workdir, ref: str) -> tuple[list[str], int] | None:
    """Return the lines of the referenced text and the 1-based line number.

    Returns None when the source is missing or the line is out of range.
    """
    origin, _, number = ref.rpartition(":")
    if not number.isdigit() or not origin:
        return None
    line = int(number)
    lines: list[str] | None = None
    if origin.startswith("live/") and ".." not in Path(origin).parts:
        path = workdir.root / origin
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    elif origin.startswith("bugreport:") and workdir.bugreport:
        name = origin.removeprefix("bugreport:")
        member = workdir.bugreport.member(name)
        lines = member.lines if member else workdir.bugreport.lines
    if lines is None or not 1 <= line <= len(lines):
        return None
    return lines, line


def main() -> int:
    """Print the referenced line with context."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("workdir", type=Path, help="directory from collect.py")
    parser.add_argument("ref", nargs="+", help="evidence reference(s)")
    parser.add_argument("-C", "--context", type=int, default=3, help="lines around")
    args = parser.parse_args()
    workdir = Workdir(args.workdir)
    status = 0
    for ref in args.ref:
        found = resolve(workdir, ref)
        if found is None:
            print(f"cannot resolve {ref!r}", file=sys.stderr)
            status = 2
            continue
        lines, line = found
        first = max(1, line - args.context)
        last = min(len(lines), line + args.context)
        print(f"== {ref}")
        for n in range(first, last + 1):
            marker = ">" if n == line else " "
            print(f"{marker}{n:>8}  {lines[n - 1]}")
    return status


if __name__ == "__main__":
    sys.exit(main())
