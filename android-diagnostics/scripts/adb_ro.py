#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run one ad-hoc read-only command on the phone, refusing anything else.

    adb_ro.py [--serial S] [--save KEY --workdir DIR] -- dumpsys wifi

The command must match a read-only shape (dumpsys SERVICE without arguments,
or with arguments vetted for that service such as batterystats --charged;
getprop; cat/ls/head/tail/grep/wc under /proc, /sys, /vendor/etc,
/system/etc, /product/etc; settings get|list, logcat -d, ip ... show, and a
few more; see androiddiag/readonly.py) and may not contain shell syntax such
as ; | > $ { or quotes. Run several simple commands instead of one pipeline.
A rejected command prints the forms that are allowed.

Without --save the command's output goes to stdout. With --save it is written
to DIR/live/KEY.txt (stderr to KEY.err), recorded under "adhoc" in
DIR/manifest.json, and only the saved path is printed.

Exit codes:
  2    the command was rejected (the reason is printed), usage error, or no
       usable device
  124  the command timed out
  else the exit code of the command on the phone
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from androiddiag.readonly import (
    DeviceError,
    append_manifest,
    check_adhoc,
    connect,
    now_iso,
    run_shell,
    save_output,
)
from androiddiag.storage import private_directory

if sys.version_info < (3, 11):  # ruff: ignore[outdated-version-block] - message for users of old Python
    sys.exit("adb_ro.py needs Python 3.11 or newer")

_KEY_RE = re.compile(r"[a-z0-9][a-z0-9_]*")  # used with fullmatch: no "\n"
TIMEOUT_EXIT = 124  # the convention of timeout(1)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line; the phone command follows ``--``."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--serial", help="adb serial, needed when several are attached")
    parser.add_argument("--save", metavar="KEY", help="save as WORKDIR/live/KEY.txt")
    parser.add_argument("--workdir", type=Path, help="workdir for --save")
    parser.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="seconds before giving up (default: %(default)s)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="the command words")
    args = parser.parse_args(argv)
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("give the command after --, for example: -- dumpsys wifi")
    if bool(args.save) != bool(args.workdir):
        parser.error("--save and --workdir go together")
    if args.save:
        if not _KEY_RE.fullmatch(args.save):
            parser.error("--save KEY may contain only a-z, 0-9 and _")
        target = args.workdir / "live" / f"{args.save}.txt"
        if target.exists():
            parser.error(f"{target} exists; choose another KEY")
    return args


def main(argv: list[str] | None = None) -> int:
    """Validate, run and print or save one command."""
    args = parse_args(argv)
    command = " ".join(args.command)
    try:
        check_adhoc(command)
    except ValueError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2
    try:
        if args.save:
            private_directory(args.workdir)
            private_directory(args.workdir / "live")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        adb, device = connect(args.serial)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    started = now_iso()
    run = run_shell(adb, device.serial, command, args.timeout, adhoc=True)
    if args.save:
        path = save_output(args.workdir / "live", args.save, run)
        entry = {"key": args.save, "command": command, "started": started}
        append_manifest(args.workdir, "adhoc", entry | run.record(device.serial))
        print(path)
    else:
        sys.stdout.buffer.write(run.stdout)
        sys.stdout.flush()
    if run.stderr:
        sys.stderr.buffer.write(run.stderr)
    if run.error:
        print(f"adb_ro: {run.error}", file=sys.stderr)
    if run.exit_code is None:
        return TIMEOUT_EXIT if "timed out" in run.error else 1
    return run.exit_code


if __name__ == "__main__":
    sys.exit(main())
