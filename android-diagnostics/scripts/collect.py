#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Collect read-only diagnostics from an adb-connected Android phone.

Runs each command of the catalog (LIVE_COMMANDS in androiddiag/catalog.py)
with `adb shell`, saves its output as live/<key>.txt (stderr as
live/<key>.err), takes a bugreport as bugreport.zip and writes manifest.json.
The workdir path is the last line on stdout; progress and warnings go to
stderr. Analyse the workdir with analyze.py afterwards.

Collect soon after the drain or slowness, ideally before plugging the phone
in: charging ends the on-battery period, turns a sticky battery saver off and
releases deferred work. Wireless debugging avoids the USB cable.

Nothing on the phone is changed, except that `adb bugreport` leaves a copy of
the bugreport in the phone's own bugreport storage.

Exit codes:
  0  everything was collected, except optional dumps the phone refused
  2  usage error, adb missing, or no usable device (nothing collected)
  3  some commands failed (the workdir and manifest are still written)
  4  the bugreport failed (the live dumps are still written)
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from androiddiag.catalog import LIVE_COMMANDS, LiveCommand
from androiddiag.readonly import (
    DeviceError,
    check_shell,
    connect,
    now_iso,
    run_adb,
    run_shell,
    save_output,
    serial_hash,
    write_json,
)

if sys.version_info < (3, 11):  # ruff: ignore[outdated-version-block] - message for users of old Python
    sys.exit("collect.py needs Python 3.11 or newer")

# dumpstate usually takes 2-5 minutes; slow or busy phones need more.
BUGREPORT_TIMEOUT_S = 900
# Listing devices and reading a few properties is quick unless adb hangs.
DEVICE_TIMEOUT_S = 30
# Build properties for the manifest, read in one adb call before the dumps.
DEVICE_PROPS = (
    ("model", "ro.product.model"),
    ("product", "ro.product.name"),
    ("manufacturer", "ro.product.manufacturer"),
    ("build_fingerprint", "ro.build.fingerprint"),
    ("sdk", "ro.build.version.sdk"),
)
_POWERED_RE = re.compile(
    r"^\s*(AC|USB|Wireless|Dock) powered: (true|false)", re.MULTILINE
)
_LEVEL_RE = re.compile(r"^\s*level: (\d+)", re.MULTILINE)

BUGREPORT_NOTE = (
    "adb bugreport leaves a copy of the zip in the phone's own bugreport "
    "storage. It holds the same personal data; delete it on the phone if it "
    "should not stay there."
)
PLUGGED_WARNING = (
    "The phone is on external power ({sources}). Plugging in ended the "
    "on-battery period: live states such as Doze, battery saver and thermal "
    "status now describe charging, and a sticky battery saver has turned off. "
    "The since-last-charge battery statistics are still valid. For live "
    "experiments on battery, connect with wireless debugging (Settings > "
    "System > Developer options > Wireless debugging) instead of USB."
)


def log(message: str) -> None:
    """Print a progress or warning line on stderr."""
    print(message, file=sys.stderr, flush=True)


def select_commands(only: str | None) -> list[LiveCommand]:
    """Return the catalog commands to run, in catalog order."""
    if not only:
        return list(LIVE_COMMANDS)
    keys = {k.strip() for k in only.split(",") if k.strip()}
    unknown = sorted(keys - {c.key for c in LIVE_COMMANDS})
    if unknown:
        msg = f"unknown key(s) {', '.join(unknown)}; see --list"
        raise ValueError(msg)
    return [c for c in LIVE_COMMANDS if c.key in keys]


def is_optional(command: LiveCommand) -> bool:
    """Whether a failure of ``command`` is expected on some phones.

    ``getattr`` keeps this working until LiveCommand has an ``optional`` field.
    """
    return bool(getattr(command, "optional", False))


def print_catalog() -> None:
    """Print each catalog key with its command and purpose."""
    for c in LIVE_COMMANDS:
        needs = f"; needs SDK {c.min_sdk}+" if c.min_sdk else ""
        needs += "; optional" if is_optional(c) else ""
        print(f"{c.key:22} {c.shell}")
        print(f"{'':22} {c.purpose} (timeout {c.timeout_s} s{needs})")


def dry_run(
    commands: list[LiveCommand],
    serial: str | None,
    scale: float,
    *,
    bugreport: bool,
) -> None:
    """Print the adb invocations a real run would make."""
    target = serial or "SERIAL"
    print("adb devices -l")
    print(shlex.join(["adb", "-s", target, "shell", device_props_command()]))
    for c in commands:
        check_shell(c.shell)
        needs = f", only on SDK {c.min_sdk}+" if c.min_sdk else ""
        argv = shlex.join(["adb", "-s", target, "shell", c.shell])
        print(f"{argv}  # {c.key}: timeout {c.timeout_s * scale:g} s{needs}")
    if bugreport:
        argv = shlex.join(["adb", "-s", target, "bugreport", "WORKDIR/bugreport.zip"])
        print(f"{argv}  # timeout {BUGREPORT_TIMEOUT_S * scale:g} s")


def device_props_command() -> str:
    """Return the shell command that prints DEVICE_PROPS, one per line."""
    return "; ".join(f"getprop {prop}" for _, prop in DEVICE_PROPS)


def parse_device_props(text: str, serial: str) -> dict[str, Any]:
    """Map the output of :func:`device_props_command` to manifest fields."""
    values = text.splitlines()
    info: dict[str, Any] = {
        name: values[i].strip() if i < len(values) else ""
        for i, (name, _) in enumerate(DEVICE_PROPS)
    }
    info["sdk"] = int(info["sdk"]) if info["sdk"].isdigit() else None
    info["serial_sha256"] = serial_hash(serial)
    return info


def plug_state(battery_dump: str) -> dict[str, Any] | None:
    """Return the power sources and level from ``dumpsys battery``."""
    powered = {m[1]: m[2] == "true" for m in _POWERED_RE.finditer(battery_dump)}
    if not powered:
        return None
    level = _LEVEL_RE.search(battery_dump)
    return {
        "plugged": any(powered.values()),
        "sources": [name for name, on in powered.items() if on],
        "level_pct": int(level[1]) if level else None,
    }


def make_workdir(out: Path, model: str, now: datetime) -> Path:
    """Create ``<out>/<model>-<YYYYmmdd-HHMMSS>/live`` and return the workdir."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("._") or "android"
    base = out / f"{name}-{now:%Y%m%d-%H%M%S}"
    path, n = base, 1
    while path.exists():
        n += 1
        path = base.with_name(f"{base.name}-{n}")
    (path / "live").mkdir(parents=True)
    return path


class Collector:
    """Run the catalog against one device and keep manifest.json up to date."""

    def __init__(
        self,
        adb: str,
        serial: str,
        workdir: Path,
        manifest: dict[str, Any],
        scale: float,
    ) -> None:
        """Remember where to run and where to write."""
        self.adb = adb
        self.serial = serial
        self.workdir = workdir
        self.manifest = manifest
        self.scale = scale

    def save_manifest(self) -> None:
        """Write manifest.json; called after every command."""
        write_json(self.workdir / "manifest.json", self.manifest)

    def note_plug_state(self, battery_dump: str) -> None:
        """Record the plug state and warn when the phone is charging."""
        state = plug_state(battery_dump)
        self.manifest["plugged_at_start"] = state
        if state and state["plugged"]:
            warning = PLUGGED_WARNING.format(sources=", ".join(state["sources"]))
            self.manifest["notes"].append(warning)
            log(f"warning: {warning}")

    def run_commands(self, commands: list[LiveCommand], sdk: int | None) -> int:
        """Run and save each command; return the number that failed."""
        failed = 0
        if not any(c.key == "battery" for c in commands):
            run = run_shell(self.adb, self.serial, "dumpsys battery", DEVICE_TIMEOUT_S)
            self.note_plug_state(run.stdout.decode(errors="replace"))
        for i, c in enumerate(commands, 1):
            entry: dict[str, Any] = {"key": c.key, "command": c.shell}
            if c.min_sdk and sdk is not None and sdk < c.min_sdk:
                entry |= {
                    "status": "skipped",
                    "error": f"needs SDK {c.min_sdk}, the phone has {sdk}",
                }
            else:
                log(f"[{i}/{len(commands)}] {c.key}")
                entry |= self.run_one(c)
                if entry["status"] == "failed" and is_optional(c):
                    # Expected on some phones, e.g. a dump the shell may not read;
                    # recorded, but not counted towards exit code 3.
                    entry["optional"] = True
                    log("  (optional; the collection still counts as complete)")
                else:
                    failed += entry["status"] != "ok"
            self.manifest["commands"].append(entry)
            self.save_manifest()
        return failed

    def run_one(self, command: LiveCommand) -> dict[str, Any]:
        """Run one catalog command and save its output; return manifest fields."""
        try:
            run = run_shell(
                self.adb,
                self.serial,
                command.shell,
                command.timeout_s * self.scale,
            )
        except ValueError as exc:
            return {"status": "rejected", "error": str(exc)}
        save_output(self.workdir / "live", command.key, run)
        if command.key == "battery" and run.ok:
            self.note_plug_state(run.stdout.decode(errors="replace"))
        if not run.ok:
            log(f"  failed: {run.error}")
        return {"status": "ok" if run.ok else "failed", **run.record(self.serial)}

    def bugreport(self) -> bool:
        """Take a bugreport into the workdir; return whether it succeeded."""
        path = self.workdir / "bugreport.zip"
        log("taking a bugreport (usually 2-5 minutes)...")
        run = run_adb(
            self.adb,
            ["-s", self.serial, "bugreport", str(path)],
            BUGREPORT_TIMEOUT_S * self.scale,
        )
        valid = path.exists() and zipfile.is_zipfile(path)
        entry: dict[str, Any] = {"command": "adb bugreport", **run.record(self.serial)}
        if run.ok and not valid:
            entry["error"] = "adb finished but wrote no valid bugreport.zip"
        if path.exists() and not valid:
            # A partial zip would be picked up by analyze.py; keep it aside.
            path.rename(path.with_name("bugreport.zip.partial"))
        entry |= {
            "status": "ok" if valid else "failed",
            "file": path.name if valid else None,
            "bytes": path.stat().st_size if valid else 0,
            "note": BUGREPORT_NOTE,
        }
        self.manifest["bugreport"] = entry
        self.save_manifest()
        if not valid:
            log(f"bugreport failed: {entry['error']}")
        return valid


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(tempfile.gettempdir()) / "android-diagnostics",
        help="parent directory of the new workdir (default: %(default)s)",
    )
    parser.add_argument("--serial", help="adb serial, needed when several are attached")
    parser.add_argument(
        "--no-bugreport",
        dest="bugreport",
        action="store_false",
        help="skip the bugreport (saves 2-5 minutes; loses kernel log, PSI, HALs)",
    )
    parser.add_argument("--only", metavar="KEY[,KEY]", help="run only these keys")
    parser.add_argument("--list", action="store_true", help="print the catalog, exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the adb commands without running anything",
    )
    parser.add_argument(
        "--timeout-scale",
        type=float,
        default=1.0,
        help="multiply every timeout, for slow phones (default: 1)",
    )
    args = parser.parse_args(argv)
    if args.timeout_scale <= 0:
        parser.error("--timeout-scale must be positive")
    try:
        args.commands = select_commands(args.only)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv: list[str] | None = None) -> int:
    """Collect from the device and print the workdir path."""
    args = parse_args(argv)
    if args.list:
        print_catalog()
        return 0
    if args.dry_run:
        dry_run(
            args.commands,
            args.serial,
            args.timeout_scale,
            bugreport=args.bugreport,
        )
        return 0
    try:
        adb, device = connect(args.serial)
    except DeviceError as exc:
        log(f"error: {exc}")
        return 2
    props = run_shell(adb, device.serial, device_props_command(), DEVICE_TIMEOUT_S)
    if not props.ok:
        log(f"error: cannot read properties from {device.serial}: {props.error}")
        return 2
    info = parse_device_props(props.stdout.decode(errors="replace"), device.serial)
    model = info["model"] or device.model.replace("_", " ")
    workdir = make_workdir(args.out, model, datetime.now())
    manifest: dict[str, Any] = {
        "tool": "android-diagnostics collect",
        "started": now_iso(),
        "finished": None,
        "options": {
            "only": sorted(c.key for c in args.commands) if args.only else None,
            "bugreport": args.bugreport,
            "timeout_scale": args.timeout_scale,
        },
        "device": info,
        "plugged_at_start": None,
        "commands": [],
        "notes": [],
    }
    collector = Collector(adb, device.serial, workdir, manifest, args.timeout_scale)
    collector.save_manifest()
    log(f"collecting {len(args.commands)} dumps from {model} into {workdir}")
    failed = collector.run_commands(args.commands, info["sdk"])
    bugreport_ok = collector.bugreport() if args.bugreport else True
    manifest["finished"] = now_iso()
    collector.save_manifest()
    statuses = [c["status"] for c in manifest["commands"] if c["status"] != "skipped"]
    log(
        f"done: {statuses.count('ok')} of {len(statuses)} commands succeeded; "
        "manifest.json written",
    )
    print(workdir)
    if not bugreport_ok:
        return 4
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
