"""CPU time: who burns it since boot, on battery, with the screen off, and now.

Every input covers its own window, and the analyzers here never add numbers
from different windows together:

- ``ps`` TIME is CPU since each process started (``since_boot`` for daemons).
- batterystats ``Proc`` lines and per-UID CPU cover time on battery since the
  last full charge (``on_battery``).
- ``top`` and ``dumpsys cpuinfo`` are samples of seconds to a minute around
  the capture (``snapshot``); the phone may have been charging by then.
- The event log's ``am_cpu`` rows cover the part of the battery time that the
  log buffer kept (``log_coverage``).
- The bugreport's per-thread ``ps -T`` TIME is CPU since each thread started.

CPU seconds are measured by the kernel. Any mAh value derived from them is the
batterystats power model split by CPU share, labelled ``modelled``.

Shares of a core and per-hour rates need a long enough window: below
``MIN_ON_BATTERY_S`` on battery or ``MIN_SCREEN_OFF_S`` with the screen off
they are not computed.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .batterystats import load_since_charge, parse_since_charge
from .common import (
    EventLog,
    fmt_duration,
    format_uid,
    iter_logcat,
    load_event_log,
    load_ps,
    parse_clock_s,
    parse_decimal,
    parse_duration_ms,
    parse_ps,
    pct,
    ps_cpu_by_name,
    uid_class,
)
from .model import (
    TABLE_CAP,
    Context,
    Evidence,
    Finding,
    Result,
    Severity,
    SkipError,
    analyzer,
    link,
)
from .source import Text

if TYPE_CHECKING:
    from .batterystats import ProcCpu, SinceCharge, UidPower
    from .common import PsRow, Transition
    from .model import Windows

Row = dict[str, Any]

# Shares of a core or per-hour rates over shorter windows are noise, for
# example right after an unplug; they are not computed.
MIN_ON_BATTERY_S = 15 * 60
MIN_SCREEN_OFF_S = 10 * 60

# A boot-time daemon gets one of the first few thousand PIDs (system_server is
# usually below 2500). A daemon restarted hours later gets a PID from the
# current allocation frontier, far above this. After PID wrap-around a restart
# can land low again, so a clean check is not proof.
BOOT_PID_MAX = 4000

# Daemons that start once per boot; a high PID means a crash or a kill.
CORE_DAEMONS = (
    "system_server",
    "surfaceflinger",
    "lmkd",
    "ueventd",
    "logd",
    "servicemanager",
    "hwservicemanager",
    "vold",
    "netd",
    "statsd",
    "zygote64",
    "android.system.suspend-service",
)

# A native daemon averaging more than this share of one core since boot is
# busy for a process that should idle once boot is over (reference data:
# ueventd 1.3% and the suspend service 2.5%, both driven by a resume loop).
BUSY_DAEMON_CORE_PCT = 1.0

# Processes whose CPU follows screen use or media; high values are normal.
EXPECTED_BUSY_RE = re.compile(
    r"^(?:system|system_server|surfaceflinger|com\.android\.systemui|"
    r".*composer.*|.*graphics.*|.*display.*|.*audio.*|.*camera.*|media.*|"
    r".*codec.*|adbd|dumpstate|top|logcat|ps|sh)$",
)

# Commands that the collection itself runs; they inflate their own samples.
COLLECTION_TOOLS = frozenset(
    {"top", "dumpstate", "bugreportz", "logcat", "ps", "dumpsys", "incidentd", "sh"},
)

# A user-space daemon averaging at least this share of one core over the
# whole time on battery is a measurable standby cost. The severity steps are
# the shares of the reference phone's three cases: the suspend service (8.8%,
# a confirmed high finding), ueventd (4.4%, rated medium by the verifier) and
# a vendor log daemon (2.9%, medium).
CHURN_MIN_CORE_PCT = 1.0
CHURN_HIGH_CORE_PCT = 5.0
CHURN_MEDIUM_CORE_PCT = 2.0
CHURN_MAX_FINDINGS = 6

# At least this share of a process's since-boot CPU falling on battery means
# the load belongs to the battery period (Doze, suspend), not to normal use.
BATTERY_SPECIFIC_SHARE_PCT = 90.0
# On-battery CPU may exceed since-boot TIME by this much from capture skew.
SHARE_SLACK_PCT = 105.0

# A service whose CPU is more than this share kernel time is executing a
# kernel path (suspend/resume, I/O) in its own thread, not looping in code.
KERNEL_HEAVY_PCT = 95.0

# Screen-off CPU of all UIDs above this many seconds per hour (10% of one core
# averaged over screen-off time) is far from an idle phone, which spends
# nearly all screen-off time suspended.
SCREEN_OFF_CPU_HIGH_S_PER_H = 360.0

# Core UIDs (kernel, system, radio...) above this share of screen-off CPU mean
# apps are at most triggers; look at the kernel and system processes.
CORE_SHARE_HIGH_PCT = 80.0

# An app above this many seconds of screen-off CPU per hour is busy in the
# background (reference: the busiest app on the reference phone, 32 s/h).
APP_SCREEN_OFF_S_PER_H = 30.0

# A UID spending this share of its CPU at the highest frequency step of the
# fastest cluster (with at least TOP_STEP_MIN_CPU_S of CPU) runs hot work that
# costs more energy per second; it is listed for the app analysis.
TOP_STEP_HEAVY_PCT = 40.0
TOP_STEP_MIN_CPU_S = 60.0

# top: idle below half of the total capacity in two samples means saturation;
# iowait above 10% of the total capacity means the CPU waits on storage.
TOP_IDLE_SATURATED_PCT = 50.0
TOP_IOWAIT_PCT = 10.0
# The same non-UI process above this per-core % in every sample is a hog.
TOP_HOG_CPU_PCT = 25.0
TOP_MIN_SAMPLES = 2

# cpuinfo: more major faults per second than this means pages are being read
# back from storage constantly (refault thrash), which shows as stutter.
MAJOR_FAULTS_PER_S = 20.0
# A system daemon above this per-core % in the last tracker window is busy.
CPUINFO_DAEMON_PCT = 5.0
# TOTAL below this % of all cores with a 1-minute load below 1: not saturated.
CPUINFO_IDLE_TOTAL_PCT = 20.0
CPUINFO_IDLE_LOAD = 1.0
# The window may end this long after the plug-in time and still count as on
# battery: the two times come from different clocks.
CPUINFO_PLUG_SLACK = timedelta(seconds=1)
# Wall-clock stamps further than this from the window's uptime span (scaled by
# the awake share) straddle a clock change, as when the clock is set after boot.
CPUINFO_CLOCK_SLACK_S = 5.0

# am_cpu: two processes whose per-interval CPU correlates at least this well
# share a trigger; pairs are only tested among the busiest processes.
COUPLED_MIN_R = 0.9
COUPLED_TOP_PROCESSES = 12
COUPLED_MIN_BATCHES = 4
# Screen state of a batch: share of its wall-clock span with the screen on.
SCREEN_ON_MIN_FRACTION = 0.9
SCREEN_OFF_MAX_FRACTION = 0.1
# Below this % of awake time a process (or the suspend service) is idle.
IDLE_PCT = 1.0
# am_cpu names are the last 15 characters; shorter suffixes match too loosely.
MIN_SUFFIX_MATCH = 8

# thread_cpu: a thread holding this share of a process's CPU is the code path.
DOMINANT_THREAD_PCT = 80.0
DOMINANT_THREAD_MIN_CPU_S = 60.0

# Linux keeps the first 15 characters of a thread (and main-thread) name.
_COMM_LEN = 15

_PCT = 100.0
_S_PER_H = 3600.0
_MS = 1000.0

# Android 10-11 indent 'Screen-off cpu times per freq at state X' by three
# spaces inside a UID block.
_THREE_SPACES_RE = re.compile(r"^   (?=\S)", re.MULTILINE)
_TOTAL_CPU_RE = re.compile(r"^    Total cpu time: u=(.+?) s=(.+?)\s*$")
_FREQ_RE = re.compile(r"^    Total (screen-off )?cpu time per freq:(.*)$")
_KILLED_RE = re.compile(
    r"^      \* Killed for (\w+) use: (\S+) over (\S+)(?: \((\d+)%\))?",
)

_APP_USER_RE = re.compile(r"^u\d+_[ai]\d+$")
_PER_CPU_THREAD_RE = re.compile(
    r"^(migration|cpuhp|ksoftirqd|rcuop|rcuos|rcuog|rcuc|watchdog|idle_inject)/\d+$",
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_TOP_SAMPLE_RE = re.compile(r"^\s*(?:Tasks|Threads):")
_TOP_SUMMARY_RE = re.compile(r"(\d+)%(cpu|user|nice|sys|idle|iow|irq|sirq|host)\b")

_LOAD_RE = re.compile(r"^Load: ([\d.,]+) / ([\d.,]+) / ([\d.,]+)")
_STAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?"
_CPUINFO_WINDOW_RE = re.compile(
    rf"CPU usage from (-?\d+)ms to (-?\d+)ms ago \(({_STAMP}) to ({_STAMP})\)"
    r"(?: with ([\d.,]+)% awake)?",
)
_CPUINFO_ROW_RE = re.compile(r"^\s*[+-]?([\d.,]+)% (\d+)/(.+?): (-?[\d.,]+% user.*)$")
_CPUINFO_TOTAL_RE = re.compile(r"^\s*([\d.,]+)% TOTAL: (.*)$")
_CPUINFO_PART_RE = re.compile(r"(-?[\d.,]+)% (user|kernel|iowait|irq|softirq)")
_FAULTS_RE = re.compile(r"(\d+) (minor|major)")

_AM_CPU_RE = re.compile(r"^\[(\d+),(-?\d+),(.*),(\d+),(\d+),(\d+)\]\s*$")


# ----------------------------------------------------------------------------
# Small shared helpers (logs.py uses some of them too)


def kernel_group(name: str) -> str:
    """Group per-CPU kernel threads and kworkers so they rank as one consumer.

    ``kworker/u16:3-events_unbound`` becomes ``kworker:events_unbound``,
    ``kworker/1:2`` becomes ``kworker:(none)`` and ``migration/3`` becomes
    ``migration/*``. Other names are returned without brackets.
    """
    bare = name.strip("[]")
    if bare.startswith("kworker/"):
        return "kworker:" + (bare.split("-", 1)[1] if "-" in bare else "(none)")
    if m := _PER_CPU_THREAD_RE.match(bare):
        return f"{m[1]}/*"
    return bare


def slug(text: str) -> str:
    """Return a finding-id-safe slug of ``text``."""
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:48] or "x"


def result_table(ctx: Context, analyzer_name: str, table: str) -> list[Row]:
    """Return a table of an earlier analyzer, or an empty list."""
    found = ctx.results.get(analyzer_name)
    if found is None or found.status != "ok":
        return []
    return found.tables.get(table, [])


def charging_since(w: Windows) -> datetime | None:
    """Return the plug-in time when the phone was charging at capture.

    A plug-in time after the capture comes from a broken history clock and
    is ignored.
    """
    plug = w.plugged_at if w.on_battery_at_capture is False else None
    if plug is None or (w.dump_time is not None and plug > w.dump_time):
        return None
    return plug


def power_state(w: Windows, start: datetime, end: datetime | None = None) -> str:
    """Say whether the moment ``start`` (or ``start..end``) was on battery.

    Returns ``on_battery`` inside the stretch from the last full charge to the
    plug-in (or to the capture when the phone was unplugged), ``charging``
    after that plug-in, ``mixed`` across either edge and ``unknown`` before
    the last full charge or when the plug state at capture is unknown.
    """
    end = end or start
    charging = w.on_battery_at_capture is False
    stop = charging_since(w) if charging else w.dump_time
    if w.on_battery_at_capture is None or stop is None:
        return "unknown"
    if charging and start >= stop:
        return "charging"
    first = w.since_charge_start
    if first is not None and first <= start and end <= stop:
        return "on_battery"
    if start < stop < end or (first is not None and start < first < end):
        return "mixed"
    return "unknown"


def plug_note(w: Windows) -> str | None:
    """Return a note with the plug-in time when the phone charged at capture."""
    if (plug := charging_since(w)) is None:
        return None
    return (
        f"Plug-in time ({w.plugged_at_source or 'windows'}): {plug:%Y-%m-%d %H:%M:%S}."
    )


def _command(name: str) -> str:
    """Return the first word of a command line, the program."""
    return name.split(maxsplit=1)[0]


def _base(name: str) -> str:
    """Return a process name without kernel-thread brackets or its directory."""
    bare = name.strip("[]")
    return bare.rsplit("/", 1)[-1] if bare.startswith("/") else bare


def _churn_reported(ctx: Context) -> dict[str, str]:
    """Return ``{process: finding id}`` for daemons system_process_cpu_churn reported.

    That analyzer owns the 'busy system daemon' fact; others list only the
    daemons it did not report.
    """
    found = ctx.results.get("system_process_cpu_churn")
    if found is None:
        return {}
    ids = {f.id for f in found.findings}
    return {
        _base(row["process"]): fid
        for row in found.tables.get("processes", [])
        if (fid := f"system_process_cpu_churn.{slug(row['process'])}") in ids
    }


# ----------------------------------------------------------------------------
# ps: CPU since process start


def _ps_evidence(row: PsRow) -> Evidence:
    return Evidence(row.ref, " ".join(row.line.split()))


def _unparsed(text: Text, rows: list[PsRow]) -> int:
    """Count non-blank lines after the first parsed row that did not parse."""
    parsed = {r.index for r in rows}
    first = min(parsed, default=len(text.lines))
    return sum(
        1
        for i in range(first, len(text.lines))
        if i not in parsed and text.lines[i].strip()
    )


def _process_names(ctx: Context) -> dict[int, str]:
    """Return ``pid -> name`` from ps, or from the main threads of the thread list."""
    return {r.pid: r.name for r in load_ps(ctx) if r.tid is None or r.tid == r.pid}


def _is_app_user(user: str) -> bool:
    return bool(_APP_USER_RE.match(user))


def _busy_daemon(row: PsRow, share: float | None) -> bool:
    return bool(
        share is not None
        and share >= BUSY_DAEMON_CORE_PCT
        and not _is_app_user(row.user)
        and not EXPECTED_BUSY_RE.match(row.name)
        and row.name not in COLLECTION_TOOLS,
    )


def _kernel_groups(rows: list[PsRow]) -> list[Row]:
    groups: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        if row.name.startswith("["):
            group = groups[kernel_group(row.name)]
            group[0] += row.cpu_s
            group[1] += 1
    return [
        {"group": g, "threads": int(n), "cpu_s": round(s, 1)}
        for g, (s, n) in sorted(groups.items(), key=lambda kv: -kv[1][0])
    ]


def _core_daemons(rows: list[PsRow]) -> tuple[list[Row], list[PsRow]]:
    newest = {r.name: r for r in sorted(rows, key=lambda r: r.pid)}
    table: list[Row] = []
    restarted = []
    for name in CORE_DAEMONS:
        if (row := newest.get(name)) is None:
            continue
        flag = row.pid > BOOT_PID_MAX
        table.append(
            {"process": name, "pid": row.pid, "restarted": flag, "ref": row.ref}
        )
        if flag:
            restarted.append(row)
    return table, restarted


def _restart_finding(restarted: list[PsRow]) -> Finding:
    names = ", ".join(f"{r.name} (PID {r.pid})" for r in restarted)
    return Finding(
        id="process_cpu_since_boot.core-daemon-restarted",
        title="Core system daemons restarted since boot",
        symptom="both",
        severity="high",
        basis="inferred",
        window="since_boot",
        summary=(
            f"{names} have PIDs above {BOOT_PID_MAX}, so they started long "
            "after boot: they crashed or were killed and restarted."
        ),
        metrics={"restarted": [r.name for r in restarted]},
        evidence=[_ps_evidence(r) for r in restarted],
        recommendation=(
            "Look for the crash in the dropbox (system_server_crash, "
            "SYSTEM_TOMBSTONE) and the tombstones. A restarting core daemon "
            "is a firmware bug: check Settings > System > System update and "
            "report it to the vendor."
        ),
        followups=[
            (
                "An hour later, run `adb_ro.py --save ps_later --workdir WORKDIR "
                "-- ps -A -o PID,TIME,NAME` and grep WORKDIR/live/ps_later.txt "
                "for the daemon: a new PID means it restarted again."
            ),
            (
                "Run `adb_ro.py --save logcat_crash --workdir WORKDIR -- logcat "
                "-d -b crash` and grep WORKDIR/live/logcat_crash.txt for the "
                "daemon's native crash."
            ),
        ],
    )


def _busy_finding(busy: list[tuple[PsRow, float]], related: list[str]) -> Finding:
    listed = ", ".join(f"{r.name} {share:.1f}%" for r, share in busy[:6])
    elsewhere = (
        f" {len(related)} more are reported with their CPU on battery "
        "(system_process_cpu_churn)."
        if related
        else ""
    )
    return Finding(
        id="process_cpu_since_boot.busy-daemons",
        title="Native daemons busy since boot",
        symptom="battery",
        severity="low",
        basis="measured",
        window="since_boot",
        summary=(
            f"{len(busy)} system daemons or kernel threads averaged at least "
            f"{BUSY_DAEMON_CORE_PCT:g}% of one core since boot: {listed}.{elsewhere}"
        ),
        metrics={r.name: share for r, share in busy[:10]},
        evidence=[_ps_evidence(r) for r, _ in busy[:6]],
        recommendation=(
            "Check how much of this CPU fell on battery "
            "(system_process_cpu_churn). A daemon that works only on battery "
            "points at suspend/resume or Doze behaviour."
        ),
        followups=[
            (
                "After an hour of screen-off time on battery, run `adb_ro.py "
                "--save ps_later --workdir WORKDIR -- ps -A -o PID,TIME,NAME` "
                "and compare each daemon's TIME in WORKDIR/live/ps_later.txt "
                "with live/ps.txt."
            ),
        ],
        related=related,
    )


@analyzer(
    "process_cpu_since_boot",
    requires=("ps",),
    after=("windows", "system_process_cpu_churn"),
)
def process_cpu_since_boot(ctx: Context) -> Result:
    """Rank processes by CPU since start and check core daemons for restarts."""
    text = ctx.sources.get("ps")
    rows = [r for r in load_ps(ctx) if r.tid is None]
    if text is None or not rows:
        msg = "ps output has no PID/TIME columns; collect with -o ...TIME...NAME"
        raise SkipError(msg)
    result = Result("process_cpu_since_boot", window="since_boot")
    w = ctx.windows
    uptime_s = (
        (w.dump_time - w.boot_time).total_seconds()
        if w.dump_time and w.boot_time
        else None
    )
    if skipped := _unparsed(text, rows):
        result.notes.append(f"Skipped {skipped} unparsable ps lines.")
    result.notes.append(
        "TIME is CPU since each process started; for processes started after "
        "boot the average share of a core is a lower bound.",
    )
    table: list[Row] = []
    busy: list[tuple[PsRow, float]] = []
    for row in sorted(rows, key=lambda r: -r.cpu_s):
        share = pct(row.cpu_s, uptime_s, 2)
        flag = _busy_daemon(row, share)
        table.append(
            {
                "pid": row.pid,
                "user": row.user,
                "process": row.name,
                "cpu_s": round(row.cpu_s, 1),
                "core_pct_since_boot": share,
                "busy_daemon": flag,
                "ref": row.ref,
            },
        )
        if flag and share is not None:
            busy.append((row, share))
    result.add_table("processes", table)
    result.add_table("kernel_thread_groups", _kernel_groups(rows))
    daemons, restarted = _core_daemons(rows)
    result.tables["core_daemons"] = daemons
    result.metrics.update(
        {
            "processes": len(rows),
            "uptime_s": round(uptime_s) if uptime_s else None,
            "total_cpu_s": round(sum(r.cpu_s for r in rows), 1),
            "kernel_threads": sum(1 for r in rows if r.name.startswith("[")),
            "core_daemons_checked": len(daemons),
            "core_daemons_restarted": len(restarted),
            "busy_daemons": len(busy),
        },
    )
    if restarted:
        result.findings.append(_restart_finding(restarted))
    reported = _churn_reported(ctx)
    unreported = [(r, s) for r, s in busy if _base(r.name) not in reported]
    if unreported:
        related = sorted(
            {reported[n] for r, _ in busy if (n := _base(r.name)) in reported}
        )
        result.findings.append(_busy_finding(unreported, related))
    return result


# ----------------------------------------------------------------------------
# batterystats per-UID CPU


@dataclass
class UidCpu:
    """CPU counters of one UID block of batterystats."""

    uid: int
    index: int  # first line of the block, for citations
    total_s: float | None = None
    freq_ms: list[int] = field(default_factory=list)
    screen_off_freq_ms: list[int] = field(default_factory=list)
    screen_off_index: int | None = None
    procs: list[ProcCpu] = field(default_factory=list)


@dataclass
class Killed:
    """One ``* Killed for cpu use`` line under a ``Proc`` entry."""

    proc: ProcCpu
    used_s: float
    over_s: float
    pct: int | None
    index: int


@dataclass
class BatteryCpu:
    """The CPU-related parts of the since-charge batterystats block."""

    since: SinceCharge
    uids: dict[int, UidCpu] = field(default_factory=dict)
    killed: list[Killed] = field(default_factory=list)
    skipped: int = 0

    @property
    def text(self) -> Text:
        """The dump the line indexes refer to."""
        return self.since.text

    def procs(self) -> list[ProcCpu]:
        """Return every Proc entry of every UID."""
        return self.since.procs

    def uid_cpu_s(self, uid: int) -> float | None:
        """Return the UID's CPU from ``Total cpu time`` or its Proc sum."""
        block = self.uids.get(uid)
        if block is None:
            return None
        if block.total_s is not None:
            return block.total_s
        return sum(p.cpu_s for p in block.procs) or None

    def model(self, uid: int) -> UidPower | None:
        """Return the UID's row of the power model, if any."""
        power = self.since.power
        return power.uids.get(uid) if power else None

    def mah_per_cpu_s(self, uid: int) -> float | None:
        """Return the UID's modelled CPU mAh divided by its CPU seconds."""
        model = self.model(uid)
        cpu_mah = model.components.get("cpu") if model else None
        cpu_s = self.uid_cpu_s(uid)
        return cpu_mah / cpu_s if cpu_mah is not None and cpu_s else None

    def scaling(self) -> list[tuple[str, list[int]]]:
        """Return ``(policy, frequency steps)`` from the ``CPU scaling`` line."""
        found = self.since.header("CPU scaling")
        policies: list[tuple[str, list[int]]] = []
        for token in found[0].split() if found else []:
            if token.endswith(":"):
                policies.append((token[:-1], []))
            elif token.isdigit() and policies:
                policies[-1][1].append(int(token))
        return policies

    def wakeup_attempts(self) -> int | None:
        """Return the sum of the 'All wakeup reasons' counts (aborts plus wakeups)."""
        counts = [r.count for r in self.since.wakeup_reasons if r.count is not None]
        return sum(counts) if counts else None


def _uid_cpu(out: BatteryCpu, uid: int, lines: list[tuple[int, str]]) -> UidCpu:
    """Read the CPU counters and kill records of one UID block."""
    by_index = {p.index: p for p in out.since.procs if p.uid == uid}
    block = UidCpu(uid, lines[0][0] if lines else 0, procs=list(by_index.values()))
    proc: ProcCpu | None = None
    for i, line in lines:
        if not line.startswith("      "):
            proc = by_index.get(i)
        try:
            _uid_line(out, block, proc, i, line)
        except ValueError:
            out.skipped += 1
    return block


def _uid_line(
    out: BatteryCpu,
    block: UidCpu,
    proc: ProcCpu | None,
    i: int,
    line: str,
) -> None:
    if m := _TOTAL_CPU_RE.match(line):
        block.total_s = (parse_duration_ms(m[1]) + parse_duration_ms(m[2])) / _MS
    elif m := _FREQ_RE.match(line):
        steps = [int(x) for x in m[2].split() if x.isdigit()]
        if m[1]:
            block.screen_off_freq_ms, block.screen_off_index = steps, i
        else:
            block.freq_ms = steps
    elif proc is not None and (m := _KILLED_RE.match(line)):
        used, over = parse_duration_ms(m[2]), parse_duration_ms(m[3])
        share = int(m[4]) if m[4] else None
        out.killed.append(Killed(proc, used / _MS, over / _MS, share, i))


def _since_charge(ctx: Context) -> SinceCharge | None:
    """Return the since-charge block, tolerating three-space UID lines.

    batterystats.py ends a UID block at a three-space line and loses the
    Proc entries after it, so such a block is read again with four spaces;
    line numbers do not change.
    """
    since = load_since_charge(ctx)
    if since is None or not any(_THREE_SPACES_RE.match(x) for _, x in since.lines()):
        return since
    text = since.text
    fixed = Text(text.origin, _THREE_SPACES_RE.sub("    ", text.text), text.first_line)
    return parse_since_charge(fixed, whole=since.start < 0)


def _battery_cpu(since: SinceCharge | None) -> BatteryCpu | None:
    if since is None or not since.uid_blocks:
        return None
    out = BatteryCpu(since)
    for uid, lines in since.uid_blocks.items():
        out.uids[uid] = _uid_cpu(out, uid, lines)
    return out


def load_battery_cpu(ctx: Context) -> BatteryCpu:
    """Return per-UID CPU of the since-charge batterystats block (parsed once)."""
    found = ctx.sources.memo(
        "cpu.battery_cpu",
        lambda: _battery_cpu(_since_charge(ctx)),
    )
    if found is None:
        msg = "no batterystats per-UID CPU (batterystats_charged or batterystats)"
        raise SkipError(msg)
    return found


def _battery_s(ctx: Context) -> float | None:
    """Return the time on battery when it is long enough for rates."""
    seconds = ctx.windows.on_battery_s
    return seconds if seconds and seconds >= MIN_ON_BATTERY_S else None


def _proc_display(proc: ProcCpu) -> str:
    """Group kernel threads of UID 0 (no user time); keep other names."""
    if proc.uid == 0 and proc.usr_s == 0:
        return kernel_group(proc.name)
    return proc.name


def _grouped_proc_rows(ctx: Context, bs: BatteryCpu) -> list[Row]:
    on_batt_s = _battery_s(ctx)
    grouped: dict[tuple[int, str], list[ProcCpu]] = defaultdict(list)
    for proc in bs.procs():
        grouped[proc.uid, _proc_display(proc)].append(proc)
    rows: list[Row] = []
    for (uid, name), procs in grouped.items():
        # Sums stay exact to the millisecond, as the dump prints them.
        usr = round(sum(p.usr_s for p in procs), 3)
        krn = round(sum(p.krn_s for p in procs), 3)
        cpu_s = usr + krn
        rate = bs.mah_per_cpu_s(uid)
        biggest = max(procs, key=lambda p: p.cpu_s)
        rows.append(
            {
                "uid": format_uid(uid),
                "uid_name": ctx.packages.name(uid),
                "process": name,
                "entries": len(procs),
                "cpu_s": round(cpu_s, 1),
                "usr_s": round(usr, 1),
                "krn_s": round(krn, 1),
                "krn_pct": pct(krn, cpu_s),
                "core_pct_on_battery": pct(cpu_s, on_batt_s, 2),
                "starts": sum(p.starts for p in procs),
                "modelled_cpu_mah": round(rate * cpu_s, 2) if rate else None,
                "ref": bs.text.ref(biggest.index),
            },
        )
    rows.sort(key=lambda r: -r["cpu_s"])
    return rows


def _uid_rows(ctx: Context, bs: BatteryCpu) -> list[Row]:
    rows: list[Row] = []
    for number, block in bs.uids.items():
        if not (cpu_s := bs.uid_cpu_s(number)):
            continue
        model = bs.model(number)
        rate = bs.mah_per_cpu_s(number)
        rows.append(
            {
                "uid": format_uid(number),
                "name": ctx.packages.name(number),
                "cpu_s": round(cpu_s, 1),
                "procs_cpu_s": round(sum(p.cpu_s for p in block.procs), 1),
                "modelled_cpu_mah": model.components.get("cpu") if model else None,
                "mah_per_cpu_s": round(rate, 5) if rate else None,
                "ref": bs.text.ref(block.index),
            },
        )
    rows.sort(key=lambda r: -r["cpu_s"])
    return rows


@analyzer("battery_proc_cpu")
def battery_proc_cpu(ctx: Context) -> Result:
    """Rank processes by CPU on battery, with kernel threads grouped.

    Kills for excessive background CPU are tabled here; exit_info_audit owns
    the finding about them.
    """
    bs = load_battery_cpu(ctx)
    result = Result("battery_proc_cpu", window="on_battery")
    if bs.skipped:
        result.notes.append(f"Skipped {bs.skipped} unparsable batterystats lines.")
    result.notes.append(
        "CPU seconds are measured; modelled_cpu_mah splits the UID's modelled "
        "CPU mAh by CPU share and inherits the power model's blind spots.",
    )
    if _battery_s(ctx) is None:
        result.notes.append(
            f"Time on battery unknown or under {MIN_ON_BATTERY_S // 60} min: "
            "no shares of a core.",
        )
    rows = _grouped_proc_rows(ctx, bs)
    result.add_table("processes", rows)
    kernel = [r for r in rows if r["uid"] == "0" and r["usr_s"] == 0]
    result.add_table("kernel_thread_groups", kernel)
    result.add_table("uids", _uid_rows(ctx, bs))
    killed: list[Row] = [
        {
            "uid": format_uid(k.proc.uid),
            "name": ctx.packages.name(k.proc.uid),
            "process": k.proc.name,
            "used_s": round(k.used_s, 2),
            "over_s": round(k.over_s, 1),
            "pct": k.pct,
            "ref": bs.text.ref(k.index),
        }
        for k in bs.killed
    ]
    result.tables["killed_for_cpu"] = killed
    procs = bs.procs()
    for uid in (0, 1000):
        cpu_s = bs.uid_cpu_s(uid)
        rate = bs.mah_per_cpu_s(uid)
        result.metrics[f"uid_{uid}_cpu_s"] = round(cpu_s, 1) if cpu_s else None
        result.metrics[f"uid_{uid}_mah_per_cpu_s"] = round(rate, 5) if rate else None
    result.metrics.update(
        {
            "uids": len(bs.uids),
            "procs": len(procs),
            "on_battery_s": ctx.windows.on_battery_s,
            "procs_cpu_s": round(sum(p.cpu_s for p in procs), 1),
            "uid_0_kernel_threads_cpu_s": round(sum(r["cpu_s"] for r in kernel), 1),
            "killed_for_cpu_events": len(killed),
        },
    )
    return result


# ----------------------------------------------------------------------------
# screen-off CPU per UID


def _screen_off_rows(
    ctx: Context,
    bs: BatteryCpu,
    off_h: float | None,
) -> list[Row]:
    scaling = bs.scaling()
    top_bin = sum(len(steps) for _, steps in scaling) - 1 if scaling else None
    rows: list[Row] = []
    for number, block in bs.uids.items():
        off_ms = sum(block.screen_off_freq_ms)
        all_ms = sum(block.freq_ms)
        if not all_ms and not off_ms:
            continue
        top_share = None
        if top_bin is not None and len(block.freq_ms) > top_bin and all_ms:
            top_share = pct(block.freq_ms[top_bin], all_ms)
        rows.append(
            {
                "uid": format_uid(number),
                "name": ctx.packages.name(number),
                "class": uid_class(number, ctx.packages.third_party),
                "cpu_s": round(all_ms / _MS, 1),
                "screen_off_cpu_s": round(off_ms / _MS, 1),
                "screen_off_s_per_h": round(off_ms / _MS / off_h, 1) if off_h else None,
                "top_step_share_pct": top_share,
                "ref": bs.text.ref(block.screen_off_index or block.index),
            },
        )
    rows.sort(key=lambda r: -r["screen_off_cpu_s"])
    return rows


def _core_dominated_finding(rows: list[Row], metrics: dict[str, Any]) -> Finding:
    rate = metrics["screen_off_cpu_s_per_h"]
    high = rate is not None and rate >= SCREEN_OFF_CPU_HIGH_S_PER_H
    per_hour = f" ({rate:.0f} s per screen-off hour)" if rate else ""
    return Finding(
        id="screen_off_cpu_by_uid.core-dominated",
        title="Screen-off CPU is mostly system and kernel, not apps",
        symptom="battery",
        severity="medium" if high else "info",
        basis="measured",
        window="screen_off_on_battery",
        summary=(
            f"Core UIDs used {metrics['core_share_pct']:.0f}% of the "
            f"{metrics['screen_off_cpu_s']:.0f} s of screen-off CPU{per_hour}; "
            f"apps used {metrics['apps_screen_off_cpu_s']:.0f} s. Apps can at "
            "most be triggers: look at kernel and system processes and at "
            "what wakes the phone."
        ),
        metrics={k: metrics[k] for k in ("core_share_pct", "screen_off_cpu_s_per_h")},
        evidence=[
            Evidence(r["ref"], f"UID {r['uid']} screen-off {r['screen_off_cpu_s']} s")
            for r in rows
            if r["class"] == "core"
        ][:3],
        recommendation=(
            "Check suspend attempts and wakeup reasons (batterystats 'All "
            "wakeup reasons') and the system processes that burn CPU on "
            "battery before restricting individual apps."
        ),
        followups=[
            (
                "Compare screen-off CPU per hour in controlled screen-off runs "
                "with Wi-Fi and mobile data on and off."
            ),
        ],
    )


def _busy_apps_finding(busy: list[Row]) -> Finding:
    listed = ", ".join(
        f"{r['name']} {r['screen_off_s_per_h']:.0f} s/h" for r in busy[:5]
    )
    return Finding(
        id="screen_off_cpu_by_uid.busy-background-apps",
        title="Apps using CPU while the screen is off",
        symptom="battery",
        severity="low",
        basis="measured",
        window="screen_off_on_battery",
        summary=(
            f"{len(busy)} apps used at least {APP_SCREEN_OFF_S_PER_H:g} s of "
            f"CPU per screen-off hour: {listed}."
        ),
        metrics={r["uid"]: r["screen_off_s_per_h"] for r in busy[:10]},
        evidence=[
            Evidence(r["ref"], f"{r['name']} screen-off {r['screen_off_cpu_s']} s")
            for r in busy[:5]
        ],
        recommendation=(
            "Check each app's foreground services, jobs and alarms; limit "
            "background use in Settings > Apps > <app> > App battery usage."
        ),
        followups=["Compare with the app's wakelocks and alarms."],
    )


@analyzer("screen_off_cpu_by_uid", after=("windows", "power_model"))
def screen_off_cpu_by_uid(ctx: Context) -> Result:
    """Split screen-off CPU between core UIDs and apps, and rank the apps."""
    bs = load_battery_cpu(ctx)
    if not any(u.screen_off_freq_ms for u in bs.uids.values()):
        msg = "batterystats has no 'Total screen-off cpu time per freq' lines"
        raise SkipError(msg)
    result = Result("screen_off_cpu_by_uid", window="screen_off_on_battery")
    off_s = ctx.windows.screen_off_on_battery_s
    off_h = off_s / _S_PER_H if off_s and off_s >= MIN_SCREEN_OFF_S else None
    rows = _screen_off_rows(ctx, bs, off_h)
    result.add_table("uids", rows)
    peaky = [
        r
        for r in rows
        if r["class"] != "core"
        and r["cpu_s"] >= TOP_STEP_MIN_CPU_S
        and (r["top_step_share_pct"] or 0) >= TOP_STEP_HEAVY_PCT
    ]
    result.add_table("top_step_heavy", sorted(peaky, key=lambda r: -r["cpu_s"]))
    core = sum(r["screen_off_cpu_s"] for r in rows if r["class"] == "core")
    total = sum(r["screen_off_cpu_s"] for r in rows)
    rate = total / off_h if off_h else None
    result.metrics.update(
        {
            "cpu_policies": " ".join(
                f"{name}:{len(steps)}x{max(steps, default=0)}kHz"
                for name, steps in bs.scaling()
            ),
            "screen_off_realtime_h": round(off_h, 2) if off_h else None,
            "screen_off_cpu_s": round(total, 1),
            "core_screen_off_cpu_s": round(core, 1),
            "apps_screen_off_cpu_s": round(total - core, 1),
            "core_share_pct": pct(core, total),
            "screen_off_cpu_s_per_h": round(rate, 1) if rate else None,
            "screen_off_core_pct": pct(rate, _S_PER_H),
        },
    )
    result.notes.append(
        "Per-frequency sums can differ slightly from 'Total cpu time u= s='. "
        "The top step is the highest frequency of the last CPU policy.",
    )
    if not ctx.packages.third_party:
        result.notes.append(
            "No third-party package list: apps are not split by origin."
        )
    if off_h is None:
        result.notes.append(
            f"Screen-off time on battery unknown or under {MIN_SCREEN_OFF_S // 60} "
            "min; no hourly rates.",
        )
    share = result.metrics["core_share_pct"]
    if share is not None and share >= CORE_SHARE_HIGH_PCT:
        core_finding = _core_dominated_finding(rows, result.metrics)
        # The power model's view of the same split (modelled mAh, not CPU time).
        if modelled := ctx.finding("power_model.system_uids_dominate"):
            link(core_finding, modelled)
        result.findings.append(core_finding)
    busy = [
        r
        for r in rows
        if r["class"] != "core"
        and (r["screen_off_s_per_h"] or 0) >= APP_SCREEN_OFF_S_PER_H
    ]
    if busy:
        result.findings.append(_busy_apps_finding(busy))
    return result


# ----------------------------------------------------------------------------
# top samples


@dataclass
class TopRow:
    """One process in one ``top`` sample (threads summed per PID)."""

    pid: int
    user: str
    cpu_pct: float
    name: str
    index: int
    time_s: float | None = None
    threads: int = 1


@dataclass
class TopSample:
    """One ``top`` iteration."""

    index: int
    summary: dict[str, int] = field(default_factory=dict)
    rows: dict[int, TopRow] = field(default_factory=dict)


def _top_row(tokens: list[str], columns: list[str], index: int) -> TopRow:
    """Parse one row; raise ValueError (or IndexError) when it is cut short."""
    pid = int(tokens[columns.index("PID")])
    cpu = parse_decimal(tokens[columns.index("%CPU")])
    user = tokens[columns.index("USER")] if "USER" in columns else ""
    if columns[-1] in {"ARGS", "CMDLINE", "COMMAND"} and "TID" not in columns:
        name = " ".join(tokens[len(columns) - 1 :])
    else:
        name = tokens[-1]
    if not name:
        msg = "top row without a process name"
        raise ValueError(msg)
    time_s = None
    if "TIME+" in columns:
        try:
            time_s = parse_clock_s(tokens[columns.index("TIME+")])
        except ValueError:
            time_s = None
    return TopRow(pid, user, cpu, name, index, time_s)


def _add_top_row(sample: TopSample, row: TopRow) -> None:
    if (old := sample.rows.get(row.pid)) is not None:
        old.cpu_pct += row.cpu_pct
        old.threads += 1
    else:
        sample.rows[row.pid] = row


def parse_top(text: Text) -> tuple[list[TopSample], int]:
    """Split ``top -b`` output into samples; threads (``-H``) are summed per PID."""
    samples: list[TopSample] = []
    skipped = 0
    columns: list[str] = []
    for i, line in enumerate(text.lines):
        if _TOP_SAMPLE_RE.match(line):
            samples.append(TopSample(i))
            columns = []
        elif not samples or not line.strip():
            continue
        elif "%cpu" in line and not columns:
            samples[-1].summary = {k: int(v) for v, k in _TOP_SUMMARY_RE.findall(line)}
            samples[-1].index = i
        elif "PID" in line and "CPU" in line:
            columns = line.replace("[", " ").replace("]", " ").split()
        elif columns:
            try:
                _add_top_row(samples[-1], _top_row(line.split(), columns, i))
            except (ValueError, IndexError):
                skipped += 1
    return [s for s in samples if s.summary.get("cpu")], skipped


def _tool(name: str) -> bool:
    return _command(name).rsplit("/", 1)[-1] in COLLECTION_TOOLS


def _sample_rows(text: Text, samples: list[TopSample]) -> list[Row]:
    rows: list[Row] = []
    for n, sample in enumerate(samples, 1):
        s = sample.summary
        ranked = sorted(sample.rows.values(), key=lambda r: -r.cpu_pct)
        rows.append(
            {
                "sample": n,
                "total_pct": s["cpu"],
                "user_pct": s.get("user"),
                "sys_pct": s.get("sys"),
                "idle_pct": s.get("idle"),
                "iow_pct": s.get("iow"),
                "idle_share_pct": pct(s.get("idle", 0), s["cpu"]),
                "iow_share_pct": pct(s.get("iow", 0), s["cpu"]),
                "top": "; ".join(f"{r.name[:40]} {r.cpu_pct:g}" for r in ranked[:5]),
                "ref": text.ref(sample.index),
            },
        )
    return rows


def _busiest_rows(text: Text, samples: list[TopSample]) -> list[Row]:
    rows: list[Row] = [
        {
            "sample": n,
            "pid": r.pid,
            "user": r.user,
            "process": r.name[:80],
            "cpu_pct": round(r.cpu_pct, 1),
            "threads": r.threads,
            "ref": text.ref(r.index),
        }
        for n, sample in enumerate(samples, 1)
        for r in sample.rows.values()
        if r.cpu_pct > 0
    ]
    rows.sort(key=lambda r: -r["cpu_pct"])
    return rows


def _time_deltas(samples: list[TopSample]) -> list[Row]:
    first, last = samples[0].rows, samples[-1].rows
    rows: list[Row] = []
    for pid, row in last.items():
        old = first.get(pid)
        if old is None or row.time_s is None or old.time_s is None:
            continue
        if (delta := row.time_s - old.time_s) > 0:
            rows.append(
                {"pid": pid, "process": row.name[:80], "cpu_s": round(delta, 2)},
            )
    rows.sort(key=lambda r: -r["cpu_s"])
    return rows


def _hogs(samples: list[TopSample]) -> list[list[TopRow]]:
    if len(samples) < TOP_MIN_SAMPLES:
        return []
    hogs = []
    for pid in set.intersection(*(set(s.rows) for s in samples)):
        per = [s.rows[pid] for s in samples]
        name = per[0].name
        if _tool(name) or EXPECTED_BUSY_RE.match(_command(name)):
            continue
        if all(r.cpu_pct >= TOP_HOG_CPU_PCT for r in per):
            hogs.append(per)
    return hogs


def _top_load_finding(kind: str, flagged: list[int], table: list[Row]) -> Finding:
    saturated = kind == "saturated"
    limit = TOP_IDLE_SATURATED_PCT if saturated else TOP_IOWAIT_PCT
    return Finding(
        id="top_samples.cpu-saturated" if saturated else "top_samples.io-wait",
        title=(
            "CPU saturated during the top samples"
            if saturated
            else "CPU waiting on storage during the top samples"
        ),
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=(
            f"{'Idle was below' if saturated else 'I/O wait was at least'} "
            f"{limit:g}% of capacity in {len(flagged)} of {len(table)} samples."
        ),
        metrics={f"{kind}_samples": len(flagged)},
        evidence=[
            Evidence(table[n - 1]["ref"], table[n - 1]["top"]) for n in flagged[:3]
        ],
        recommendation=(
            "Look at the busiest processes in the samples and repeat the "
            "capture on battery while the phone feels slow."
            if saturated
            else "Check free storage (Settings > Storage), memory pressure "
            "(refaults, swap) and which process reads or writes most."
        ),
        followups=[
            (
                "While the phone is slow, run `adb_ro.py --save top_slow "
                "--workdir WORKDIR -- top -b -n 5 -d 5` and read "
                "WORKDIR/live/top_slow.txt."
            ),
        ],
    )


def _hog_finding(text: Text, per: list[TopRow], *, charging: bool) -> Finding:
    name = _command(per[0].name)
    note = (
        " The phone was charging, so this may not describe battery use."
        if charging
        else ""
    )
    return Finding(
        id=f"top_samples.hog-{slug(name)}",
        title=f"{name} busy in every top sample",
        symptom="both",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=(
            f"{name} (PID {per[0].pid}) used "
            + "/".join(f"{r.cpu_pct:g}" for r in per)
            + f"% of a core in all {len(per)} samples.{note}"
        ),
        metrics={"cpu_pct": [r.cpu_pct for r in per]},
        evidence=[text.evidence(r.index) for r in per],
        recommendation=(
            "If this is an app, check whether it is in use; otherwise limit it "
            "in Settings > Apps > <app> > App battery usage."
        ),
        followups=[
            (
                "A few minutes later, on battery, run `adb_ro.py --save "
                "top_later --workdir WORKDIR -- top -b -n 3 -d 5` and grep "
                f"WORKDIR/live/top_later.txt for {name}."
            ),
        ],
    )


@analyzer("top_samples", requires=("top",))
def top_samples(ctx: Context) -> Result:
    """Read short ``top`` samples: load split, I/O wait and the busiest processes."""
    text = ctx.sources.get("top")
    if text is None:
        msg = "no top output"
        raise SkipError(msg)
    samples, skipped = parse_top(text)
    if not samples:
        msg = "top output has no '%cpu' summary lines"
        raise SkipError(msg)
    result = Result("top_samples", window="snapshot")
    from_bugreport = text.origin.startswith("bugreport:")
    charging = ctx.windows.on_battery_at_capture is False
    if skipped:
        result.notes.append(f"Skipped {skipped} unparsable top rows.")
    result.notes.append(
        "Per-process %CPU is of one core (the maximum is cores x 100); the "
        "collection tools themselves (top, dumpstate) are not counted as hogs.",
    )
    if from_bugreport:
        result.notes.append(
            "This sample is the bugreport's CPU INFO, taken while dumpstate ran; "
            "its load includes the bugreport itself, so no saturation finding.",
        )
    if charging:
        result.notes.append("The phone was charging when these samples were taken.")
    table = _sample_rows(text, samples)
    result.tables["samples"] = table
    result.add_table("busiest", _busiest_rows(text, samples))
    if len(samples) > 1:
        result.add_table("cpu_between_first_and_last", _time_deltas(samples))
    saturated = [
        r["sample"] for r in table if r["idle_share_pct"] < TOP_IDLE_SATURATED_PCT
    ]
    iowait = [r["sample"] for r in table if r["iow_share_pct"] >= TOP_IOWAIT_PCT]
    hogs = _hogs(samples)
    result.metrics.update(
        {
            "samples": len(samples),
            "total_pct": samples[0].summary["cpu"],
            "idle_share_pct_min": min(r["idle_share_pct"] for r in table),
            "idle_share_pct_max": max(r["idle_share_pct"] for r in table),
            "iow_share_pct_max": max(r["iow_share_pct"] for r in table),
            "saturated_samples": len(saturated),
            "iowait_samples": len(iowait),
            "hogs": len(hogs),
        },
    )
    need = min(TOP_MIN_SAMPLES, len(samples))
    if len(saturated) >= need and not from_bugreport:
        result.findings.append(_top_load_finding("saturated", saturated, table))
    if len(iowait) >= need:
        result.findings.append(_top_load_finding("iowait", iowait, table))
    result.findings.extend(
        _hog_finding(text, per, charging=charging) for per in hogs[:3]
    )
    return result


# ----------------------------------------------------------------------------
# dumpsys cpuinfo


@dataclass
class CpuInfo:
    """The last ProcessCpuTracker window of ``dumpsys cpuinfo``.

    ``uptime_s`` comes from the ``from X ms to Y ms ago`` uptime span; the
    printed wall-clock stamps can straddle a clock change.
    """

    load: tuple[float, float, float] | None = None
    start: datetime | None = None
    end: datetime | None = None
    uptime_s: float | None = None
    awake_pct: float | None = None
    window_index: int | None = None
    total: dict[str, float] = field(default_factory=dict)
    total_index: int | None = None
    rows: list[Row] = field(default_factory=list)
    skipped: int = 0

    @property
    def wall_s(self) -> float | None:
        """The window's length by its wall-clock stamps."""
        return (
            (self.end - self.start).total_seconds() if self.start and self.end else None
        )

    @property
    def clock_jump(self) -> bool:
        """Whether the wall-clock stamps disagree with the uptime span.

        The awake share is printed as a whole percent, so the real (awake
        plus asleep) length lies between uptime x 100 / (awake + 1) and
        uptime x 100 / awake.
        """
        wall, up = self.wall_s, self.uptime_s
        if wall is None or up is None:
            return False
        awake = self.awake_pct
        low = up * _PCT / (awake + 1) if awake is not None else up
        high = up * _PCT / awake if awake else (up if awake is None else wall)
        return not low - CPUINFO_CLOCK_SLACK_S <= wall <= high + CPUINFO_CLOCK_SLACK_S

    @property
    def duration_s(self) -> float | None:
        """The window's real length: wall clock, else uptime / awake share."""
        if not self.clock_jump and self.wall_s is not None:
            return self.wall_s
        if self.uptime_s is None:
            return None
        return (
            self.uptime_s * _PCT / self.awake_pct if self.awake_pct else self.uptime_s
        )


def _parts(text: str) -> dict[str, float]:
    return {kind: parse_decimal(v) for v, kind in _CPUINFO_PART_RE.findall(text)}


def _cpuinfo_row(m: re.Match[str], ref: str, index: int) -> Row:
    parts = _parts(m[4])
    faults = {kind: int(v) for v, kind in _FAULTS_RE.findall(m[4])}
    return {
        "pid": int(m[2]),
        "process": m[3],
        "cpu_pct": parse_decimal(m[1]),
        "user_pct": parts.get("user"),
        "kernel_pct": parts.get("kernel"),
        "minor_faults": faults.get("minor", 0),
        "major_faults": faults.get("major", 0),
        "ref": ref,
        "line": index,
    }


def _feed_cpuinfo(info: CpuInfo, text: Text, i: int, line: str) -> None:
    if m := _LOAD_RE.match(line):
        a, b, c = (parse_decimal(x) for x in m.groups())
        info.load = (a, b, c)
    elif m := _CPUINFO_WINDOW_RE.search(line):
        info.start = datetime.fromisoformat(m[3])
        info.end = datetime.fromisoformat(m[4])
        info.uptime_s = (int(m[1]) - int(m[2])) / _MS
        info.awake_pct = parse_decimal(m[5]) if m[5] else None
        info.window_index = i
    elif m := _CPUINFO_TOTAL_RE.match(line):
        info.total = {"pct": parse_decimal(m[1]), **_parts(m[2])}
        info.total_index = i
    elif m := _CPUINFO_ROW_RE.match(line):
        info.rows.append(_cpuinfo_row(m, text.ref(i), i))
    elif "%" in line:
        info.skipped += 1


def parse_cpuinfo(text: Text) -> CpuInfo:
    """Parse load, the window line, TOTAL and the per-process rows."""
    info = CpuInfo()
    for i, line in enumerate(text.lines):
        try:
            _feed_cpuinfo(info, text, i, line)
        except ValueError:
            info.skipped += 1
    return info


def _window_evidence(text: Text, info: CpuInfo) -> list[Evidence]:
    i = info.window_index
    return [] if i is None else [text.evidence(i)]


def _fault_finding(text: Text, info: CpuInfo, faulting: list[Row]) -> Finding:
    listed = ", ".join(
        f"{r['process']} {r['major_faults_per_s']:.0f}/s" for r in faulting[:4]
    )
    return Finding(
        id="cpuinfo_window.major-fault-thrash",
        title="Processes reading pages back from storage (major faults)",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=(
            f"In the last CPU window ({info.duration_s or 0:.0f} s), major faults "
            f"per second: {listed} (threshold {MAJOR_FAULTS_PER_S:g}/s). Pages "
            "evicted under memory pressure are being read back from storage."
        ),
        metrics={r["process"]: r["major_faults_per_s"] for r in faulting[:5]},
        evidence=[text.evidence(r["line"]) for r in faulting[:4]]
        + _window_evidence(text, info),
        recommendation=(
            "Reduce memory pressure: close or uninstall unused heavy apps and "
            "check the memory analysis (swap, refaults, kills)."
        ),
        followups=[
            (
                "A few minutes later, run `adb_ro.py --save vmstat_later "
                "--workdir WORKDIR -- cat /proc/vmstat` and compare pgmajfault "
                "and workingset_refault in WORKDIR/live/vmstat_later.txt with "
                "the first capture."
            ),
        ],
    )


def _daemons_finding(
    text: Text,
    info: CpuInfo,
    busy: list[Row],
    state: str,
    related: list[str],
) -> Finding:
    listed = ", ".join(f"{r['process']} {r['cpu_pct']:g}%" for r in busy[:5])
    context = [f"{info.duration_s or 0:.0f} s"]
    if state:
        context.append(state)
    if info.awake_pct is not None:
        context.append(f"{info.awake_pct:g}% awake")
    elsewhere = (
        f" {len(related)} more are reported with their CPU on battery "
        "(system_process_cpu_churn)."
        if related
        else ""
    )
    return Finding(
        id="cpuinfo_window.busy-daemons",
        title="System daemons busy in the last CPU window",
        symptom="battery",
        severity="low",
        basis="measured",
        window="snapshot",
        summary=(
            f"In the last CPU window ({', '.join(context)}): {listed} of one "
            f"core.{elsewhere}"
        ),
        metrics={r["process"]: r["cpu_pct"] for r in busy[:5]},
        evidence=[text.evidence(r["line"]) for r in busy[:5]]
        + _window_evidence(text, info),
        recommendation=(
            "Compare with the daemons' CPU over the whole battery period "
            "(system_process_cpu_churn) before acting on a one-minute sample."
        ),
        followups=[
            (
                "A few minutes later, on battery, run `adb_ro.py --save "
                "cpuinfo_later --workdir WORKDIR -- dumpsys cpuinfo` and grep "
                "WORKDIR/live/cpuinfo_later.txt for the daemons."
            ),
        ],
        related=related,
    )


def _idle_finding(text: Text, info: CpuInfo) -> Finding:
    load = info.load or (0.0, 0.0, 0.0)
    index = info.total_index or 0
    return Finding(
        id="cpuinfo_window.cpu-not-saturated",
        title="CPU not saturated in the last CPU window",
        symptom="info",
        severity="info",
        basis="measured",
        window="snapshot",
        summary=(
            f"TOTAL was {info.total['pct']:g}% of all cores and the load "
            f"average {load[0]:g} / {load[1]:g} / {load[2]:g}: the CPU has "
            "spare capacity, so battery drain is about wakeups and lost sleep, "
            "and slowness about memory or storage rather than compute."
        ),
        metrics={"total_pct": info.total["pct"], "load_1m": load[0]},
        evidence=[text.evidence(index)],
        followups=[
            (
                "While the phone feels slow, run `adb_ro.py --save cpuinfo_slow "
                "--workdir WORKDIR -- dumpsys cpuinfo`."
            ),
        ],
    )


def _is_daemon(row: Row, users: dict[int, str]) -> bool:
    if EXPECTED_BUSY_RE.match(row["process"]):
        return False
    user = users.get(row["pid"])
    if user is not None:
        return not _is_app_user(user)
    return "." not in row["process"] or row["process"].startswith(
        ("android.", "vendor."),
    )


def _cpuinfo_on_battery(ctx: Context, info: CpuInfo) -> bool | None:
    """Return whether the window fell on battery; None if unknown or mixed."""
    if info.start is None or info.end is None or info.clock_jump:
        return None
    end = max(info.start, info.end - CPUINFO_PLUG_SLACK)
    state = power_state(ctx.windows, info.start, end)
    return {"on_battery": True, "charging": False}.get(state)


@analyzer(
    "cpuinfo_window",
    requires=("cpuinfo",),
    after=("windows", "system_process_cpu_churn", "vmstat_reclaim_io"),
)
def cpuinfo_window(ctx: Context) -> Result:
    """Read the last ProcessCpuTracker window: load, per-process CPU, faults."""
    text = ctx.sources.get("cpuinfo")
    if text is None:
        msg = "no cpuinfo dump"
        raise SkipError(msg)
    info = parse_cpuinfo(text)
    if not info.rows and not info.total:
        msg = "cpuinfo has no per-process rows"
        raise SkipError(msg)
    result = Result("cpuinfo_window", window="snapshot")
    if info.skipped:
        result.notes.append(f"Skipped {info.skipped} unparsable cpuinfo lines.")
    result.notes.append(
        "Per-process % is of one core over the window's awake (uptime) time; "
        "TOTAL is of all cores. The window can end minutes before the dump.",
    )
    if info.clock_jump:
        result.notes.append(
            f"The window's wall-clock stamps span {info.wall_s:.0f} s but its "
            f"uptime span is {info.uptime_s:.1f} s: the clock changed inside the "
            "window, so its length comes from the uptime span and its battery "
            "state is unknown.",
        )
    duration_s = info.duration_s
    for row in info.rows:
        row["major_faults_per_s"] = (
            round(row["major_faults"] / duration_s, 1) if duration_s else None
        )
    rows = sorted(info.rows, key=lambda r: -r["cpu_pct"])
    on_battery = _cpuinfo_on_battery(ctx, info)
    load = info.load or (None, None, None)
    result.metrics.update(
        {
            "load_1m": load[0],
            "load_5m": load[1],
            "load_15m": load[2],
            "window_start": info.start.isoformat(sep=" ") if info.start else None,
            "window_end": info.end.isoformat(sep=" ") if info.end else None,
            "window_wall_s": round(duration_s, 1) if duration_s else None,
            "window_uptime_s": round(info.uptime_s, 1) if info.uptime_s else None,
            "awake_pct": info.awake_pct,
            "window_on_battery": on_battery,
            "total_pct": info.total.get("pct"),
            "total_user_pct": info.total.get("user"),
            "total_kernel_pct": info.total.get("kernel"),
            "total_iowait_pct": info.total.get("iowait"),
            "processes": len(rows),
        },
    )
    result.add_table(
        "processes",
        [{k: v for k, v in r.items() if k != "line"} for r in rows],
    )
    faulting = sorted(
        (r for r in rows if (r["major_faults_per_s"] or 0) > MAJOR_FAULTS_PER_S),
        key=lambda r: -r["major_faults"],
    )
    if faulting:
        faults = _fault_finding(text, info, faulting)
        # Since-boot thrashing owns the fact; this window shows who faults now.
        # One-way, so that it owns on equal strength (budget.owner_map).
        if thrashing := ctx.finding("vmstat_reclaim_io.page_cache_thrashing"):
            link(thrashing, faults, mutual=False)
        result.findings.append(faults)
    users = {r.pid: r.user for r in load_ps(ctx)}
    busy = [
        r for r in rows if r["cpu_pct"] >= CPUINFO_DAEMON_PCT and _is_daemon(r, users)
    ]
    reported = _churn_reported(ctx)
    unreported = [r for r in busy if _base(r["process"]) not in reported]
    if unreported:
        state = {True: "on battery", False: "charging"}.get(on_battery, "")
        related = sorted(
            {reported[n] for r in busy if (n := _base(r["process"])) in reported},
        )
        result.findings.append(
            _daemons_finding(text, info, unreported, state, related),
        )
    if (
        info.total
        and info.load
        and info.total["pct"] < CPUINFO_IDLE_TOTAL_PCT
        and info.load[0] < CPUINFO_IDLE_LOAD
    ):
        result.findings.append(_idle_finding(text, info))
    return result


# ----------------------------------------------------------------------------
# am_cpu event-log intervals


@dataclass
class AmCpuBatch:
    """One CPU-stats update: the am_cpu rows logged at one moment by one thread."""

    ts: datetime
    ref: str
    rows: dict[int, tuple[str, int, int]] = field(default_factory=dict)
    interval_ms: int = 0
    start: datetime | None = None


def _event_log(ctx: Context) -> EventLog:
    """Return the event log, or a merged ``logcat -b all`` dump standing in."""
    events = load_event_log(ctx)
    text = ctx.sources.get("logcat_all")
    if events.lines or text is None:
        return events
    lines = iter_logcat(text.text, ctx.windows.log_reference(), text.first_line)
    return EventLog(text, sorted(lines, key=lambda line: line.ts))


def parse_am_cpu(events: EventLog) -> tuple[list[AmCpuBatch], int]:
    """Group am_cpu rows into updates, oldest first; also count unparsable rows.

    Each row is ``pid -> (name, rel_uptime_ms, cpu_ms)``.
    """
    batches: dict[tuple[datetime, int], AmCpuBatch] = {}
    bad = 0
    for line in events.by_tag("am_cpu"):
        if not (m := _AM_CPU_RE.match(line.message.strip())):
            bad += 1
            continue
        key = (line.ts.replace(microsecond=0), line.tid)
        batch = batches.get(key)
        if batch is None:
            batch = batches[key] = AmCpuBatch(line.ts, events.ref(line))
        batch.rows[int(m[1])] = (m[3], int(m[4]), int(m[5]) + int(m[6]))
    ordered = sorted(batches.values(), key=lambda b: b.ts)
    _set_intervals(ordered)
    return ordered, bad


def _set_intervals(batches: list[AmCpuBatch]) -> None:
    """Set each update's interval from the processes also seen in the previous one.

    A process's ``rel_uptime`` runs from the last update in which it used
    CPU, so only processes active in both updates measure the interval.
    """
    previous: AmCpuBatch | None = None
    for batch in batches:
        shared = [
            r[1] for pid, r in batch.rows.items() if previous and pid in previous.rows
        ]
        values = shared or [r[1] for r in batch.rows.values()]
        batch.interval_ms = int(statistics.median(values)) if values else 0
        if previous:
            batch.start = previous.ts
        else:
            batch.start = batch.ts - timedelta(milliseconds=batch.interval_ms)
        previous = batch


def _am_cpu_names(batches: list[AmCpuBatch], by_pid: dict[int, str]) -> dict[int, str]:
    """Map am_cpu PIDs to full ps names when the truncated name agrees."""
    names: dict[int, str] = {}
    for batch in batches:
        for pid, (short, _, _) in batch.rows.items():
            full = by_pid.get(pid, "").strip("[]")
            names[pid] = (
                full if full and (full.endswith(short) or short in full) else short
            )
    return names


def _screen_on_fraction(
    screen: list[Transition],
    start: datetime,
    end: datetime,
) -> float | None:
    """Return the share of ``start..end`` with the screen on, or None."""
    if not screen or end <= start:
        return None
    state = not screen[0].on
    on_s = 0.0
    cursor = start
    for change in screen:
        if change.ts <= start:
            state = change.on
            continue
        if change.ts >= end:
            break
        on_s += (change.ts - cursor).total_seconds() if state else 0.0
        cursor, state = change.ts, change.on
    on_s += (end - cursor).total_seconds() if state else 0.0
    return on_s / (end - start).total_seconds()


@dataclass
class _AmCpuSeries:
    """Per-update CPU seconds per process, with each update's interval and state."""

    cpu: list[dict[str, float]]
    intervals: list[float]
    labels: list[str]
    totals: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Sum CPU per process over all updates, busiest first."""
        totals: dict[str, float] = defaultdict(float)
        for batch in self.cpu:
            for name, s in batch.items():
                totals[name] += s
        self.totals = dict(sorted(totals.items(), key=lambda kv: -kv[1]))

    def series(self, name: str) -> list[float]:
        """Return the process's % of each update's interval."""
        return [
            c.get(name, 0.0) / iv * _PCT if iv else 0.0
            for c, iv in zip(self.cpu, self.intervals, strict=True)
        ]

    def span_pct(self, picked: list[int], name: str) -> float | None:
        """Return the process's % of awake time over the ``picked`` updates."""
        span = sum(self.intervals[i] for i in picked)
        used = sum(self.cpu[i].get(name, 0.0) for i in picked)
        return pct(used, span, 2)

    def picked(self, label: str) -> list[int]:
        """Return the indexes of updates with screen state ``label``."""
        return [i for i, lab in enumerate(self.labels) if lab == label]


def _batch_cpu(
    batches: list[AmCpuBatch],
    names: dict[int, str],
) -> list[dict[str, float]]:
    per_batch = []
    for batch in batches:
        cpu: dict[str, float] = defaultdict(float)
        for pid, (_, _, ms) in batch.rows.items():
            cpu[kernel_group(names[pid])] += ms / _MS
        per_batch.append(dict(cpu))
    return per_batch


def _am_process_rows(s: _AmCpuSeries, no_suspend: list[int]) -> list[Row]:
    covered = sum(s.intervals)
    off, on = s.picked("off"), s.picked("on")
    rows: list[Row] = []
    for name, total_s in s.totals.items():
        series = s.series(name)
        rows.append(
            {
                "process": name,
                "cpu_s": round(total_s, 1),
                "pct_of_uptime": pct(total_s, covered, 2),
                "batches_present": sum(1 for c in s.cpu if name in c),
                "pct_min": round(min(series), 2),
                "pct_median": round(statistics.median(series), 2),
                "pct_max": round(max(series), 2),
                "screen_off_pct": s.span_pct(off, name),
                "screen_on_pct": s.span_pct(on, name),
                "pct_without_suspend": s.span_pct(no_suspend, name),
            },
        )
    return rows


def _pair_row(a: str, b: str, r: float, xs: list[float], ys: list[float]) -> Row:
    ratios = [y / x for x, y in zip(xs, ys, strict=True) if x >= IDLE_PCT]
    return {
        "a": a,
        "b": b,
        "r": round(r, 3),
        "ratio_min": round(min(ratios), 2) if ratios else None,
        "ratio_max": round(max(ratios), 2) if ratios else None,
        "batches_both_idle": sum(
            1 for x, y in zip(xs, ys, strict=True) if x < IDLE_PCT and y < IDLE_PCT
        ),
    }


def _coupled_pairs(s: _AmCpuSeries) -> list[Row]:
    if len(s.cpu) < COUPLED_MIN_BATCHES:
        return []
    names = list(s.totals)[:COUPLED_TOP_PROCESSES]
    series = {name: s.series(name) for name in names}
    pairs: list[Row] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            try:
                r = statistics.correlation(series[a], series[b])
            except statistics.StatisticsError:
                continue
            if r >= COUPLED_MIN_R:
                row = _pair_row(a, b, r, series[a], series[b])
                ratio = s.totals[b] / s.totals[a] if s.totals[a] else None
                row["ratio_b_to_a"] = round(ratio, 2) if ratio is not None else None
                pairs.append(row)
    pairs.sort(key=lambda p: -p["r"])
    return pairs


def _screen_label(fraction: float | None) -> str:
    if fraction is None:
        return "unknown"
    if fraction >= SCREEN_ON_MIN_FRACTION:
        return "on"
    return "off" if fraction <= SCREEN_OFF_MAX_FRACTION else "mixed"


def _batch_rows(
    batches: list[AmCpuBatch],
    s: _AmCpuSeries,
    states: list[str],
) -> list[Row]:
    rows: list[Row] = []
    for batch, used, label, state in zip(
        batches,
        s.cpu,
        s.labels,
        states,
        strict=True,
    ):
        start = batch.start or batch.ts
        top = sorted(used.items(), key=lambda kv: -kv[1])[:4]
        rows.append(
            {
                "time": batch.ts.isoformat(sep=" ", timespec="seconds"),
                "interval_s": round(batch.interval_ms / _MS, 1),
                "wall_span_s": round((batch.ts - start).total_seconds(), 1),
                "cpu_s": round(sum(used.values()), 1),
                "screen": label,
                "on_battery": {"on_battery": True, "charging": False}.get(state),
                "top": "; ".join(f"{n} {v:.1f}" for n, v in top),
                "ref": batch.ref,
            },
        )
    return rows


def suspend_process(names: list[str]) -> str | None:
    """Return the first name that looks like the suspend service."""
    return next((n for n in names if "suspend" in n), None)


@analyzer("am_cpu_intervals")
def am_cpu_intervals(ctx: Context) -> Result:
    """Follow per-process CPU interval by interval from the event log's am_cpu."""
    events = _event_log(ctx)
    if not events.lines:
        msg = "no event log (logcat_events)"
        raise SkipError(msg)
    batches, bad = parse_am_cpu(events)
    if not batches:
        msg = "the event log has no am_cpu rows"
        raise SkipError(msg)
    result = Result("am_cpu_intervals", window="log_coverage")
    if bad:
        result.notes.append(f"Skipped {bad} unparsable am_cpu rows.")
    result.notes.append(
        "am_cpu intervals are uptime (awake time), not wall time, so % of an "
        "interval overstates the per-wall-clock load in Doze. Names are the "
        "last 15 characters of the process name, joined to ps by PID where "
        "possible. Only the span kept by the log buffer is covered.",
    )
    screen = events.screen_transitions()
    s = _AmCpuSeries(
        cpu=_batch_cpu(batches, _am_cpu_names(batches, _process_names(ctx))),
        intervals=[b.interval_ms / _MS for b in batches],
        labels=[
            _screen_label(_screen_on_fraction(screen, b.start or b.ts, b.ts))
            for b in batches
        ],
    )
    w = ctx.windows
    if note := plug_note(w):
        result.notes.append(note)
    suspend = suspend_process(list(s.totals))
    no_suspend = []
    if suspend:
        no_suspend = [
            i
            for i, share in enumerate(s.series(suspend))
            if s.intervals[i] and share < IDLE_PCT
        ]
    result.add_table("processes", _am_process_rows(s, no_suspend))
    states = [power_state(w, b.start or b.ts, b.ts) for b in batches]
    batch_rows = _batch_rows(batches, s, states)
    result.tables["batches"] = batch_rows[-TABLE_CAP:]
    if len(batch_rows) > TABLE_CAP:
        result.notes.append(
            f"batches: showing the last {TABLE_CAP} of {len(batch_rows)} rows",
        )
    pairs = _coupled_pairs(s)
    result.add_table("coupled_pairs", pairs)
    labels = Counter(s.labels)
    plugged = charging_since(w)
    result.metrics.update(
        {
            "batches": len(batches),
            "first_batch": batches[0].ts.isoformat(sep=" ", timespec="seconds"),
            "last_batch": batches[-1].ts.isoformat(sep=" ", timespec="seconds"),
            "covered_uptime_s": round(sum(s.intervals), 1),
            "cpu_s": round(sum(s.totals.values()), 1),
            "screen_off_batches": labels["off"],
            "screen_on_batches": labels["on"],
            "mixed_batches": labels["mixed"],
            "unknown_screen_batches": labels["unknown"],
            "suspend_process": suspend,
            "batches_without_suspend": len(no_suspend),
            "coupled_pairs": len(pairs),
            "plugged_at": plugged.isoformat(sep=" ", timespec="seconds")
            if plugged
            else None,
            "batches_while_charging": states.count("charging"),
        },
    )
    return result


# ----------------------------------------------------------------------------
# per-thread CPU (bugreport PROCESSES AND THREADS)


def _thread_process_row(pid: int, name: str, rows: list[PsRow]) -> Row:
    total = sum(r.cpu_s for r in rows)
    ranked = sorted(rows, key=lambda r: -r.cpu_s)
    top = ranked[0]
    share = top.cpu_s / total * _PCT
    return {
        "pid": pid,
        "process": name,
        "threads": len(rows),
        "cpu_s": round(total, 1),
        "top_thread": top.name,
        "top_tid": top.tid,
        "top_thread_cpu_s": round(top.cpu_s, 1),
        "top_thread_share_pct": round(share, 1),
        "dominant": len(rows) > 1
        and share >= DOMINANT_THREAD_PCT
        and total >= DOMINANT_THREAD_MIN_CPU_S,
        "top3": "; ".join(f"{r.name} {r.cpu_s:.0f}s" for r in ranked[:3]),
        "ref": top.ref,
    }


@analyzer("thread_cpu", requires=("ps_threads",))
def thread_cpu(ctx: Context) -> Result:
    """Find the thread that holds the CPU inside each busy process."""
    text = ctx.sources.get("ps_threads")
    if text is None:
        msg = "no per-thread ps"
        raise SkipError(msg)
    rows = [r for r in parse_ps(text) if r.tid is not None]
    if not rows:
        msg = "no per-thread rows (ps -T with TIME)"
        raise SkipError(msg)
    threads: dict[int, list[PsRow]] = defaultdict(list)
    for row in rows:
        threads[row.pid].append(row)
    result = Result("thread_cpu", window="since_boot")
    if skipped := _unparsed(text, rows):
        result.notes.append(f"Skipped {skipped} unparsable thread lines.")
    result.notes.append(
        "Thread TIME is CPU since each thread started; threads that exited "
        "are missing, so a process's thread sum can be below its own TIME.",
    )
    names = _process_names(ctx)
    processes: list[Row] = []
    hot: list[Row] = []
    for pid, group in threads.items():
        total = sum(r.cpu_s for r in group)
        if total <= 0:
            continue
        main = next((r for r in group if r.tid == pid), group[0])
        name = names.get(pid, main.name)
        processes.append(_thread_process_row(pid, name, group))
        hot.extend(
            {
                "pid": pid,
                "process": name,
                "tid": r.tid,
                "thread": r.name,
                "cpu_s": round(r.cpu_s, 1),
                "share_of_process_pct": pct(r.cpu_s, total),
                "ref": r.ref,
            }
            for r in group
            if r.cpu_s > 0
        )
    processes.sort(key=lambda r: -r["cpu_s"])
    hot.sort(key=lambda r: -r["cpu_s"])
    result.add_table("processes", processes)
    result.add_table("hot_threads", hot)
    dominant = [p for p in processes if p["dominant"]]
    result.add_table("dominant_threads", dominant)
    result.metrics.update(
        {
            "processes": len(threads),
            "threads": len(rows),
            "dominant_thread_processes": len(dominant),
        },
    )
    return result


# ----------------------------------------------------------------------------
# system processes on battery


def _severity_for_rate(core_pct: float) -> Severity:
    if core_pct >= CHURN_HIGH_CORE_PCT:
        return "high"
    return "medium" if core_pct >= CHURN_MEDIUM_CORE_PCT else "low"


def _am_cpu_row(ctx: Context, name: str) -> Row:
    for row in result_table(ctx, "am_cpu_intervals", "processes"):
        short = row["process"]
        if short == name or (len(short) >= MIN_SUFFIX_MATCH and name.endswith(short)):
            return row
    return {}


def _coupling_r(ctx: Context, a: str, b: str | None) -> float | None:
    if b is None or a == b:
        return None
    for row in result_table(ctx, "am_cpu_intervals", "coupled_pairs"):
        pair = (row["a"], row["b"])
        if any(a.endswith(x) for x in pair) and any(b.endswith(x) for x in pair):
            return row["r"]
    return None


@dataclass
class _ChurnInputs:
    bs: BatteryCpu
    on_batt_s: float
    ps: list[PsRow]
    # Process rows (live ps) or main-thread rows (thread list) by name.
    ps_by_name: dict[str, list[PsRow]]
    threads: dict[int, Row]
    suspend_name: str | None
    reboot_inside: bool

    def ps_matches(self, name: str) -> list[PsRow]:
        """Return the ps rows of process ``name``; thread lists cut names to 15."""
        forms = (name, name[:_COMM_LEN], name[-_COMM_LEN:])
        return next((self.ps_by_name[f] for f in forms if f in self.ps_by_name), [])


def _churn_row(ctx: Context, inp: _ChurnInputs, proc: ProcCpu) -> Row:
    cpu_s = proc.cpu_s
    since_boot = inp.ps_matches(proc.name)
    boot_s = ps_cpu_by_name(inp.ps, [proc.name]).get(proc.name) or None
    share = pct(cpu_s, boot_s) if boot_s and not inp.reboot_inside else None
    if share is not None and share > SHARE_SLACK_PCT:
        share = None
    am = _am_cpu_row(ctx, proc.name)
    pid = since_boot[0].pid if len(since_boot) == 1 else None
    thread = inp.threads.get(pid) if pid is not None else None
    rate = inp.bs.mah_per_cpu_s(proc.uid)
    krn_pct = proc.krn_s / cpu_s * _PCT
    return {
        "process": proc.name,
        "uid": format_uid(proc.uid),
        "cpu_s": round(cpu_s, 1),
        "usr_s": round(proc.usr_s, 1),
        "krn_s": round(proc.krn_s, 1),
        "krn_pct": round(krn_pct, 1),
        "core_pct_on_battery": pct(cpu_s, inp.on_batt_s, 2),
        "since_boot_cpu_s": round(boot_s, 1) if boot_s else None,
        "on_battery_share_pct": share,
        "battery_specific": share is not None and share >= BATTERY_SPECIFIC_SHARE_PCT,
        "kernel_heavy": krn_pct >= KERNEL_HEAVY_PCT,
        "screen_off_pct": am.get("screen_off_pct"),
        "screen_on_pct": am.get("screen_on_pct"),
        "pct_without_suspend": am.get("pct_without_suspend"),
        "r_with_suspend_service": _coupling_r(ctx, proc.name, inp.suspend_name),
        "top_thread": thread["top_thread"] if thread and thread["dominant"] else None,
        "top_thread_share_pct": thread["top_thread_share_pct"] if thread else None,
        "modelled_cpu_mah": round(rate * cpu_s, 1) if rate else None,
        "ref": inp.bs.text.ref(proc.index),
        "ps_ref": since_boot[0].ref if since_boot else None,
        "thread_ref": thread["ref"] if thread else None,
    }


_CHURN_METRICS = (
    "cpu_s",
    "usr_s",
    "krn_s",
    "krn_pct",
    "core_pct_on_battery",
    "since_boot_cpu_s",
    "on_battery_share_pct",
    "modelled_cpu_mah",
)


def _churn_facts(row: Row, inp: _ChurnInputs) -> tuple[list[str], dict[str, Any]]:
    name = row["process"]
    metrics = {k: row[k] for k in _CHURN_METRICS}
    facts = [
        (
            f"{name} used {fmt_duration(round(row['cpu_s']))} of CPU on battery "
            f"({row['cpu_s']:.0f} s, {row['krn_pct']:.1f}% kernel), "
            f"{row['core_pct_on_battery']:.1f}% of one core over "
            f"{inp.on_batt_s / _S_PER_H:.1f} h on battery."
        ),
    ]
    if row["on_battery_share_pct"] is not None:
        tail = (
            ", so the load belongs to the battery period."
            if row["battery_specific"]
            else "."
        )
        facts.append(
            f"{row['on_battery_share_pct']:.0f}% of its since-boot CPU "
            f"({fmt_duration(round(row['since_boot_cpu_s']))}) fell in that "
            f"window{tail}",
        )
    if row["kernel_heavy"]:
        facts.append(
            "Almost all of it is kernel time: a kernel path such as "
            "suspend/resume or I/O runs in its thread, not a user-space loop.",
        )
    attempts = inp.bs.wakeup_attempts()
    if attempts and name == inp.suspend_name:
        metrics["ms_per_suspend_attempt"] = round(row["cpu_s"] * _MS / attempts, 1)
        metrics["suspend_attempts"] = attempts
        facts.append(
            f"That is about {metrics['ms_per_suspend_attempt']:.0f} ms per "
            f"suspend attempt over {attempts:,} attempts.",
        )
    if row["r_with_suspend_service"] is not None:
        facts.append(
            f"Per am_cpu interval its CPU moves with {inp.suspend_name} "
            f"(r = {row['r_with_suspend_service']:.2f}).",
        )
    elif name != inp.suspend_name and (row["pct_without_suspend"] or 0) >= IDLE_PCT:
        facts.append(
            "In am_cpu intervals without suspend activity it still used "
            f"{row['pct_without_suspend']:.1f}% of awake time, so its cost "
            "follows awake time rather than suspend attempts.",
        )
    if row["top_thread"]:
        facts.append(
            f"Thread {row['top_thread']} holds {row['top_thread_share_pct']:.0f}% "
            "of its since-boot CPU.",
        )
    return facts, metrics


def _churn_recommendation(name: str, suspend_name: str | None) -> str:
    if name == suspend_name:
        return (
            "The suspend service runs the kernel's suspend/resume path, so its "
            "CPU counts suspend attempts. Find what keeps waking the phone or "
            "aborting suspend (wakeup reasons, kernel log 'PM: suspend entry' "
            "and abort lines) and reduce the trigger, often incoming network "
            "traffic. A per-resume driver fault needs a system update "
            "(Settings > System > System update) or a report to the vendor."
        )
    if name == "ueventd":
        return (
            "ueventd handles kernel device events and should idle after boot. "
            "Sustained CPU means a driver keeps sending uevents, for example on "
            "every resume; compare with the number of resumes and report it to "
            "the vendor with the bugreport."
        )
    if name == "cnss_diag":
        return (
            "cnss_diag is Qualcomm's Wi-Fi firmware log daemon, which a "
            "production phone does not need. Check that Developer options > "
            "Enable Wi-Fi verbose logging is off; if the daemon keeps using "
            "CPU, report it to the vendor with a bugreport."
        )
    return (
        "This is a system or vendor daemon that cannot be turned off without "
        "root. Check for a system update (Settings > System > System update) "
        "and report the CPU use to the vendor; fewer wakeups reduce it if its "
        "cost follows awake time."
    )


def _churn_finding(row: Row, proc: ProcCpu, inp: _ChurnInputs) -> Finding:
    name = row["process"]
    facts, metrics = _churn_facts(row, inp)
    text = inp.bs.text
    cpu_line = proc.cpu_index if proc.cpu_index is not None else proc.index
    evidence = [text.evidence(cpu_line, f"Proc {name}: {text.lines[cpu_line]}")]
    if matches := inp.ps_matches(name):
        evidence.append(_ps_evidence(matches[0]))
    if row["thread_ref"] and row["top_thread"]:
        evidence.append(Evidence(row["thread_ref"], f"thread {row['top_thread']}"))
    return Finding(
        id=f"system_process_cpu_churn.{slug(name)}",
        title=f"{name} burns CPU on battery",
        symptom="battery",
        severity=_severity_for_rate(row["core_pct_on_battery"]),
        basis="measured",
        window="on_battery",
        summary=" ".join(facts),
        metrics=metrics,
        evidence=evidence,
        recommendation=_churn_recommendation(name, inp.suspend_name),
        followups=[
            (
                "On battery with the screen off, run `adb_ro.py --save "
                "ps_before --workdir WORKDIR -- ps -A -o PID,TIME,NAME`, then "
                "an hour later the same with `--save ps_after`, and compare "
                f"{name}'s TIME in WORKDIR/live/ps_before.txt and ps_after.txt."
            ),
            (
                "Compare its rate with suspend attempts and with the screen "
                "state to see whether it follows wakeups or awake time."
            ),
        ],
    )


def _churn_inputs(ctx: Context, bs: BatteryCpu, on_batt_s: float) -> _ChurnInputs:
    rows = load_ps(ctx)
    by_name: dict[str, list[PsRow]] = defaultdict(list)
    for row in rows:
        if row.tid is None or row.tid == row.pid:
            by_name[row.name].append(row)
    w = ctx.windows
    core_user = sorted(
        (p for p in bs.procs() if uid_class(p.uid, frozenset()) == "core" and p.usr_s),
        key=lambda p: -p.cpu_s,
    )
    return _ChurnInputs(
        bs=bs,
        on_batt_s=on_batt_s,
        ps=rows,
        ps_by_name=by_name,
        threads={r["pid"]: r for r in result_table(ctx, "thread_cpu", "processes")},
        suspend_name=suspend_process([p.name for p in core_user]),
        reboot_inside=bool(
            w.boot_time and w.since_charge_start and w.boot_time > w.since_charge_start,
        ),
    )


@analyzer(
    "system_process_cpu_churn",
    after=("windows", "am_cpu_intervals", "thread_cpu"),
)
def system_process_cpu_churn(ctx: Context) -> Result:
    """Find system daemons burning CPU on battery and how battery-specific it is.

    This analyzer owns the 'busy system daemon' fact; process_cpu_since_boot
    and cpuinfo_window list only the daemons it does not report.
    """
    bs = load_battery_cpu(ctx)
    on_batt_s = _battery_s(ctx)
    if on_batt_s is None:
        msg = (
            f"time on battery unknown or under {MIN_ON_BATTERY_S // 60} min "
            "(windows.on_battery_s); shares of a core would be noise"
        )
        raise SkipError(msg)
    inp = _churn_inputs(ctx, bs, on_batt_s)
    result = Result("system_process_cpu_churn", window="on_battery")
    if inp.reboot_inside:
        result.notes.append(
            "The phone rebooted inside the since-charge period, so on-battery "
            "shares of since-boot CPU are not computed.",
        )
    candidates = [
        (_churn_row(ctx, inp, proc), proc)
        for proc in bs.procs()
        if uid_class(proc.uid, frozenset()) == "core"
        and proc.usr_s > 0
        and not EXPECTED_BUSY_RE.match(proc.name)
        and proc.cpu_s / on_batt_s * _PCT >= CHURN_MIN_CORE_PCT
    ]
    candidates.sort(key=lambda rp: -rp[0]["cpu_s"])
    result.findings.extend(
        _churn_finding(row, proc, inp) for row, proc in candidates[:CHURN_MAX_FINDINGS]
    )
    rows = [row for row, _ in candidates]
    attempts = bs.wakeup_attempts()
    result.metrics.update(
        {
            "on_battery_s": on_batt_s,
            "candidates": len(rows),
            "suspend_attempts": attempts,
            "battery_specific": sum(1 for r in rows if r["battery_specific"]),
        },
    )
    if attempts:
        result.notes.append(
            "Suspend attempts are the sum of batterystats 'All wakeup reasons' "
            "counts (aborts plus wakeups) since the last charge.",
        )
    result.notes.append(
        "modelled_cpu_mah splits the UID's modelled CPU mAh by CPU time; it "
        "misses the cost of lost sleep and is not additive across causes.",
    )
    result.add_table("processes", rows)
    return result
