#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Sample live counters several times and report what changed in between.

Shows what the phone does right now, for example while idle with the screen
off:
- kernel TCP and UDP counters (/proc/net/snmp, /proc/net/snmp6): segments,
  resets sent (OutRsts), datagrams, multicast nobody listens to (IgnoredMulti);
- per-UID and per-interface packet counters from the netstats BPF maps
  (dumpsys netstats, Android 12 and newer);
- wakeup reasons and awake time from dumpsys batterystats --charged, which
  only advance while the phone is on battery.

Each raw sample is saved as WORKDIR/live/sample-<n>-<key>.txt. Deltas and
rates go to WORKDIR/sample-diff.json, whose path is the last stdout line.

For idle measurements unplug the phone, connect with wireless debugging
(Settings > System > Developer options > Wireless debugging), turn the screen
off and wait a few minutes for Doze before sampling. USB charging keeps the
phone out of Doze and stops the batterystats counters. The sampler itself
wakes the phone at each sample, and adb over Wi-Fi adds its own packets.

Exit codes:
  0  all samples were taken
  2  usage error, or no usable device
  3  some sample commands failed (sample-diff.json is still written)
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from androiddiag.common import PackageMap, parse_duration_ms
from androiddiag.readonly import (
    DeviceError,
    append_manifest,
    connect,
    now_iso,
    run_shell,
    save_output,
    serial_hash,
    write_json,
)
from androiddiag.storage import private_directory

if sys.version_info < (3, 11):  # ruff: ignore[outdated-version-block] - message for users of old Python
    sys.exit("sample_live.py needs Python 3.11 or newer")

# 120 s shows keepalives with periods up to about a minute several times over;
# the original diagnosis used the same interval.
DEFAULT_INTERVAL_S = 120.0
# Below a minute, a handful of events decides the rate; say so in the output.
SHORT_INTERVAL_S = 60.0
COMMAND_TIMEOUT_S = 60.0
# A difference needs two samples.
MIN_SAMPLES = 2
# Keep the most active rows of each table; the cap is noted in the output.
TABLE_CAP = 25

# Read-only commands run at every sample. They are fixed strings with pipes,
# so like collect.py's catalog they pass only the deny-list check.
SAMPLE_COMMANDS: tuple[tuple[str, str], ...] = (
    (
        "state",
        (
            "cat /proc/uptime; date +%s; dumpsys power | grep -E "
            "'mWakefulness=|mIsPowered=|mPlugType=|mBatteryLevel=|"
            "mDeviceIdleMode=|mLightDeviceIdleMode='"
        ),
    ),
    ("snmp", "cat /proc/net/snmp"),
    ("snmp6", "cat /proc/net/snmp6"),
    (
        "netstats",
        (
            "dumpsys netstats | sed -n "
            "'/mAppUidStatsMap:/,/mStatsMapA:/p;/mIfaceStatsMap:/,/^$/p'"
        ),
    ),
    (
        "charged",
        "dumpsys batterystats --charged | grep -E 'Time on battery|Wakeup reason '",
    ),
)

# /proc/net/snmp fields that are settings or current values, not counters.
SNMP_GAUGES = frozenset(
    {"Tcp.RtoAlgorithm", "Tcp.RtoMin", "Tcp.RtoMax", "Tcp.MaxConn", "Tcp.CurrEstab"},
)
SNMP_REPORTED = ("Tcp.", "Udp.", "Udp6")
# Counters copied into the flat "metrics" of each comparison.
HEADLINE_SNMP = (
    "Tcp.OutRsts",
    "Tcp.InSegs",
    "Tcp.OutSegs",
    "Tcp.RetransSegs",
    "Udp.InDatagrams",
    "Udp.OutDatagrams",
    "Udp.NoPorts",
    "Udp.IgnoredMulti",
)
HEADLINE_WAKEUPS = (
    "awake_share_pct",
    "screen_off_awake_share_pct",
    "wakeups_per_h",
    "suspend_aborts_per_h",
)

_UPTIME_RE = re.compile(r"^(\d+(?:\.\d+)?) \d+(?:\.\d+)?$")
_EPOCH_RE = re.compile(r"^\d{9,11}$")
_POWER_FIELD_RE = re.compile(r"^(m\w+)=(\S+)$")
_STATE_FIELDS = {
    "mWakefulness": "wakefulness",
    "mIsPowered": "is_powered",
    "mPlugType": "plug_type",
    "mBatteryLevel": "battery_level_pct",
    "mDeviceIdleMode": "device_idle",
    "mLightDeviceIdleMode": "light_device_idle",
}
_SNMP6_RE = re.compile(r"^(\w+)\s+(-?\d+)$")
_UID_HEADER = "uid rxBytes rxPackets txBytes txPackets"
_IFACE_HEADER = "ifaceIndex ifaceName rxBytes rxPackets txBytes txPackets"
# Negative UIDs are netstats pseudo-UIDs (for example removed or tethering).
_UID_ROW_RE = re.compile(r"^(-?\d+) (\d+) (\d+) (\d+) (\d+)$")
_IFACE_ROW_RE = re.compile(r"^\d+ (\S+) (\d+) (\d+) (\d+) (\d+)$")
_ON_BATTERY_RE = re.compile(
    r"^\s*Time on battery(?P<screen_off> screen off)?: (?P<real>[^(]+?) \([^)]*\) "
    r"realtime, (?P<up>[^(]+?) \([^)]*\) uptime",
)
_DURATION = r"\d+(?:ms|[dhms])(?: \d+(?:ms|[dhms]))*"
_WAKEUP_RE = re.compile(
    rf"^\s*Wakeup reason (?P<reason>.*?)"
    rf"(?:: (?P<time>{_DURATION}) \((?P<count>\d+) times\))? realtime\s*$",
)

USB_WARNING = (
    "The phone was on external power during sampling. Charging keeps it out "
    "of Doze and stops the batterystats counters, so these rates do not "
    "describe idle use on battery. Unplug, connect with wireless debugging "
    "and sample again with the screen off."
)
AWAKE_WARNING = (
    "The screen was on (wakefulness Awake) in at least one sample; the rates "
    "describe interactive use, not standby."
)
SAMPLER_NOTE = (
    "The sampler's own commands wake the phone at each sample, and adb over "
    "Wi-Fi adds packets (adbd runs as UID 2000, shell). Rates come from one "
    "short window and must not be extrapolated to hours without saying so."
)


def log(message: str) -> None:
    """Print a progress or warning line on stderr."""
    print(message, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- parsers


def _convert(value: str) -> bool | int | str:
    if value in {"true", "false"}:
        return value == "true"
    return int(value) if value.lstrip("-").isdigit() else value


def parse_state(text: str) -> dict[str, Any]:
    """Parse /proc/uptime, ``date +%s`` and the selected ``dumpsys power`` lines."""
    state: dict[str, Any] = {}
    for line in text.splitlines():
        s = line.strip()
        if m := _UPTIME_RE.match(s):
            state.setdefault("uptime_s", float(m[1]))
        elif _EPOCH_RE.match(s):
            state.setdefault("epoch_s", int(s))
        elif (m := _POWER_FIELD_RE.match(s)) and m[1] in _STATE_FIELDS:
            state.setdefault(_STATE_FIELDS[m[1]], _convert(m[2]))
    return state


def parse_snmp(text: str) -> dict[str, int]:
    """Return ``{"Tcp.OutRsts": n, ...}`` from header/value line pairs."""
    counters: dict[str, int] = {}
    header: tuple[str, list[str]] | None = None
    for line in text.splitlines():
        proto, _, rest = line.partition(":")
        fields = rest.split()
        numeric = all(f.lstrip("-").isdigit() for f in fields)
        if header and header[0] == proto and numeric and len(fields) == len(header[1]):
            names = header[1]
            counters.update(
                {f"{proto}.{n}": int(v) for n, v in zip(names, fields, strict=True)},
            )
            header = None
        elif fields and not numeric:
            header = (proto, fields)
    return counters


def parse_snmp6(text: str) -> dict[str, int]:
    """Return ``{"Udp6InDatagrams": n, ...}`` from /proc/net/snmp6."""
    matches = (_SNMP6_RE.match(line.strip()) for line in text.splitlines())
    return {m[1]: int(m[2]) for m in matches if m}


Traffic = tuple[int, int, int, int]  # rx bytes, rx packets, tx bytes, tx packets


@dataclass
class NetstatsMaps:
    """Cumulative packet counters per UID and per interface."""

    uids: dict[int, Traffic] = field(default_factory=dict)
    ifaces: dict[str, Traffic] = field(default_factory=dict)
    skipped: int = 0  # rows inside a table that did not parse


def parse_netstats(text: str) -> NetstatsMaps:
    """Parse the ``mAppUidStatsMap`` and ``mIfaceStatsMap`` BPF map dumps."""
    maps = NetstatsMaps()
    table = ""
    for line in text.splitlines():
        s = " ".join(line.split())
        if s in {_UID_HEADER, _IFACE_HEADER}:
            table = "uid" if s == _UID_HEADER else "iface"
        elif not s or s.endswith(":"):
            table = ""
        elif table == "uid" and (m := _UID_ROW_RE.match(s)):
            uid, rxb, rxp, txb, txp = map(int, m.groups())
            maps.uids[uid] = (rxb, rxp, txb, txp)
        elif table == "iface" and (m := _IFACE_ROW_RE.match(s)):
            # Several interface indexes can share a name; add them up.
            rxb, rxp, txb, txp = map(int, m.groups()[1:])
            old = maps.ifaces.get(m[1], (0, 0, 0, 0))
            maps.ifaces[m[1]] = (old[0] + rxb, old[1] + rxp, old[2] + txb, old[3] + txp)
        elif table:
            maps.skipped += 1
    return maps


def parse_charged(text: str) -> dict[str, Any]:
    """Parse time on battery (realtime and awake) and the wakeup reason counts."""
    out: dict[str, Any] = {"wakeup_reasons": {}}
    for line in text.splitlines():
        if m := _ON_BATTERY_RE.match(line):
            prefix = "screen_off" if m["screen_off"] else "on_battery"
            out.setdefault(f"{prefix}_realtime_ms", parse_duration_ms(m["real"]))
            out.setdefault(f"{prefix}_uptime_ms", parse_duration_ms(m["up"]))
        elif m := _WAKEUP_RE.match(line):
            time_ms = parse_duration_ms(m["time"]) if m["time"] else 0
            out["wakeup_reasons"][m["reason"]] = (int(m["count"] or 0), time_ms)
    return out


# ---------------------------------------------------------------- samples


@dataclass
class Sample:
    """The raw outputs of one round of SAMPLE_COMMANDS."""

    number: int
    taken_at: str
    host_start: float  # host monotonic clock when the sample started
    texts: dict[str, str] = field(default_factory=dict)
    commands: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def state(self) -> dict[str, Any]:
        """The parsed power state of this sample."""
        return parse_state(self.texts.get("state", ""))


def take_sample(adb: str, serial: str, number: int, live: Path) -> Sample:
    """Run every sample command once and save the raw outputs."""
    sample = Sample(number, now_iso(), time.monotonic())
    for key, command in SAMPLE_COMMANDS:
        run = run_shell(adb, serial, command, COMMAND_TIMEOUT_S)
        save_output(live, f"sample-{number}-{key}", run)
        sample.texts[key] = run.stdout.decode(errors="replace")
        status = "ok" if run.ok else "failed"
        sample.commands[key] = {"status": status, **run.record(serial)}
        if not run.ok:
            log(f"  sample {number} {key} failed: {run.error}")
    return sample


def elapsed(a: Sample, b: Sample) -> tuple[float, str]:
    """Return the seconds between two samples and the clock they come from.

    The phone's /proc/uptime counts time in suspend too, like the original
    diagnosis; the host clock is the fallback. Every command of a sample runs
    at the same offset from its start, so one interval serves all counters.
    """
    up_a, up_b = a.state.get("uptime_s"), b.state.get("uptime_s")
    if up_a is not None and up_b is not None and up_b > up_a:
        return up_b - up_a, "phone /proc/uptime"
    return b.host_start - a.host_start, "host clock"


def _rate(delta: float, seconds: float, per: float) -> float | None:
    return round(delta / seconds * per, 3) if seconds else None


def diff_snmp(
    a: Sample,
    b: Sample,
    seconds: float,
    notes: list[str],
) -> dict[str, Any]:
    """Return TCP/UDP counter deltas and per-minute rates."""
    counters: dict[str, Any] = {}
    gauges: dict[str, Any] = {}
    for key, parser in (("snmp", parse_snmp), ("snmp6", parse_snmp6)):
        start, end = parser(a.texts.get(key, "")), parser(b.texts.get(key, ""))
        for name in start:
            if not name.startswith(SNMP_REPORTED) or name not in end:
                continue
            if name in SNMP_GAUGES:
                gauges[name] = {"start": start[name], "end": end[name]}
                continue
            delta = end[name] - start[name]
            if delta < 0:
                notes.append(f"{name} went down; the counters were reset (reboot?)")
            counters[name] = {
                "start": start[name],
                "end": end[name],
                "delta": delta,
                "per_min": _rate(delta, seconds, 60),
            }
    return {"counters": counters, "gauges": gauges}


def _traffic_rows(
    start: dict[Any, Traffic],
    end: dict[Any, Traffic],
    seconds: float,
    label: str,
    notes: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, after in end.items():
        # A UID missing from the first sample had sent nothing since boot.
        before = start.get(key, (0, 0, 0, 0))
        rxb, rxp, txb, txp = (x - y for x, y in zip(after, before, strict=True))
        if min(rxb, rxp, txb, txp) < 0:
            notes.append(f"{label} {key}: counters went down; row skipped")
            continue
        if rxp or txp:
            rows.append(
                {
                    label: key,
                    "rx_packets": rxp,
                    "tx_packets": txp,
                    "rx_bytes": rxb,
                    "tx_bytes": txb,
                    "packets_per_min": _rate(rxp + txp, seconds, 60),
                    "rx_period_s": round(seconds / rxp, 1) if seconds and rxp else None,
                    "rx_bytes_per_packet": round(rxb / rxp) if rxp else None,
                }
            )
    rows.sort(key=lambda r: int(r["rx_packets"]) + int(r["tx_packets"]), reverse=True)
    if len(rows) > TABLE_CAP:
        notes.append(f"{label} table: kept the {TABLE_CAP} busiest of {len(rows)} rows")
    return rows[:TABLE_CAP]


def diff_traffic(
    a: Sample,
    b: Sample,
    seconds: float,
    packages: PackageMap,
    notes: list[str],
) -> dict[str, Any]:
    """Return per-UID and per-interface packet deltas."""
    start = parse_netstats(a.texts.get("netstats", ""))
    end = parse_netstats(b.texts.get("netstats", ""))
    if not end.uids and not end.ifaces:
        notes.append(
            "No netstats BPF map rows (mAppUidStatsMap) found; they exist on "
            "Android 12 and newer.",
        )
    if start.skipped or end.skipped:
        notes.append(
            f"netstats: skipped {start.skipped + end.skipped} unparsable table rows",
        )
    uid_rows = _traffic_rows(start.uids, end.uids, seconds, "uid", notes)
    for row in uid_rows:
        uid = row["uid"]
        row["name"] = f"pseudo-UID {uid}" if uid < 0 else packages.name(uid)
    return {
        "uids": uid_rows,
        "interfaces": _traffic_rows(
            start.ifaces, end.ifaces, seconds, "interface", notes
        ),
    }


def diff_wakeups(a: Sample, b: Sample, notes: list[str]) -> dict[str, Any]:
    """Return wakeup reason deltas and the awake share while on battery."""
    start = parse_charged(a.texts.get("charged", ""))
    end = parse_charged(b.texts.get("charged", ""))
    if "on_battery_realtime_ms" not in start or "on_battery_realtime_ms" not in end:
        notes.append("batterystats --charged had no 'Time on battery'; no wakeups.")
        return {}
    real_ms = end["on_battery_realtime_ms"] - start["on_battery_realtime_ms"]
    up_ms = end["on_battery_uptime_ms"] - start["on_battery_uptime_ms"]
    if real_ms < 0:
        notes.append("batterystats was reset between samples (charged and unplugged).")
        return {}
    if real_ms == 0:
        notes.append(
            "Time on battery did not advance: the phone was on external power, "
            "which stops the since-charge counters.",
        )
        return {"on_battery_s": 0.0}
    off_real = _delta(start, end, "screen_off_realtime_ms")
    off_up = _delta(start, end, "screen_off_uptime_ms")
    hours = real_ms / 3_600_000
    rows: list[dict[str, Any]] = []
    totals = {"wakeup": 0, "abort": 0}
    for reason, (count, time_ms) in end["wakeup_reasons"].items():
        count_0, time_0 = start["wakeup_reasons"].get(reason, (0, 0))
        if count > count_0:
            # Kernel suspend aborts are listed as "Abort: ..."; the rest are
            # resumes from suspend with the waking IRQ.
            kind = "abort" if reason.startswith("Abort") else "wakeup"
            totals[kind] += count - count_0
            rows.append(
                {
                    "reason": reason,
                    "kind": kind,
                    "count": count - count_0,
                    "per_h": round((count - count_0) / hours, 1),
                    "time_s": round((time_ms - time_0) / 1000, 1),
                }
            )
    rows.sort(key=lambda r: int(r["count"]), reverse=True)
    if len(rows) > TABLE_CAP:
        notes.append(
            f"wakeup reasons: kept the {TABLE_CAP} most frequent of {len(rows)}"
        )
    return {
        "on_battery_s": round(real_ms / 1000, 1),
        "awake_share_pct": round(100 * up_ms / real_ms, 1),
        "screen_off_s": round(off_real / 1000, 1),
        "screen_off_awake_share_pct": (
            round(100 * off_up / off_real, 1) if off_real > 0 else None
        ),
        "wakeups_per_h": round(totals["wakeup"] / hours, 1),
        "suspend_aborts_per_h": round(totals["abort"] / hours, 1),
        "reasons": rows[:TABLE_CAP],
    }


def _delta(start: dict[str, Any], end: dict[str, Any], key: str) -> int:
    return int(end.get(key, 0)) - int(start.get(key, 0))


def diff_samples(a: Sample, b: Sample, packages: PackageMap) -> dict[str, Any]:
    """Compare two samples: counters, rates and the power state at each end."""
    notes: list[str] = []
    seconds, clock = elapsed(a, b)
    snmp = diff_snmp(a, b, seconds, notes)
    wakeups = diff_wakeups(a, b, notes)
    counters = snmp["counters"]
    metrics: dict[str, Any] = {"interval_s": round(seconds, 1)}
    for name in HEADLINE_SNMP:
        if name in counters:
            key = f"{name.replace('.', '_').lower()}_per_min"
            metrics[key] = counters[name]["per_min"]
    metrics |= {name: wakeups[name] for name in HEADLINE_WAKEUPS if name in wakeups}
    return {
        "from_sample": a.number,
        "to_sample": b.number,
        "from_time": a.taken_at,
        "to_time": b.taken_at,
        "interval_clock": clock,
        "state": {"start": a.state, "end": b.state},
        "metrics": metrics,
        "snmp": snmp,
        "traffic": diff_traffic(a, b, seconds, packages, notes),
        "wakeups": wakeups,
        "notes": notes,
    }


def warnings_for(samples: list[Sample]) -> list[str]:
    """Return the conditions that make the measurement unrepresentative."""
    states = [s.state for s in samples]
    seconds, _ = elapsed(samples[0], samples[-1])
    interval = seconds / (len(samples) - 1)
    warnings = []
    if any(st.get("is_powered") for st in states):
        warnings.append(USB_WARNING)
    if any(st.get("wakefulness") == "Awake" for st in states):
        warnings.append(AWAKE_WARNING)
    if interval < SHORT_INTERVAL_S:
        warnings.append(
            f"Samples were {interval:.0f} s apart; with so few events per window "
            "the rates are noisy.",
        )
    return warnings


def load_packages(adb: str, serial: str, live: Path) -> PackageMap:
    """Read the UID-to-package map from the workdir, fetching it if missing."""
    path = live / "packages_uid.txt"
    if not path.exists():
        run = run_shell(adb, serial, "cmd package list packages -U", COMMAND_TIMEOUT_S)
        if run.ok:
            save_output(live, "packages_uid", run)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return PackageMap.from_pm_list(text)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workdir", type=Path, required=True, help="where to save")
    parser.add_argument("--serial", help="adb serial, needed when several are attached")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_S,
        help="seconds between sample starts (default: %(default)g)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=2,
        help="number of samples, at least 2 (default: %(default)s)",
    )
    parser.add_argument("--force", action="store_true", help="overwrite a previous run")
    args = parser.parse_args(argv)
    if args.samples < MIN_SAMPLES:
        parser.error(f"--samples must be at least {MIN_SAMPLES}")
    if args.interval < 0:
        parser.error("--interval must not be negative")
    if (args.workdir / "sample-diff.json").exists() and not args.force:
        parser.error(f"{args.workdir} already has sample-diff.json; use --force")
    return args


def main(argv: list[str] | None = None) -> int:
    """Take the samples, write sample-diff.json and print its path."""
    args = parse_args(argv)
    try:
        private_directory(args.workdir)
        private_directory(args.workdir / "live")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        adb, device = connect(args.serial)
    except DeviceError as exc:
        log(f"error: {exc}")
        return 2
    live = args.workdir / "live"
    started = now_iso()
    packages = load_packages(adb, device.serial, live)
    samples: list[Sample] = []
    next_start = time.monotonic()
    for number in range(1, args.samples + 1):
        wait = next_start - time.monotonic()
        if wait > 0:
            log(f"waiting {wait:.0f} s for sample {number}")
            time.sleep(wait)
        next_start = time.monotonic() + args.interval
        log(f"sample {number} of {args.samples}")
        samples.append(take_sample(adb, device.serial, number, live))
        if number == 1 and samples[0].state.get("is_powered"):
            log(f"warning: {USB_WARNING}")
    report: dict[str, Any] = {
        "tool": "android-diagnostics sample_live",
        "started": started,
        "finished": now_iso(),
        "device": {"serial_sha256": serial_hash(device.serial)},
        "requested_interval_s": args.interval,
        "samples": [
            {
                "number": s.number,
                "taken_at": s.taken_at,
                "state": s.state,
                "commands": s.commands,
            }
            for s in samples
        ],
        "warnings": warnings_for(samples),
        "notes": [SAMPLER_NOTE],
        "overall": diff_samples(samples[0], samples[-1], packages),
    }
    if len(samples) > MIN_SAMPLES:  # with two samples, "overall" is the only interval
        report["intervals"] = [
            diff_samples(x, y, packages) for x, y in itertools.pairwise(samples)
        ]
    out = args.workdir / "sample-diff.json"
    write_json(out, report)
    failed = sum(c["status"] != "ok" for s in samples for c in s.commands.values())
    append_manifest(
        args.workdir,
        "samples",
        {
            "tool": "sample_live",
            "started": started,
            "finished": report["finished"],
            "samples": len(samples),
            "failed_commands": failed,
            "file": out.name,
        },
    )
    for warning in report["warnings"]:
        log(f"warning: {warning}")
    print(out)
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
