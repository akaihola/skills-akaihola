"""Suspend attempts in the kernel log, and the suspend service's counters.

Android suspends the SoC whenever no wakelock is held. The kernel logs each
attempt between ``PM: suspend entry`` and ``PM: suspend exit``. An attempt
either reaches suspend and is later resumed by an interrupt (``Resume caused
by IRQ 41, WLAN_CE_2``), or it aborts because a wakeup source became active, a
task refused to freeze or a driver failed to suspend (``Abort: ...``, the same
text batterystats lists as a wakeup reason). The suspend service retries an
aborted attempt with a growing back-off, so a phone that aborts after every
resume stays awake much longer per wake.

The kernel log is a ring buffer of a few minutes, and its printk clock stops
while the SoC is suspended: kernel seconds are awake seconds, not wall time.
Wall-clock times come from stamps inside the log where it has them: audit
records carry epoch seconds, some Android kernels print the UTC time on
suspend entry and exit, and some vendor drivers prefix lines with a UTC time
of day. healthd's battery lines show when a charger was plugged in; the phone
rarely tries to suspend on USB power, so the analysis leaves out the attempts
made on a charger.

On phones with ``ro.logd.kernel=true`` dumpstate writes the kernel log as
``logcat -b kernel`` instead of dmesg; :func:`parse_kernel_log` reads both.

``suspend_control_internal`` (the suspend service) keeps since-boot counters
of successful and failed attempts and of every wakeup reason. The rate of
aborted attempts on battery is reported by ``wakeup_reasons.suspend_aborts``;
this module adds the log sample's and the since-boot figures as metrics.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING

from .common import iter_logcat, pct
from .model import Context, Finding, Result, SkipError, analyzer

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .model import Windows
    from .source import Text

# Kernel messages that precede an abort are collected from this many seconds
# before the line that decides the attempt. One second covers the previous
# resume path and the whole aborted attempt (about 0.1-0.3 s) but not the
# attempt before it, which starts at least the 100 ms back-off earlier.
LEAD_S = 1.0
# An abort class needs this many attempts, and the baseline this many attempts
# that reached suspend, before a co-occurrence percentage is meaningful.
MIN_CLASS_ATTEMPTS = 10
# A message counts as an abort precursor when it precedes nearly every attempt
# of an abort class (95 %, allowing a lost line in a busy ring buffer) and is
# at least 30 points rarer before attempts that reached suspend. Messages that
# are part of the suspend path itself appear in both and are filtered out.
PRECURSOR_MIN_CLASS_PCT = 95.0
PRECURSOR_MIN_LIFT_PCT = 30.0
MAX_PRECURSOR_FINDINGS = 3
# After an aborted attempt the suspend service sleeps a back-off (AOSP
# SystemSuspend: 100 ms, doubled per abort in a row) and then waits until no
# wakelock is held. Only the back-off is caused by the abort: a gap counts as
# back-off up to 10 % above the estimated back-off for its position, and a
# position seen fewer than 3 times is capped at twice the previous one.
BACKOFF_TOLERANCE = 0.1
MIN_BACKOFF_GAPS = 3
# In a logcat-form kernel log a step back in time, or forward by more than an
# hour, is a clock change (or a long sleep), not time the kernel was awake.
LOGCAT_CLOCK_STEP_S = 3600.0
TEMPLATE_MAX_CHARS = 120
# A UTC offset is estimated from the capture time only when the log ends
# within this distance of a quarter-hour offset.
OFFSET_TOLERANCE = timedelta(minutes=5)
QUARTER_HOUR = timedelta(minutes=15)
MAX_UTC_OFFSET = timedelta(hours=14)
SECONDS_PER_MINUTE = 60.0

_PRINTK_RE = re.compile(
    r"^(?:<\d+>)?\[\s*(?P<t>\d+\.\d+)\](?:\[\s*[TC]\d+\])?\s?(?P<msg>.*)$",
)
# Some vendor kernels print the CPU and PID before the message:
# "c2   1032 healthd: battery l=50 ...".
_CPU_PID_RE = re.compile(r"^c\d+\s+\d+ ")
_AUDIT_RE = re.compile(r"\baudit\((?P<epoch>\d{9,11})\.(?P<ms>\d{3}):\d+\)")
_PM_UTC_RE = re.compile(
    r"PM: suspend (?:entry|exit) "
    r"(?P<stamp>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.(?P<frac>\d+))? UTC",
)
# Qualcomm WLAN driver prefix: "[kworke][0x1a2b3c4d][10:00:00.250000] wlan:"
_TOD_RE = re.compile(
    r"\]\[0x[0-9a-f]+\]\[(?P<h>\d\d):(?P<m>\d\d):(?P<s>\d\d(?:\.\d+)?)\]",
)
_HEALTHD_RE = re.compile(
    r"healthd: battery l=(?P<level>-?\d+) v=(?P<mv>-?\d+) t=(?P<temp>-?[\d.]+) "
    r"h=(?P<health>\d+) st=(?P<status>\d+)(?P<rest>.*?) chg=(?P<chg>[a-z]*)",
)
_HEALTHD_CURRENT_RE = re.compile(r"\bc=(-?\d+)")

_ENTRY_RE = re.compile(r"PM: suspend entry\b")
_EXIT_RE = re.compile(r"PM: suspend exit\b")
_ABORT_RE = re.compile(r"\bAbort: (?P<reason>.+?)\s*$")
_WAKE_SOURCE_RE = re.compile(
    r"(?P<reason>(?:Pending Wakeup Sources|Last active Wakeup Source"
    r"|active wakeup source): ?.*?)\s*$",
    re.IGNORECASE,
)
_ABORT_HINT_RE = re.compile(
    r"Freezing of tasks (?:aborted|failed)|Some devices failed to suspend"
    r"|suspend of devices failed|failed to suspend|wakeup pending"
    r"|Abort CPU freeze|Error taking CPU|dpm_run_callback\(\)|aborting suspend",
    re.IGNORECASE,
)
_RESUME_RE = re.compile(
    r"Resume caused by (?:IRQ (?P<irq>\d+), (?P<name>\S.*?)|(?P<other>.+?))\s*$",
)
_IRQ_WAKEUP_RE = re.compile(
    r"pm_system_irq_wakeup: (?P<irq>\d+) triggered (?P<name>\S+)",
)
_DEEP_RE = re.compile(
    r"Disabling non-boot CPUs|PM: suspend-to-idle|suspend ns:"
    r"|PM: resume from suspend-to-idle",
)
# Lines that belong to the suspend path itself appear around every attempt and
# say nothing about why one aborted. "CPUn is up" is kept as the one marker of
# CPU hotplug, a suspected abort trigger on some kernels.
_MACHINERY_RE = re.compile(
    r"^(?:PM: |Freezing |OOM killer |Restarting tasks|Suspending console"
    r"|done\.$|Abort: |Resume caused by|pm_system_irq_wakeup|suspend ns:"
    r"|resume cycles:|Disabling non-boot|Enabling non-boot|Wakeup pending"
    r"|Non-boot CPUs|CPU\d+: shutdown|psci: CPU\d+ killed|Detected \w+ I-cache"
    r"|CPU\d+: Booted secondary|arch_timer: CPU\d+|IRQ \d+: no longer affine)",
)
_VENDOR_PREFIX_RE = re.compile(r"^\[[^\]]*\]\[0x[0-9a-f]+\]\[[\d:.]+\]\s*")
_MAC_RE = re.compile(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", re.IGNORECASE)
_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
# Hex numbers, and bare hex strings of 8+ characters with a digit and a letter.
_HEX_RE = re.compile(
    r"\b0x[0-9a-f]+\b|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{8,}\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d+")

_SECTION_RE = re.compile(r"^-+ ?(?P<name>[A-Za-z ]+?) ?-+$|^(?P<label>[A-Z][\w ]+):$")
_STAT_RE = re.compile(r"^\s*(?P<key>[a-z][a-z_ ]*?):\s*(?P<value>-?\d+)(?: ms)?\s*$")
_LAST_FAILURE_RE = re.compile(r"^\s*(?P<key>last_failed_\w+):\s*(?P<value>\S.*?)\s*$")
_WAKEUP_INFO_RE = re.compile(r"WakeupInfo\{name: (?P<name>.+), count: (?P<count>\d+)\}")


@dataclass(frozen=True)
class KernelLine:
    """One line of the kernel log."""

    pos: int  # position in the list of parsed lines
    index: int  # zero-based line index in the source text, for citations
    t: float  # kernel seconds; the clock stops while suspended
    msg: str


@dataclass
class KernelLog:
    """The kernel log of a capture, in dmesg or logcat form."""

    text: Text
    lines: list[KernelLine]
    skipped: int  # non-empty lines that are not kernel-log lines
    logcat: bool = False  # written by logd as 'logcat -b kernel'


@dataclass(frozen=True)
class HealthdSample:
    """One ``healthd: battery ...`` line (AOSP BatteryMonitor)."""

    line: KernelLine
    level: int
    temp_c: float
    health: int  # BatteryManager.BATTERY_HEALTH_*: 2 good, 3 overheat, 7 cold
    status: int  # BatteryManager.BATTERY_STATUS_*: 2 charging, 3 discharging
    current_ua: int | None
    chg: str  # "a" AC, "u" USB, "w" wireless, "d" dock; empty on battery

    @property
    def plugged(self) -> bool:
        """Whether any charger was connected."""
        return bool(self.chg)


@dataclass
class Attempt:
    """One suspend attempt, from ``PM: suspend entry`` to ``PM: suspend exit``."""

    entry: KernelLine
    exit: KernelLine | None = None
    outcome: str = "unknown"  # "deep", "abort" or "unknown"
    reason: str = ""  # abort reason, or the IRQ that resumed a deep suspend
    decision: KernelLine | None = None  # first line that decided the outcome
    resume: KernelLine | None = None  # first line naming the resume IRQ
    on_battery: bool | None = None
    # Message templates logged shortly before the decision, with the line
    # nearest to it.
    templates: dict[str, KernelLine] = field(default_factory=dict)
    # Parser state: the first abort and deep-suspend markers, and how specific
    # the reason found so far is (lower is better).
    abort_line: KernelLine | None = field(default=None, repr=False)
    abort_rank: int = field(default=9, repr=False)
    deep_line: KernelLine | None = field(default=None, repr=False)
    resume_reason: str = field(default="", repr=False)
    resume_rank: int = field(default=9, repr=False)


def parse_kernel_log(text: Text, reference: datetime) -> KernelLog:
    """Parse a dmesg kernel log, or the logcat form dumpstate writes instead.

    With ``ro.logd.kernel=true`` dumpstate prints ``logcat -b kernel``, whose
    times are logd's wall-clock estimates (``reference`` supplies the year).
    logd moves its clock forward by the time suspended when it reads the UTC
    stamp of ``PM: suspend exit``; removing that jump, and clock changes,
    gives back kernel seconds that exclude time suspended, as printk's do.
    """
    lines: list[KernelLine] = []
    for i, raw in enumerate(text.lines):
        if m := _PRINTK_RE.match(raw):
            lines.append(KernelLine(len(lines), i, float(m["t"]), _message(m["msg"])))
    nonempty = sum(1 for raw in text.lines if raw.strip())
    if lines:
        return KernelLog(text, lines, nonempty - len(lines))
    entries = list(iter_logcat(text.text, reference, first_line=0))
    asleep = previous = 0.0
    for e in entries:
        wall_s = (e.ts - entries[0].ts).total_seconds()
        # logd may split "healthd: battery ..." into a tag and a message.
        msg = _message(f"{e.tag}: {e.message}" if e.tag else e.message)
        gap = wall_s - previous
        if _EXIT_RE.search(msg) or gap < 0 or gap > LOGCAT_CLOCK_STEP_S:
            asleep += gap
        previous = wall_s
        lines.append(KernelLine(len(lines), e.lineno, wall_s - asleep, msg))
    return KernelLog(text, lines, nonempty - len(lines), logcat=True)


def _message(msg: str) -> str:
    return _CPU_PID_RE.sub("", msg, count=1)


def load_kernel_log(ctx: Context) -> KernelLog:
    """Return the kernel log, parsed once per run; skip when there is none."""
    text = ctx.sources.get("dmesg")
    if text is None:
        msg = "no kernel log"
        raise SkipError(msg)
    return ctx.sources.memo(
        "kernel_log",
        lambda: parse_kernel_log(text, ctx.windows.log_reference()),
    )


def parse_healthd(lines: Iterable[KernelLine]) -> list[HealthdSample]:
    """Return every healthd battery sample in kernel-log order."""
    samples = []
    for kl in lines:
        if "healthd:" not in kl.msg or not (m := _HEALTHD_RE.search(kl.msg)):
            continue
        current = _HEALTHD_CURRENT_RE.search(m["rest"])
        samples.append(
            HealthdSample(
                line=kl,
                level=int(m["level"]),
                temp_c=float(m["temp"]),
                health=int(m["health"]),
                status=int(m["status"]),
                current_ua=int(current[1]) if current else None,
                chg=m["chg"],
            ),
        )
    return samples


def driver_tod_s(msg: str) -> float | None:
    """Return the UTC seconds of day stamped on a Qualcomm WLAN driver line."""
    if m := _TOD_RE.search(msg):
        return int(m["h"]) * 3600 + int(m["m"]) * 60 + float(m["s"])
    return None


def template(msg: str) -> str:
    """Return ``msg`` with numbers, addresses and vendor prefixes normalised."""
    s = _VENDOR_PREFIX_RE.sub("", msg)
    s = _MAC_RE.sub("<mac>", s)
    s = _IPV4_RE.sub("<ip>", s)
    s = _HEX_RE.sub("<hex>", s)
    s = _NUMBER_RE.sub("N", s)
    return " ".join(s.split())[:TEMPLATE_MAX_CHARS]


# ---------------------------------------------------------------- wall clock


@dataclass(frozen=True)
class _Anchor:
    t: float
    utc: datetime | None
    tod_s: float | None  # UTC seconds of the day when the stamp has no date


# Wall-clock stamps of the log and the reference that dates time-of-day stamps.
Clock = tuple[list[_Anchor], tuple[float, datetime]]


def find_wall_anchors(lines: Iterable[KernelLine]) -> list[_Anchor]:
    """Return the wall-clock stamps found in the kernel log."""
    anchors = []
    for kl in lines:
        if m := _AUDIT_RE.search(kl.msg):
            stamp = int(m["epoch"]) + int(m["ms"]) / 1000
            utc = datetime.fromtimestamp(stamp, tz=UTC).replace(tzinfo=None)
            anchors.append(_Anchor(kl.t, utc, None))
        elif m := _PM_UTC_RE.search(kl.msg):
            micro = int((m["frac"] or "0")[:6].ljust(6, "0"))
            utc = datetime.strptime(m["stamp"], "%Y-%m-%d %H:%M:%S")
            utc += timedelta(microseconds=micro)
            anchors.append(_Anchor(kl.t, utc, None))
        elif (tod := driver_tod_s(kl.msg)) is not None:
            anchors.append(_Anchor(kl.t, None, tod))
    return anchors


def _resolve(anchor: _Anchor, ref_t: float, ref_utc: datetime) -> datetime:
    """Give a time-of-day anchor the date that puts it nearest the reference."""
    if anchor.utc is not None:
        return anchor.utc
    approx = ref_utc + timedelta(seconds=anchor.t - ref_t)
    midnight = datetime.combine(approx.date(), time())
    candidates = [
        midnight + timedelta(days=d, seconds=anchor.tod_s or 0.0) for d in (-1, 0, 1)
    ]
    return min(candidates, key=lambda c: abs(c - approx))


def _offset(
    windows: Windows,
    end_utc: datetime | None,
) -> tuple[timedelta | None, bool]:
    """Return the UTC offset and whether it was estimated from the capture time."""
    if (offset := windows.offset()) is not None:
        return offset, False
    if windows.dump_time is None or end_utc is None:
        return None, False
    diff = windows.dump_time - end_utc
    estimate = round(diff / QUARTER_HOUR) * QUARTER_HOUR
    if abs(diff - estimate) <= OFFSET_TOLERANCE and abs(estimate) <= MAX_UTC_OFFSET:
        return estimate, True
    return None, False


def _stamp(value: datetime) -> str:
    return value.isoformat(sep=" ", timespec="seconds")


def _reference(
    anchors: list[_Anchor],
    lines: list[KernelLine],
    windows: Windows,
) -> tuple[float, datetime] | None:
    """Return a (kernel seconds, UTC) pair that dates time-of-day anchors."""
    full = next((a for a in anchors if a.utc is not None), None)
    if full is not None and full.utc is not None:
        return full.t, full.utc
    if windows.dump_time is not None and (offset := windows.offset()) is not None:
        return lines[-1].t, windows.dump_time - offset
    return None


def _wall_at(clock: Clock, t: float) -> datetime | None:
    """Return the wall time at kernel time ``t`` from the last stamp before it.

    Only valid when the phone did not suspend in between, as around a plug-in.
    """
    anchors, ref = clock
    before = [a for a in anchors if a.t <= t]
    if not before:
        return None
    return _resolve(before[-1], *ref) + timedelta(seconds=t - before[-1].t)


def wall_clock(
    lines: list[KernelLine],
    windows: Windows,
    plug_t: float | None,
    result: Result,
) -> Clock | None:
    """Add the wall-clock coverage of the kernel log to the result metrics.

    Between two stamps, wall time minus kernel time is the time spent
    suspended. The plug-in, if any, gets a wall time from the last stamp
    before it (the phone is awake around a plug-in). Returns the stamps for
    later conversions, or None when they cannot be dated.
    """
    anchors = find_wall_anchors(lines)
    result.metrics["wall_clock_anchors"] = len(anchors)
    if not anchors:
        result.notes.append(
            "The kernel log has no wall-clock stamps; its coverage is known only "
            "in kernel seconds, which stop while the phone is suspended.",
        )
        return None
    ref = _reference(anchors, lines, windows)
    if ref is None:
        result.metrics["log_first_utc_time_of_day"] = _tod(anchors[0].tod_s)
        result.metrics["log_last_utc_time_of_day"] = _tod(anchors[-1].tod_s)
        result.notes.append("Wall-clock stamps in the kernel log have no date.")
        return None
    clock = (anchors, ref)
    points = {
        "log_first": _resolve(anchors[0], *ref),
        "log_last": _resolve(anchors[-1], *ref),
    }
    wall_s = (points["log_last"] - points["log_first"]).total_seconds()
    kernel_s = anchors[-1].t - anchors[0].t
    result.metrics.update(
        log_wall_span_s=round(wall_s, 1),
        log_kernel_span_between_anchors_s=round(kernel_s, 1),
        log_suspended_s=round(max(wall_s - kernel_s, 0.0), 1),
    )
    if plug_t is not None and (plug_utc := _wall_at(clock, plug_t)):
        points["plug_in"] = plug_utc
        result.metrics["log_wall_s_before_plug_in"] = round(
            (plug_utc - points["log_first"]).total_seconds(),
            1,
        )
        result.metrics["log_kernel_s_before_plug_in"] = round(plug_t - anchors[0].t, 1)
    offset, estimated = _offset(windows, _wall_at(clock, lines[-1].t))
    for name, value in points.items():
        result.metrics[f"{name}_utc"] = _stamp(value)
        if offset is not None:
            result.metrics[f"{name}_local"] = _stamp(value + offset)
    if offset is not None:
        result.metrics["utc_offset_estimated"] = estimated
    if estimated:
        result.notes.append(
            "The UTC offset was estimated from the capture time and the end of "
            "the kernel log (rounded to 15 minutes).",
        )
    return clock


def _tod(seconds: float | None) -> str:
    whole = int(seconds or 0)
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d}"


# ------------------------------------------------------------------- attempts


def _mark_abort(attempt: Attempt, kl: KernelLine) -> None:
    """Record an abort marker; the ``Abort:`` line names the reason best."""
    msg = kl.msg
    if m := _ABORT_RE.search(msg):
        rank, reason = 0, m["reason"]
    elif m := _WAKE_SOURCE_RE.search(msg):
        rank, reason = 1, m["reason"]
    elif _ABORT_HINT_RE.search(msg):
        rank, reason = 2, template(msg)
    else:
        return
    if attempt.abort_line is None:
        attempt.abort_line = kl
    if rank < attempt.abort_rank:
        attempt.abort_rank = rank
        attempt.reason = " ".join(reason.split())[:TEMPLATE_MAX_CHARS]


def _mark_deep(attempt: Attempt, kl: KernelLine) -> None:
    msg = kl.msg
    if m := _RESUME_RE.search(msg):
        rank = 0
        name = f"{m['irq']} {m['name']}" if m["irq"] else m["other"]
    elif m := _IRQ_WAKEUP_RE.search(msg):
        rank, name = 1, f"{m['irq']} {m['name']}"
    elif _DEEP_RE.search(msg):
        rank, name = 9, ""
    else:
        return
    if attempt.deep_line is None:
        attempt.deep_line = kl
    if name and attempt.resume is None:
        attempt.resume = kl
    if name and rank < attempt.resume_rank:
        attempt.resume_rank = rank
        attempt.resume_reason = name


def _finish(attempt: Attempt) -> None:
    if attempt.abort_line is not None:
        attempt.outcome, attempt.decision = "abort", attempt.abort_line
    elif attempt.deep_line is not None:
        attempt.outcome, attempt.decision = "deep", attempt.deep_line
        attempt.reason = attempt.resume_reason or "unknown IRQ"


def parse_attempts(lines: list[KernelLine]) -> tuple[list[Attempt], int]:
    """Split the log into suspend attempts; also count exits without an entry."""
    attempts: list[Attempt] = []
    current: Attempt | None = None
    orphan_exits = 0
    for kl in lines:
        if _ENTRY_RE.search(kl.msg):
            if current is not None:
                _finish(current)
            current = Attempt(kl)
            attempts.append(current)
        elif current is None:
            orphan_exits += 1 if _EXIT_RE.search(kl.msg) else 0
        elif _EXIT_RE.search(kl.msg):
            current.exit = kl
            _finish(current)
            current = None
        else:
            _mark_abort(current, kl)
            _mark_deep(current, kl)
    if current is not None:
        _finish(current)
    return attempts, orphan_exits


def _assign_power(attempts: list[Attempt], samples: list[HealthdSample]) -> None:
    """Mark each attempt on battery or plugged in from the latest healthd sample.

    healthd logs a sample on every charger change, but on battery it may log
    nothing else for many minutes, so the oldest sample left in the ring
    buffer can be the plug-in itself. Attempts before the first sample are
    therefore on battery when that sample is, and of unknown state otherwise.
    """
    if not samples:
        return
    i = -1
    for attempt in attempts:
        while i + 1 < len(samples) and samples[i + 1].line.pos <= attempt.entry.pos:
            i += 1
        if i >= 0 or not samples[0].plugged:
            attempt.on_battery = not samples[max(i, 0)].plugged


def _battery_spans(
    samples: list[HealthdSample],
    start: float,
    end: float,
) -> list[tuple[float, float]]:
    """Return the kernel-time stretches of the log not known to be on a charger."""
    spans = []
    since: float | None = start
    for s in samples:
        if s.plugged and since is not None:
            spans.append((since, s.line.t))
            since = None
        elif not s.plugged and since is None:
            since = s.line.t
    if since is not None:
        spans.append((since, end))
    return spans


def _collect_templates(attempts: list[Attempt], lines: list[KernelLine]) -> None:
    """Gather the message templates logged shortly before each decision.

    The window is the ``LEAD_S`` seconds before the deciding line, but never
    earlier than the previous attempt's deciding line, so every line belongs
    to at most one attempt and the pass stays linear.
    """
    floor = -1
    for attempt in attempts:
        if attempt.decision is None:
            continue
        limit = attempt.decision.t - LEAD_S
        pos = attempt.decision.pos - 1
        while pos > floor and lines[pos].t >= limit:
            msg = _VENDOR_PREFIX_RE.sub("", lines[pos].msg.strip())
            if msg and not _MACHINERY_RE.match(msg):
                attempt.templates.setdefault(template(msg), lines[pos])
            pos -= 1
        floor = attempt.decision.pos


# -------------------------------------------------------------------- metrics


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _backoff_floors(by_position: dict[int, list[float]]) -> dict[int, float]:
    """Estimate the back-off after each number of aborts in a row.

    A gap is the back-off plus any time wakelocks or active wakeup sources
    held the next attempt off, so the shortest gap at a position is the best
    estimate. A rarely seen position is also capped at twice the previous
    one, as the AOSP back-off doubles.
    """
    floors: dict[int, float] = {}
    for k in sorted(by_position):
        floor = min(by_position[k])
        if len(by_position[k]) < MIN_BACKOFF_GAPS and k - 1 in floors:
            floor = min(floor, 2 * floors[k - 1])
        floors[k] = floor
    return floors


def _timing(scope: list[Attempt], result: Result) -> None:
    """Add durations, back-off gaps, abort runs and per-wake awake time."""
    done = [a for a in scope if a.exit is not None]
    if len(done) < 2:  # ruff: ignore[magic-value-comparison] - a gap needs two attempts
        return
    gaps_after: dict[str, list[float]] = {"abort": [], "deep": []}
    by_position: dict[int, list[float]] = {}
    runs: Counter[int] = Counter()
    run = 0
    for prev, nxt in pairwise(done):
        if prev.exit is None or prev.outcome == "unknown":
            continue
        gap = nxt.entry.t - prev.exit.t
        gaps_after[prev.outcome].append(gap)
        if prev.outcome == "deep":
            run = 0
        else:
            run += 1
            by_position.setdefault(run, []).append(gap)
    # Count only runs bounded by two deep suspends: the run before the first
    # one may be cut off by the start of the ring buffer.
    run: int | None = None
    for attempt in done:
        if attempt.outcome == "deep":
            if run is not None:
                runs[run] += 1
            run = 0
        elif attempt.outcome == "abort" and run is not None:
            run += 1
    durations = {
        kind: [a.exit.t - a.entry.t for a in done if a.outcome == kind and a.exit]
        for kind in ("abort", "deep")
    }
    floors = _backoff_floors(by_position)
    backoff_s = sum(
        min(gap, floors[k] * (1 + BACKOFF_TOLERANCE))
        for k, gaps in by_position.items()
        for gap in gaps
    )
    window_s = (done[-1].exit.t if done[-1].exit else 0.0) - done[0].entry.t
    deep = [a for a in done if a.outcome == "deep" and a.decision]
    awake_per_wake = [
        nxt.decision.t - woke.t
        for cur, nxt in pairwise(deep)
        if nxt.decision and (woke := cur.resume or cur.decision)
    ]
    result.metrics.update(
        kernel_awake_window_s=round(window_s, 1),
        abort_attempts_s=round(sum(durations["abort"]), 1),
        abort_backoff_gaps_s=round(backoff_s, 1),
        abort_gaps_beyond_backoff_s=round(sum(gaps_after["abort"]) - backoff_s, 1),
        abort_overhead_pct=pct(sum(durations["abort"]) + backoff_s, window_s),
        median_abort_attempt_s=_median(durations["abort"]),
        median_deep_attempt_s=_median(durations["deep"]),
        median_gap_after_abort_s=_median(gaps_after["abort"]),
        median_gap_after_deep_s=_median(gaps_after["deep"]),
        median_awake_per_real_wake_s=_median(awake_per_wake),
        mean_awake_per_real_wake_s=(
            round(statistics.fmean(awake_per_wake), 3) if awake_per_wake else None
        ),
    )
    result.add_table(
        "backoff_by_abort_position",
        [
            {
                "aborts_in_a_row": k,
                "n": len(v),
                "median_gap_s": _median(v),
                "backoff_s": round(floors[k], 3),
            }
            for k, v in sorted(by_position.items())
        ],
    )
    result.add_table(
        "aborts_between_deep_suspends",
        [{"aborts": k, "times": v} for k, v in sorted(runs.items())],
    )


@dataclass(frozen=True)
class _CoRow:
    """How often one message template precedes the attempts of one abort class."""

    abort_reason: str
    template: str
    class_attempts: int
    with_template: int
    deep_with_template: int
    deep_attempts: int
    without_template: int

    @property
    def class_pct(self) -> float:
        return 100 * self.with_template / self.class_attempts

    @property
    def deep_pct(self) -> float:
        return 100 * self.deep_with_template / max(self.deep_attempts, 1)

    @property
    def lift(self) -> float:
        return self.class_pct - self.deep_pct

    def row(self) -> dict:
        return {
            "abort_reason": self.abort_reason,
            "template": self.template,
            "class_attempts": self.class_attempts,
            "with_template": self.with_template,
            "class_pct": round(self.class_pct, 1),
            "deep_attempts_with_template": self.deep_with_template,
            "deep_pct": round(self.deep_pct, 1) if self.deep_attempts else None,
            "attempts_without_template": self.without_template,
            "class_attempts_without_template": self.class_attempts - self.with_template,
        }


def _cooccurrence(scope: list[Attempt], result: Result) -> list[_CoRow]:
    """Tabulate templates before aborts and return the precursor candidates."""
    deep = [a for a in scope if a.outcome == "deep"]
    aborts = [a for a in scope if a.outcome == "abort"]
    in_deep = Counter(t for a in deep for t in a.templates)
    in_abort = Counter(t for a in aborts for t in a.templates)
    result.add_table(
        "messages_before_aborts",
        [
            {
                "template": t,
                "abort_attempts": n,
                "abort_pct": pct(n, len(aborts)),
                "deep_attempts": in_deep[t],
                "deep_pct": pct(in_deep[t], len(deep)),
            }
            for t, n in in_abort.most_common()
        ],
    )
    members: dict[str, Counter[str]] = {}
    for a in aborts:
        members.setdefault(a.reason, Counter()).update(a.templates.keys())
    classes = Counter(a.reason for a in aborts)
    rows = [
        _CoRow(
            abort_reason=reason,
            template=t,
            class_attempts=classes[reason],
            with_template=k,
            deep_with_template=in_deep[t],
            deep_attempts=len(deep),
            without_template=len(aborts) + len(deep) - in_abort[t] - in_deep[t],
        )
        for reason, counter in members.items()
        if classes[reason] >= MIN_CLASS_ATTEMPTS
        for t, k in counter.items()
        if 100 * k / classes[reason] >= PRECURSOR_MIN_CLASS_PCT / 2
    ]
    rows.sort(key=lambda r: (-r.lift, r.abort_reason, r.template))
    result.add_table("abort_cooccurrence", [r.row() for r in rows])
    if len(deep) < MIN_CLASS_ATTEMPTS:
        return []
    return [
        r
        for r in rows
        if r.class_pct >= PRECURSOR_MIN_CLASS_PCT and r.lift >= PRECURSOR_MIN_LIFT_PCT
    ]


def _precursor_findings(
    candidates: list[_CoRow],
    scope: list[Attempt],
    text: Text,
) -> list[Finding]:
    """Merge candidate rows per template into at most a few findings."""
    by_template: dict[str, list[_CoRow]] = {}
    for row in candidates:
        by_template.setdefault(row.template, []).append(row)
    findings = []
    for number, (tmpl, rows) in enumerate(by_template.items(), start=1):
        if number > MAX_PRECURSOR_FINDINGS:
            break
        first = rows[0]
        classes = " and ".join(
            f"{r.with_template} of {r.class_attempts} '{r.abort_reason}' aborts"
            for r in rows
        )
        never = [
            f"'{r.abort_reason}'" for r in rows if r.with_template == r.class_attempts
        ]
        never_text = (
            f" None of the {first.without_template} attempts without it aborted "
            f"with {' or '.join(never)}."
            if never
            else ""
        )
        example = next(
            (
                a
                for a in scope
                if a.reason == first.abort_reason and tmpl in a.templates
            ),
            None,
        )
        evidence = [
            text.evidence(kl.index)
            for kl in (
                (example.templates[tmpl], example.decision)
                if example is not None and example.decision is not None
                else ()
            )
        ]
        findings.append(
            Finding(
                id=f"kernel_suspend.abort-precursor-{number}",
                title=f"Suspend aborts follow the kernel message '{tmpl}'",
                symptom="battery",
                severity="medium",
                basis="measured",
                window="log_coverage",
                summary=(
                    f"In the kernel-log sample the message '{tmpl}' was logged in "
                    f"the {LEAD_S:g} s before {classes}, but before only "
                    f"{first.deep_with_template} of {first.deep_attempts} attempts "
                    f"that reached suspend ({first.deep_pct:.0f} %).{never_text} "
                    "The co-occurrence is measured; that the event causes the "
                    "abort is inferred."
                ),
                metrics={
                    "template": tmpl,
                    "abort_reason": first.abort_reason,
                    "class_pct": round(first.class_pct, 1),
                    "deep_pct": round(first.deep_pct, 1),
                    "attempts_without_template": first.without_template,
                },
                evidence=evidence,
                recommendation=(
                    "Treat this kernel event as the leading suspect for the abort "
                    "class and include the co-occurrence counts in a bug report "
                    "to the device or kernel vendor, with a bugreport attached. "
                    "It is not something an app setting can fix."
                ),
                followups=[
                    (
                        "Check that the same pattern holds in a second bugreport "
                        "taken right after 30 minutes of screen-off use on battery."
                    ),
                    (
                        "Compare with the since-charge 'Abort:' wakeup reasons in "
                        "batterystats to see how much of the period this class "
                        "covers."
                    ),
                ],
            ),
        )
    return findings


def _scope(
    attempts: list[Attempt],
    samples: list[HealthdSample],
    result: Result,
) -> list[Attempt]:
    plugged = sum(1 for a in attempts if a.on_battery is False)
    unknown = sum(1 for a in attempts if a.on_battery is None)
    if unknown and not samples:
        result.notes.append(
            "The kernel log has no healthd battery lines, so the charger state is "
            "unknown and all suspend attempts are analysed.",
        )
    elif unknown:
        result.notes.append(
            f"{unknown} suspend attempts come before the first healthd battery "
            "line, which shows a charger. healthd can stay silent on battery for "
            "many minutes, so that line may be the plug-in itself; these attempts "
            "are analysed with an unknown charger state.",
        )
        result.metrics["attempts_charger_unknown"] = unknown
    if plugged:
        result.notes.append(
            f"{plugged} suspend attempts started while a charger was "
            "connected and are left out.",
        )
    result.metrics["attempts_while_plugged"] = plugged
    return [a for a in attempts if a.on_battery is not False]


def _power_metrics(samples: list[HealthdSample], result: Result) -> None:
    for prev, cur in pairwise(samples):
        if prev.plugged != cur.plugged:
            key = "plug_in_kernel_s" if cur.plugged else "unplug_kernel_s"
            result.metrics.setdefault(key, round(cur.line.t, 3))
    result.metrics["healthd_samples"] = len(samples)


def _outcome_metrics(scope: list[Attempt], orphan_exits: int, m: dict) -> None:
    outcomes = Counter(a.outcome for a in scope)
    deep, aborts = outcomes["deep"], outcomes["abort"]
    m.update(
        suspend_attempts=len(scope),
        deep_suspends=deep,
        aborted_attempts=aborts,
        unknown_outcome_attempts=outcomes["unknown"],
        attempts_without_exit=sum(1 for a in scope if a.exit is None),
        exits_without_entry_at_log_start=orphan_exits,
        abort_share_pct=pct(aborts, aborts + deep),
        aborts_per_deep_resume=round(aborts / deep, 2) if deep else None,
    )


def _resume_rate(
    scope: list[Attempt],
    samples: list[HealthdSample],
    lines: list[KernelLine],
    clock: Clock | None,
    m: dict,
) -> None:
    """Add deep resumes per wall minute off the charger.

    Resumes and wall time are counted over the same stretches: between the
    first and last wall-clock stamp, and not known to be on a charger.
    """
    if clock is None:
        return
    anchors = clock[0]
    resumes = [
        (a.resume or a.decision or a.entry).t for a in scope if a.outcome == "deep"
    ]
    wall_s, count = 0.0, 0
    for lo, hi in _battery_spans(samples, lines[0].t, lines[-1].t):
        lo, hi = max(lo, anchors[0].t), min(hi, anchors[-1].t)
        start, end = _wall_at(clock, lo), _wall_at(clock, hi)
        if hi <= lo or start is None or end is None:
            continue
        wall_s += (end - start).total_seconds()
        count += sum(1 for t in resumes if lo <= t <= hi)
    if wall_s > 0 and count:
        m["deep_resumes_per_wall_min"] = round(count / (wall_s / SECONDS_PER_MINUTE), 1)


def _reason_tables(scope: list[Attempt], result: Result) -> None:
    reasons = Counter(a.reason for a in scope if a.outcome == "abort")
    result.add_table(
        "abort_reasons",
        [
            {"reason": r, "attempts": n, "pct_of_attempts": pct(n, len(scope))}
            for r, n in reasons.most_common()
        ],
    )
    resumes = Counter(a.reason for a in scope if a.outcome == "deep")
    result.add_table(
        "resume_reasons",
        [{"irq": r, "resumes": n} for r, n in resumes.most_common()],
    )


@analyzer("kernel_suspend", requires=("dmesg",), after=("windows",))
def kernel_suspend(ctx: Context) -> Result:
    """Classify the suspend attempts in the kernel log."""
    log = load_kernel_log(ctx)
    lines = log.lines
    if not lines:
        msg = "the kernel log has neither dmesg nor logcat-format lines"
        raise SkipError(msg)
    result = Result("kernel_suspend", window="log_coverage")
    result.metrics.update(
        kernel_log_lines=len(lines),
        log_first_kernel_s=round(lines[0].t, 3),
        log_last_kernel_s=round(lines[-1].t, 3),
        log_kernel_span_s=round(lines[-1].t - lines[0].t, 1),
    )
    if log.logcat:
        result.metrics["kernel_log_format"] = "logcat"
        result.notes.append(
            "The kernel log is in logcat form (ro.logd.kernel). Kernel seconds "
            "count from its first line and are rebuilt from logd's millisecond "
            "wall-clock times by removing the jump at each suspend exit.",
        )
    if log.skipped:
        result.notes.append(
            f"{log.skipped} kernel-log lines without a time stamp were skipped.",
        )
    samples = parse_healthd(lines)
    _power_metrics(samples, result)
    plug_t = result.metrics.get("plug_in_kernel_s")
    clock = wall_clock(lines, ctx.windows, plug_t, result)
    attempts, orphan_exits = parse_attempts(lines)
    _assign_power(attempts, samples)
    scope = _scope(attempts, samples, result)
    _outcome_metrics(scope, orphan_exits, result.metrics)
    _resume_rate(scope, samples, lines, clock, result.metrics)
    if not scope:
        result.notes.append(
            "No suspend attempts on battery in the kernel log: the phone stayed "
            "awake or on a charger for the whole log.",
        )
        return result
    _collect_templates(scope, lines)
    _reason_tables(scope, result)
    _timing(scope, result)
    candidates = _cooccurrence(scope, result)
    result.notes.append(
        "Kernel seconds exclude time suspended. Counts cover only the ring-buffer "
        "sample and are lower bounds for any longer period. The abort rate on "
        "battery is reported by wakeup_reasons; aborts_per_deep_resume and "
        "abort_overhead_pct give this sample's view of it.",
    )
    result.findings.extend(_precursor_findings(candidates, scope, log.text))
    return result


# ----------------------------------------------------------- suspend service


def parse_suspend_control(text: Text) -> tuple[dict[str, int | str], list[dict]]:
    """Return the counters and the wakeup-reason rows of the suspend service."""
    stats: dict[str, int | str] = {}
    wakeups: list[dict] = []
    block = ""
    for i, line in enumerate(text.lines):
        if m := _WAKEUP_INFO_RE.search(line):
            name = m["name"].strip()
            wakeups.append(
                {
                    "reason": name,
                    "count": int(m["count"]),
                    "kind": "abort" if name.startswith("Abort:") else "resume",
                    "ref": text.ref(i),
                },
            )
        elif m := _SECTION_RE.match(line.strip()):
            block = (m["name"] or m["label"] or "").strip().lower()
        elif block in {"suspend stats", "suspend info"} and (m := _STAT_RE.match(line)):
            key = "_".join(m["key"].split())
            stats.setdefault(key, int(m["value"]))
        elif m := _LAST_FAILURE_RE.match(line):
            stats.setdefault(m["key"], m["value"])
    return stats, wakeups


@analyzer("suspend_stats", requires=("suspend_control",), after=("windows",))
def suspend_stats(ctx: Context) -> Result:
    """Summarise the suspend service's since-boot counters and wakeup reasons."""
    text = ctx.sources.get("suspend_control")
    if text is None:
        msg = "no suspend_control_internal dump"
        raise SkipError(msg)
    stats, wakeups = parse_suspend_control(text)
    if not stats and not wakeups:
        msg = "suspend_control_internal has no 'Suspend Stats' or 'Wakeups' block"
        raise SkipError(msg)
    result = Result("suspend_stats", window="since_boot")
    m = result.metrics
    renames = {
        "suspend_attempts": "suspend_attempts",
        "success": "suspend_success",
        "fail": "suspend_fail",
        "failed_freeze": "failed_freeze",
        "failed_prepare": "failed_prepare",
        "failed_suspend": "failed_suspend",
        "failed_suspend_late": "failed_suspend_late",
        "failed_suspend_noirq": "failed_suspend_noirq",
        "total_suspend_time": "total_suspend_time_ms",
        "suspend_overhead": "suspend_overhead_ms",
        "failed_suspend_overhead": "failed_suspend_overhead_ms",
        "total_sleep_time_between_suspends": "sleep_between_suspends_ms",
        "new_backoffs": "new_backoffs",
        "backoff_continuations": "backoff_continuations",
        "short_suspends": "short_suspends",
        "last_failed_dev": "last_failed_dev",
        "last_failed_errno": "last_failed_errno",
        "last_failed_step": "last_failed_step",
    }
    for key, name in renames.items():
        if key in stats:
            m[name] = stats[key]
    success, fail = stats.get("success"), stats.get("fail")
    if isinstance(success, int) and isinstance(fail, int):
        m["fail_share_pct"] = pct(fail, success + fail)
    wakeups.sort(key=lambda w: -w["count"])
    resumes = sum(w["count"] for w in wakeups if w["kind"] == "resume")
    aborts = sum(w["count"] for w in wakeups if w["kind"] == "abort")
    if wakeups:
        m.update(wakeup_resumes=resumes, wakeup_aborts=aborts)
        m["aborts_per_resume"] = round(aborts / resumes, 2) if resumes else None
        result.add_table(
            "wakeup_reasons",
            [{k: w[k] for k in ("reason", "count", "kind", "ref")} for w in wakeups],
        )
    result.notes.append(
        "These counters run since boot and include time on a charger; "
        "batterystats gives the since-charge view, and wakeup_reasons reports "
        "the abort rate on battery.",
    )
    return result
