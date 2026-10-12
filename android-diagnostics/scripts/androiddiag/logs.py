"""Logs: what the log buffers cover, who floods them, and crashes, ANRs and reboots.

Log buffers are rings in logd's memory, so they hold only the current boot
(the previous boot's last lines are a separate read, ``logcat -L``). Each one
covers a different span (the main buffer can rotate in two minutes, the event
buffer may reach back half an hour), so every count from them is a lower bound
for its own window. The dropbox rate-limits low-priority tags and keeps a
fixed number of entries, and exit-info keeps a few records per app, so "none
found" there means "none in what was kept".

Logcat's threadtime format has no year; years are inferred relative to the
capture time. Lines written early in boot, before the clock was set, can carry
a stale date months back. A line stamped before the boot is such a line: it is
counted, but left out of buffer spans and per-minute counts, and
crash_anr_audit treats its crash as part of the boot.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, Any

from .batterystats import load_since_charge
from .common import iter_logcat
from .cpu import (
    MIN_ON_BATTERY_S,
    Row,
    charging_since,
    plug_note,
    power_state,
    result_table,
)
from .model import Context, Evidence, Finding, Result, SkipError, analyzer

if TYPE_CHECKING:
    from .common import LogLine
    from .model import Windows
    from .source import Text

# Log sources in the order they are read; logcat_all only stands in when
# none of the per-buffer dumps exist.
LOG_KEYS = ("logcat_system", "logcat_events", "logcat_radio")

# A tag writing this many lines in one minute is a burst worth a look.
SPAM_BURST_PER_MIN = 1000
# A tag averaging this many lines per minute over at least SPAM_MIN_SPAN_MIN
# minutes is sustained spam.
SPAM_SUSTAINED_PER_MIN = 100
SPAM_MIN_SPAN_MIN = 5.0
# Logging only costs battery that matters when logd and statsd together are
# modelled above this many mAh per hour on battery (reference: 0.16 mAh/h).
LOGGING_COST_MAH_PER_H = 1.0
LOGD_UID = 1036
STATSD_UID = 1066
# The same component logging this many WTFs ("what a terrible failure") in
# the event log is repeated churn worth a follow-up capture.
WTF_REPEAT_MIN = 20
# Framework event tags that are high-volume by design (CPU and memory stats
# batches, UI interaction events); they are counted but never called spam.
EXPECTED_VOLUME_TAGS = frozenset({"am_cpu", "am_pss", "sysui_multi_action"})
# Buffers covering less than this many minutes (often main, which rotates
# fast) are left out when choosing the window for the overall line rate.
RATE_MIN_SPAN_MIN = 10.0

# Crashes or ANRs of one process within this window, at least LOOP_MIN times,
# form a loop. Only loops newer than RECENT_DAYS before capture are findings.
LOOP_WINDOW = timedelta(hours=24)
LOOP_MIN = 3
RECENT_DAYS = 7
# Unexpected reboots in the boot-reason history this recent are findings.
REBOOT_RECENT_DAYS = 30
# Events in the first minutes after boot belong to the boot itself.
BOOT_PHASE = timedelta(minutes=5)
# A log line stamped this long before the boot was written before the clock
# was set (logd keeps only the current boot); the margin covers the boot
# time's own rounding.
STALE_STAMP_SLACK = timedelta(minutes=1)

_PCT = 100.0
_S_PER_H = 3600.0
_MARKER_RE = re.compile(r"^--------- (?:beginning of|switch to) (\S+)")
_DIGITS_RE = re.compile(r"\d+")
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_MAC_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
_TEMPLATE_LEN = 120
_AM_WTF_FIELDS = 6  # [user,pid,process,flags,tag,message]

_DROPBOX_ENTRY_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\S+)(?: \((.*)\))?\s*$",
)
_DROPBOX_FIELD_RE = re.compile(r"^(Process|Package|Foreground|Subject|Cmdline): (.*)$")
_NATIVE_NAME_RE = re.compile(r">>> (.+?) <<<")
_EXIT_HEAD_RE = re.compile(r"timestamp=(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)")
_EXIT_REASON_RE = re.compile(r"process=(\S+) reason=(\d+) \((.*?)\) subreason=")
_TOMB_TIME_RE = re.compile(r"^Timestamp: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
_TOMB_SIGNAL_RE = re.compile(r"^signal (\d+) \((\w+)\)")
_ANR_PID_RE = re.compile(r"^----- pid (\d+) at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
_ANR_CMD_RE = re.compile(r"^Cmd line: (.+)$")
_FATAL_SIGNAL_RE = re.compile(r"Fatal signal (\d+) \((\w+)\).*?pid (\d+) \((.*?)\)")
_JAVA_PROCESS_RE = re.compile(r"^Process: (\S+), PID: (\d+)")
_ANR_IN_RE = re.compile(r"^ANR in (\S+)")
_PROP_RE = re.compile(r"^\[([^\]]+)\]: \[(.*)$")

# Exit-info reasons (AOSP ApplicationExitInfo): 4 crash, 5 native crash, 6 ANR.
_EXIT_KINDS = {4: "crash", 5: "native", 6: "anr"}

# Boot reasons, checked in this order (AOSP bootstat reason strings).
_BOOT_REASON_KINDS = (
    ("battery", ("battery",)),
    ("thermal", ("thermal",)),
    (
        "unexpected",
        (
            "panic",
            "watchdog",
            "hard",
            "rescueparty",
            "abnormal",
            "longkey",
            "hw_reset",
            "kernel",
            "ramdump",
            "oem_",
        ),
    ),
    (
        "requested",
        (
            "userrequested",
            "shell",
            "adb",
            "ota",
            "recovery",
            "bootloader",
            "factory_reset",
            "fastboot",
            "reboot,",
        ),
    ),
)


# ----------------------------------------------------------------------------
# logcat volume


@dataclass
class _Volume:
    """Counters collected in one pass over every log source."""

    windows: Windows
    tags: Counter[str] = field(default_factory=Counter)
    # Lines per tag, minute and power state: the minute of the plug-in is
    # split, so a peak is labelled by when its lines were written.
    tag_minutes: Counter[tuple[str, datetime, str]] = field(default_factory=Counter)
    minutes: Counter[datetime] = field(default_factory=Counter)
    tag_pids: Counter[tuple[str, int, str]] = field(default_factory=Counter)
    templates: Counter[tuple[str, str]] = field(default_factory=Counter)
    first: dict[str, datetime] = field(default_factory=dict)
    last: dict[str, datetime] = field(default_factory=dict)
    wtf: dict[str, list[tuple[datetime, str, str]]] = field(
        default_factory=lambda: defaultdict(list),
    )
    buffers: list[Row] = field(default_factory=list)
    lines: Counter[str] = field(default_factory=Counter)
    unparsed: int = 0
    stale: int = 0

    def add(self, text: Text, line: LogLine) -> None:
        """Count one parsed line with a usable time stamp."""
        minute = line.ts.replace(second=0, microsecond=0)
        self.tags[line.tag] += 1
        state = power_state(self.windows, line.ts)
        self.tag_minutes[line.tag, minute, state] += 1
        self.minutes[minute] += 1
        self.tag_pids[line.tag, line.pid, line.uid or ""] += 1
        self.templates[line.tag, template(line.message)] += 1
        self.first.setdefault(line.tag, line.ts)
        self.last[line.tag] = line.ts
        if line.tag == "am_wtf":
            parts = line.message.strip("[] ").split(",", 5)
            if len(parts) == _AM_WTF_FIELDS:
                ref = text.ref(line.lineno - text.first_line)
                self.wtf[parts[4]].append((line.ts, template(parts[5]), ref))


def template(message: str) -> str:
    """Normalise a log message: MAC addresses, hex values and numbers are masked."""
    s = _MAC_RE.sub("MAC", message)
    s = _HEX_RE.sub("HEX", s)
    s = _DIGITS_RE.sub("N", s)
    return s[:_TEMPLATE_LEN]


def _log_sources(ctx: Context) -> list[tuple[str, Text]]:
    found = [(key, text) for key in LOG_KEYS if (text := ctx.sources.get(key))]
    if not found and (text := ctx.sources.get("logcat_all")):
        found = [("logcat_all", text)]
    return found


def _log_lines(ctx: Context, key: str) -> list[LogLine]:
    """Return the parsed lines of log source ``key`` in file order, parsed once."""

    def build() -> list[LogLine]:
        text = ctx.sources.get(key)
        if text is None:
            return []
        reference = ctx.windows.log_reference()
        return list(iter_logcat(text.text, reference, text.first_line))

    return ctx.sources.memo(f"logs.lines.{key}", build)


def _stale(ts: datetime | None, boot: datetime | None) -> bool:
    """Return whether a log stamp predates the boot (written before clock set)."""
    return bool(ts and boot and ts < boot - STALE_STAMP_SLACK)


def _markers(text: Text) -> list[tuple[int, str]]:
    return [
        (i, m[1])
        for i, line in enumerate(text.lines)
        if line.startswith("---------") and (m := _MARKER_RE.match(line))
    ]


def _scan_source(
    volume: _Volume,
    key: str,
    text: Text,
    lines: list[LogLine],
) -> None:
    """Count one source and record when each of its buffers starts.

    Lines stamped before the boot are counted but carry no usable time.
    """
    markers = _markers(text)
    pending = list(markers)
    starts: dict[str, datetime] = {}
    waiting: list[str] = []  # buffers whose first usable stamp is still ahead
    last_ts = None
    boot = volume.windows.boot_time
    for line in lines:
        index = line.lineno - text.first_line
        while pending and pending[0][0] < index:
            waiting.append(pending.pop(0)[1])
        volume.lines[key] += 1
        if _stale(line.ts, boot):
            volume.stale += 1
            continue
        for buffer in waiting:
            starts.setdefault(buffer, line.ts)
        waiting.clear()
        volume.add(text, line)
        last_ts = line.ts
    parsed = len(lines)
    nonblank = sum(1 for line in text.lines if line.strip())
    volume.unparsed += max(0, nonblank - parsed - len(markers))
    for buffer, start in starts.items():
        span = (last_ts - start).total_seconds() / 60 if last_ts else None
        volume.buffers.append(
            {
                "source": text.origin,
                "buffer": buffer,
                "start": start.isoformat(sep=" ", timespec="seconds"),
                "end": last_ts.isoformat(sep=" ", timespec="seconds")
                if last_ts
                else None,
                "span_min": round(span, 1) if span is not None else None,
                "lines": parsed if len(starts) == 1 else None,
            },
        )


def _tag_rows(volume: _Volume) -> list[Row]:
    peaks: dict[str, tuple[datetime, str, int]] = {}
    for (tag, minute, state), count in volume.tag_minutes.items():
        if count > peaks.get(tag, (minute, state, 0))[2]:
            peaks[tag] = (minute, state, count)
    top_pid: dict[str, tuple[int, str]] = {}
    for (tag, pid, uid), _ in volume.tag_pids.most_common():
        top_pid.setdefault(tag, (pid, uid))
    total = sum(volume.tags.values())
    rows: list[Row] = []
    for tag, lines in volume.tags.most_common():
        span_min = (volume.last[tag] - volume.first[tag]).total_seconds() / 60
        minute, state, peak = peaks[tag]
        rows.append(
            {
                "tag": tag,
                "lines": lines,
                "share_pct": round(lines / total * _PCT, 1),
                "peak_per_min": peak,
                "peak_minute": minute.isoformat(sep=" ", timespec="minutes"),
                "peak_during": state,
                "span_min": round(span_min, 1),
                "per_min": round(lines / max(span_min, 1.0), 1),
                "top_pid": top_pid[tag][0],
                "top_uid": top_pid[tag][1],
            },
        )
    return rows


def _logging_cost(ctx: Context) -> dict[str, float | None]:
    """Return the modelled mAh of logd and statsd since the last charge."""
    since = load_since_charge(ctx)
    power = since.power if since else None
    if power is None:
        return {}
    logd, statsd = power.uids.get(LOGD_UID), power.uids.get(STATSD_UID)
    cost: dict[str, float | None] = {
        "logd_modelled_mah": logd.total if logd else None,
        "statsd_modelled_mah": statsd.total if statsd else None,
    }
    on_battery_s = ctx.windows.on_battery_s or 0
    if on_battery_s >= MIN_ON_BATTERY_S and (logd or statsd):
        both = sum(row.total for row in (logd, statsd) if row)
        cost["logging_modelled_mah_per_h"] = round(both * _S_PER_H / on_battery_s, 3)
    return cost


def _spam_finding(rows: list[Row], cost: dict[str, Any]) -> Finding:
    per_h = cost.get("logging_modelled_mah_per_h")
    costly = per_h is not None and per_h >= LOGGING_COST_MAH_PER_H
    listed = ", ".join(
        f"{r['tag']} {r['per_min']:.0f}/min over {r['span_min']:.0f} min"
        for r in rows[:5]
    )
    cost_text = (
        f" logd and statsd were modelled at {per_h:.2f} mAh per hour on battery."
        if per_h is not None
        else " The cost of logging is unknown (no batterystats power model)."
    )
    return Finding(
        id="logcat_volume.sustained-spam",
        title="Tags flooding the log continuously",
        symptom="battery" if costly else "both",
        severity="medium" if costly else "low",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{len(rows)} tags logged at least {SPAM_SUSTAINED_PER_MIN} lines "
            f"per minute for {SPAM_MIN_SPAN_MIN:g}+ minutes: {listed}.{cost_text}"
        ),
        metrics={r["tag"]: r["per_min"] for r in rows[:10]},
        recommendation=(
            "Identify the app or service behind each tag (top_pid, top_uid). "
            "Update or restrict that app; a system component logging this "
            "much usually reflects a retry loop worth reporting."
        ),
        followups=[
            (
                "A few minutes later, run `adb_ro.py --save logcat_later "
                "--workdir WORKDIR -- logcat -d -b all` and count each tag's "
                "lines in WORKDIR/live/logcat_later.txt with `grep -c`."
            ),
        ],
    )


def _burst_finding(rows: list[Row]) -> Finding:
    listed = ", ".join(
        f"{r['tag']} {r['peak_per_min']} lines at {r['peak_minute']} "
        f"({r['peak_during']})"
        for r in rows[:5]
    )
    return Finding(
        id="logcat_volume.bursts",
        title="Short log bursts",
        symptom="info",
        severity="info",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{len(rows)} tags wrote at least {SPAM_BURST_PER_MIN} lines in one "
            f"minute without sustained spam: {listed}. One-off bursts cost little."
        ),
        metrics={r["tag"]: r["peak_per_min"] for r in rows[:10]},
        followups=["Check whether the burst repeats in a later capture."],
    )


def _wtf_rows(volume: _Volume) -> list[Row]:
    rows: list[Row] = []
    for component, items in volume.wtf.items():
        first, last = items[0][0], items[-1][0]
        span_min = (last - first).total_seconds() / 60
        common = Counter(t for _, t, _ in items).most_common(1)[0][0]
        rows.append(
            {
                "component": component,
                "count": len(items),
                "first": first.isoformat(sep=" ", timespec="seconds"),
                "last": last.isoformat(sep=" ", timespec="seconds"),
                "per_min": round(len(items) / max(span_min, 1.0), 2),
                "message": common[:100],
                "ref": items[0][2],
            },
        )
    rows.sort(key=lambda r: -r["count"])
    return rows


def _wtf_finding(rows: list[Row]) -> Finding:
    listed = ", ".join(f"{r['component']} x{r['count']}" for r in rows[:4])
    return Finding(
        id="logcat_volume.repeated-wtf",
        title="Repeated WTF reports from system components",
        symptom="info",
        severity="low",
        basis="measured",
        window="log_coverage",
        summary=(
            f"The event log holds repeated WTF reports: {listed} (at least "
            f"{WTF_REPEAT_MIN} each; a lower bound, the buffer rotates). They "
            "point at churn inside the component, not at a measured cost."
        ),
        metrics={r["component"]: r["count"] for r in rows[:5]},
        evidence=[
            Evidence(r["ref"], f"{r['component']}: {r['message']}") for r in rows[:4]
        ],
        recommendation=(
            "Save the main and system buffers right away with `adb_ro.py "
            "--save logcat_wtf --workdir WORKDIR -- logcat -d -b main,system` "
            "and grep WORKDIR/live/logcat_wtf.txt for the component to see the "
            "full WTF text and stack, then check what drives the component "
            "(for ConnectivityService, network changes)."
        ),
        followups=["Count the WTFs again after an hour to get a rate."],
    )


def _rate_window(volume: _Volume) -> dict[str, Any]:
    """Return lines per second over the minutes every long buffer covers.

    The window starts at the last full charge and ends at the plug-in time
    when those fall inside it, so the rate describes battery use. Buffers
    that rotated within minutes are left out.
    """
    long = [b for b in volume.buffers if (b["span_min"] or 0) >= RATE_MIN_SPAN_MIN]
    ends = [datetime.fromisoformat(b["end"]) for b in long if b["end"]]
    if not long or not ends:
        return {}
    start = max(datetime.fromisoformat(b["start"]) for b in long)
    end = max(ends)
    w = volume.windows
    plug = charging_since(w)
    if plug is not None and start < plug < end:
        end = plug
    if (first := w.since_charge_start) is not None and start < first < end:
        start = first
    start = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = end.replace(second=0, microsecond=0)
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return {}
    lines = sum(n for m, n in volume.minutes.items() if start <= m < end)
    state = power_state(w, start, end)
    return {
        "rate_window_from": start.isoformat(sep=" ", timespec="minutes"),
        "rate_window_to": end.isoformat(sep=" ", timespec="minutes"),
        "rate_window_on_battery": {"on_battery": True, "charging": False}.get(state),
        "rate_window_lines": lines,
        "lines_per_s": round(lines / seconds, 2),
    }


def _volume_metrics(volume: _Volume, cost: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {f"lines_{k}": n for k, n in volume.lines.items()}
    metrics.update(
        {
            "lines_total": sum(volume.lines.values()),
            "unparsed_lines": volume.unparsed,
            "tags": len(volume.tags),
            "wtf_total": sum(len(v) for v in volume.wtf.values()),
            **cost,
            **_rate_window(volume),
        },
    )
    if volume.stale:
        metrics["stale_stamp_lines"] = volume.stale
    for b in volume.buffers:
        metrics[f"coverage_{b['buffer']}_min"] = b["span_min"]
    return metrics


@analyzer("logcat_volume")
def logcat_volume(ctx: Context) -> Result:
    """Count log lines per tag and minute, buffer coverage, spam and WTFs."""
    sources = _log_sources(ctx)
    if not sources:
        msg = "no logcat dumps (logcat_system, logcat_events, logcat_radio)"
        raise SkipError(msg)
    volume = _Volume(ctx.windows)
    for key, text in sources:
        _scan_source(volume, key, text, _log_lines(ctx, key))
    if not volume.tags:
        msg = "the log dumps contain no threadtime lines with a usable time"
        raise SkipError(msg)
    result = Result("logcat_volume", window="log_coverage")
    if note := plug_note(ctx.windows):
        result.notes.append(note)
    if volume.stale:
        result.notes.append(
            f"{volume.stale} lines are stamped before the boot, so they were "
            "written before the clock was set; they are left out of buffer "
            "spans and per-minute counts.",
        )
    if any(key == "logcat_all" for key, _ in sources):
        result.notes.append(
            "Only a merged 'logcat -b all' capture was available: buffer start "
            "markers show where each buffer begins, but lines cannot be "
            "attributed to buffers.",
        )
    result.notes.append(
        "Counts are lower bounds for each buffer's span; a merged dump "
        "(main, system, crash) has one line count for all its buffers.",
    )
    if volume.unparsed:
        result.notes.append(f"Skipped {volume.unparsed} lines that are not threadtime.")
    tag_rows = _tag_rows(volume)
    result.add_table("tags", tag_rows)
    result.tables["buffers"] = volume.buffers
    result.add_table(
        "minutes",
        [
            {"minute": m.isoformat(sep=" ", timespec="minutes"), "lines": n}
            for m, n in volume.minutes.most_common()
        ],
    )
    result.add_table(
        "templates",
        [
            {"tag": t, "template": s, "lines": n}
            for (t, s), n in volume.templates.most_common()
        ],
    )
    wtf = _wtf_rows(volume)
    result.add_table("wtf", wtf)
    cost = _logging_cost(ctx)
    result.metrics.update(_volume_metrics(volume, cost))
    sustained = [
        r
        for r in tag_rows
        if r["tag"] not in EXPECTED_VOLUME_TAGS
        and r["span_min"] >= SPAM_MIN_SPAN_MIN
        and r["per_min"] >= SPAM_SUSTAINED_PER_MIN
    ]
    bursts = [
        r
        for r in tag_rows
        if r["peak_per_min"] >= SPAM_BURST_PER_MIN and r not in sustained
    ]
    result.metrics["sustained_spam_tags"] = len(sustained)
    result.metrics["burst_tags"] = len(bursts)
    if sustained:
        result.findings.append(_spam_finding(sustained, cost))
    if bursts:
        result.findings.append(_burst_finding(bursts))
    repeated = [r for r in wtf if r["count"] >= WTF_REPEAT_MIN]
    if repeated:
        result.findings.append(_wtf_finding(repeated))
    return result


# ----------------------------------------------------------------------------
# crashes, ANRs, watchdogs, reboots


@dataclass
class CrashEvent:
    """One crash, ANR, watchdog or native crash from any source."""

    source: str
    kind: str  # crash, native, anr, watchdog, system_restart
    ts: datetime | None
    process: str
    ref: str
    detail: str = ""
    foreground: bool | None = None
    # A log line stamped before the boot: written before the clock was set.
    stale: bool = False


def _dropbox_kind(tag: str) -> str | None:
    low = tag.lower()
    if "watchdog" in low:
        return "watchdog"
    if tag == "SYSTEM_RESTART":
        return "system_restart"
    if "anr" in low.split("_"):
        return "anr"
    if "native_crash" in low or tag == "SYSTEM_TOMBSTONE":
        return "native"
    if low.endswith("_crash"):
        return "crash"
    return None


@dataclass
class _DropboxEntry:
    ts: datetime
    tag: str
    index: int
    fields: dict[str, str] = field(default_factory=dict)


def parse_dropbox(text: Text) -> list[_DropboxEntry]:
    """Parse ``dumpsys dropbox [--print]`` entry headers and key body fields."""
    entries: list[_DropboxEntry] = []
    for i, line in enumerate(text.lines):
        if m := _DROPBOX_ENTRY_RE.match(line):
            ts = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S")
            entries.append(_DropboxEntry(ts, m[2], i))
        elif entries and (m := _DROPBOX_FIELD_RE.match(line)):
            entries[-1].fields.setdefault(m[1], m[2].strip())
        elif entries and (m := _NATIVE_NAME_RE.search(line)):
            entries[-1].fields.setdefault("Process", m[1])
    return entries


def _dropbox_events(text: Text, entries: list[_DropboxEntry]) -> list[CrashEvent]:
    events = []
    for e in entries:
        kind = _dropbox_kind(e.tag)
        if kind is None:
            continue
        process = e.fields.get("Process") or (e.fields.get("Package") or "?").split()[0]
        foreground = e.fields.get("Foreground")
        events.append(
            CrashEvent(
                source="dropbox",
                kind=kind,
                ts=e.ts,
                process=process,
                ref=text.ref(e.index),
                detail=e.tag,
                foreground=None if foreground is None else foreground == "Yes",
            ),
        )
    return events


def _exit_info_events(text: Text) -> list[CrashEvent]:
    events = []
    ts: datetime | None = None
    for i, line in enumerate(text.lines):
        if m := _EXIT_HEAD_RE.search(line):
            ts = datetime.fromisoformat(m[1])
        elif (m := _EXIT_REASON_RE.search(line)) and int(m[2]) in _EXIT_KINDS:
            kind = _EXIT_KINDS[int(m[2])]
            events.append(CrashEvent("exit_info", kind, ts, m[1], text.ref(i), m[3]))
    return events


def _tombstone_event(text: Text) -> CrashEvent | None:
    ts = name = signal = None
    for line in text.lines[:40]:
        if m := _TOMB_TIME_RE.match(line):
            ts = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S")
        elif (m := _NATIVE_NAME_RE.search(line)) and name is None:
            name = m[1]
        elif m := _TOMB_SIGNAL_RE.match(line):
            signal = m[2]
    if ts is None and name is None:
        return None
    return CrashEvent(
        "tombstone", "native", ts, name or "?", f"{text.origin}:1", signal or ""
    )


def _anr_trace_event(text: Text) -> CrashEvent | None:
    ts = name = None
    subject = ""
    for line in text.lines[:60]:
        if line.startswith("Subject: "):
            subject = line[9:].strip()
        elif (m := _ANR_PID_RE.match(line)) and ts is None:
            ts = datetime.strptime(m[2], "%Y-%m-%d %H:%M:%S")
        elif (m := _ANR_CMD_RE.match(line)) and name is None:
            name = m[1].strip()
    if ts is None:
        return None
    return CrashEvent(
        "anr_trace", "anr", ts, name or "?", f"{text.origin}:1", subject[:100]
    )


def _java_crash(
    line: LogLine,
    pending: dict[int, int],
) -> tuple[str, str, str, str] | None:
    """Pair ``FATAL EXCEPTION`` with the ``Process: x, PID: n`` line after it."""
    if line.message.startswith("FATAL EXCEPTION"):
        pending[line.pid] = line.lineno
    elif (m := _JAVA_PROCESS_RE.match(line.message)) and pending.pop(int(m[2]), None):
        return ("logcat", "crash", m[1], "")
    return None


def _other_crash(line: LogLine) -> tuple[str, str, str, str] | None:
    msg = line.message
    if line.tag == "libc" and (m := _FATAL_SIGNAL_RE.search(msg)):
        return ("logcat", "native", m[4], m[2])
    if line.tag == "ActivityManager" and (m := _ANR_IN_RE.match(msg)):
        return ("logcat", "anr", m[1], "")
    if line.tag == "Watchdog" and "WATCHDOG KILLING SYSTEM PROCESS" in msg:
        return ("logcat", "watchdog", "system_server", "")
    if line.tag in {"am_crash", "am_anr"}:
        fields = msg.strip("[]").split(",")
        names = [f for f in fields if f and not f.lstrip("-").isdigit()]
        kind = "crash" if line.tag == "am_crash" else "anr"
        return ("events", kind, names[0] if names else "?", "")
    return None


def _logcat_event(
    text: Text,
    line: LogLine,
    pending: dict[int, int],
) -> CrashEvent | None:
    """Turn one log line into a crash event; Java crashes span two lines."""
    if line.tag == "AndroidRuntime":
        found = _java_crash(line, pending)
    else:
        found = _other_crash(line)
    if found is None:
        return None
    source, kind, process, detail = found
    ref = text.ref(line.lineno - text.first_line)
    return CrashEvent(source, kind, line.ts, process, ref, detail)


def _logcat_events(ctx: Context) -> list[CrashEvent]:
    events: list[CrashEvent] = []
    boot = ctx.windows.boot_time
    keys = [k for k in LOG_KEYS[:2] if ctx.sources.has(k)] or ["logcat_all"]
    for key in keys:
        text = ctx.sources.get(key)
        if text is None:
            continue
        pending: dict[int, int] = {}
        for line in _log_lines(ctx, key):
            if event := _logcat_event(text, line, pending):
                event.stale = _stale(line.ts, boot)
                events.append(event)
    return events


def boot_reason_kind(reason: str) -> str:
    """Classify an AOSP boot reason as requested, battery, thermal or unexpected."""
    low = reason.lower()
    for kind, words in _BOOT_REASON_KINDS:
        if any(w in low for w in words):
            return kind
    return "unknown"


def _getprop_values(text: Text, wanted: set[str]) -> dict[str, tuple[str, int]]:
    """Return ``{prop: (value, line index)}``; multi-line values are joined."""
    found: dict[str, tuple[str, int]] = {}
    current: tuple[str, int] | None = None
    parts: list[str] = []
    for i, line in enumerate(text.lines):
        if current is None:
            m = _PROP_RE.match(line)
            if not m or m[1] not in wanted:
                continue
            current, parts = (m[1], i), [m[2]]
        else:
            parts.append(line)
        if parts[-1].endswith("]"):
            found[current[0]] = ("\n".join(parts)[:-1], current[1])
            current = None
    return found


def _boot_reasons(ctx: Context) -> tuple[str | None, list[Row]]:
    text = ctx.sources.get("getprop")
    if text is None:
        return None, []
    props = _getprop_values(
        text, {"sys.boot.reason", "persist.sys.boot.reason.history"}
    )
    current = props.get("sys.boot.reason", ("", 0))[0] or None
    history, index = props.get("persist.sys.boot.reason.history", ("", 0))
    rows: list[Row] = []
    for entry in history.splitlines():
        reason, _, epoch = entry.strip().rpartition(",")
        if not epoch.isdigit():
            continue
        local = ctx.windows.local_from_epoch(int(epoch))
        try:
            when = local or datetime.fromtimestamp(int(epoch), tz=UTC)
        except (OverflowError, OSError, ValueError):
            continue
        rows.append(
            {
                "reason": reason,
                "kind": boot_reason_kind(reason),
                "recorded_at": when.replace(tzinfo=None).isoformat(sep=" "),
                "clock": "local" if local else "UTC",
                "ref": text.ref(index),
            },
        )
    return current, rows


def _loops(events: list[CrashEvent], boot: datetime | None) -> list[Row]:
    """Find processes with LOOP_MIN+ crashes (or ANRs) of one source in a day.

    Crashes during the current boot's first minutes (and log lines stamped
    before the clock was set) are left out: services that abort while the
    system starts are a boot artefact, not a loop. Records without a process
    name ('?') cannot be tied to one process, so they form no loop.
    """
    groups: dict[tuple[str, str, str], list[tuple[datetime, CrashEvent]]] = defaultdict(
        list
    )
    for e in events:
        if e.ts is None or e.stale or e.process == "?":
            continue
        if boot and boot <= e.ts < boot + BOOT_PHASE:
            continue
        group = "anr" if e.kind == "anr" else "crash"
        groups[e.source, group, e.process].append((e.ts, e))
    rows: list[Row] = []
    for (source, group, process), items in groups.items():
        items.sort(key=itemgetter(0))
        best, start = 0, 0
        for end, (ts, _) in enumerate(items):
            while ts - items[start][0] > LOOP_WINDOW:
                start += 1
            best = max(best, end - start + 1)
        if best >= LOOP_MIN:
            rows.append(
                {
                    "process": process,
                    "kind": group,
                    "source": source,
                    "max_per_day": best,
                    "total": len(items),
                    "last": items[-1][0].isoformat(sep=" "),
                    "ref": items[-1][1].ref,
                },
            )
    rows.sort(key=itemgetter("last"), reverse=True)
    return rows


def _event_row(e: CrashEvent, boot: datetime | None) -> Row:
    during_boot = bool(boot and e.ts and boot <= e.ts < boot + BOOT_PHASE)
    return {
        "time": e.ts.isoformat(sep=" ") if e.ts else None,
        "kind": e.kind,
        "process": e.process,
        "source": e.source,
        "detail": e.detail,
        "foreground": e.foreground,
        "since_boot": e.stale or bool(boot and e.ts and e.ts >= boot),
        "during_boot": e.stale or during_boot,
        "stale_stamp": e.stale,
        "ref": e.ref,
    }


def _system_crash_finding(rows: list[Row]) -> Finding:
    listed = ", ".join(f"{r['detail'] or r['kind']} at {r['time']}" for r in rows[:4])
    return Finding(
        id="crash_anr_audit.system-server-crash",
        title="System server crashed or hung",
        symptom="both",
        severity="high",
        basis="measured",
        window="since_boot",
        summary=(
            f"{len(rows)} system_server crash, watchdog or restart records "
            f"since boot or in the last {RECENT_DAYS} days: {listed}. Each one "
            "restarts the whole Android framework (a 'soft reboot')."
        ),
        metrics={"events": len(rows)},
        evidence=[Evidence(r["ref"], f"{r['kind']} {r['process']}") for r in rows[:4]],
        recommendation=(
            "Check Settings > System > System update, then report the crash "
            "with the bugreport to the vendor. If it follows an app install, "
            "boot into safe mode to test without third-party apps."
        ),
        followups=["Read the dropbox entry text for the stack or blocked thread."],
    )


def _loop_finding(loops: list[Row]) -> Finding:
    listed = ", ".join(
        f"{r['process']} {r['kind']} x{r['max_per_day']}/day ({r['source']})"
        for r in loops[:5]
    )
    system = any(
        r["process"] in {"system_server", "com.android.systemui"} for r in loops
    )
    return Finding(
        id="crash_anr_audit.crash-loop",
        title="Processes crashing or hanging repeatedly",
        symptom="both",
        severity="high" if system else "medium",
        basis="measured",
        window="daily",
        summary=(
            f"{len(loops)} processes had {LOOP_MIN} or more crashes or ANRs "
            f"within one day in the last {RECENT_DAYS} days: {listed}. A "
            "crash loop restarts the process again and again, which costs "
            "CPU and battery."
        ),
        metrics={r["process"]: r["max_per_day"] for r in loops[:10]},
        evidence=[Evidence(r["ref"], f"{r['process']} {r['kind']}") for r in loops[:5]],
        recommendation=(
            "Update the app, clear its cache (Settings > Apps > <app> > "
            "Storage & cache), or uninstall it if unused."
        ),
        followups=["Read the crash text (dropbox or exit-info) for the cause."],
    )


def _foreground_finding(rows: list[Row]) -> Finding:
    listed = ", ".join(f"{r['process']} {r['kind']} at {r['time']}" for r in rows[:5])
    return Finding(
        id="crash_anr_audit.foreground-anr-or-crash",
        title="Apps crashed or froze while in use",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="since_boot",
        summary=f"{len(rows)} foreground ANRs or crashes since boot: {listed}.",
        metrics={"events": len(rows)},
        evidence=[Evidence(r["ref"], f"{r['kind']} {r['process']}") for r in rows[:5]],
        recommendation=(
            "Update the apps involved; repeated ANRs across many apps point at "
            "memory or storage pressure (see the memory analysis)."
        ),
        followups=["Check the ANR trace files for the blocked main thread."],
    )


def _reboot_finding(rows: list[Row]) -> Finding:
    listed = ", ".join(f"{r['reason']} ({r['recorded_at']})" for r in rows[:4])
    return Finding(
        id="crash_anr_audit.unexpected-reboot",
        title="Unexpected reboots",
        symptom="both",
        severity="medium",
        basis="measured",
        window="daily",
        summary=(
            f"The boot-reason history has {len(rows)} unexpected reboots in the "
            f"last {REBOOT_RECENT_DAYS} days: {listed}. Times are when the "
            "next boot recorded them."
        ),
        metrics={"unexpected_reboots": len(rows)},
        evidence=[Evidence(r["ref"], r["reason"]) for r in rows[:4]],
        recommendation=(
            "Check Settings > System > System update; kernel panics and "
            "watchdog resets are firmware or hardware faults to report to the "
            "vendor with the bugreport."
        ),
        followups=["Look for the panic text in the dropbox (SYSTEM_LAST_KMSG)."],
    )


def _quiet_finding(metrics: dict[str, Any], rows: list[Row]) -> Finding:
    during_boot = sum(1 for r in rows if r["since_boot"] and r["during_boot"])
    extra = (
        f" {during_boot} crash or ANR records fell in the first "
        f"{BOOT_PHASE.seconds // 60} minutes after boot."
        if during_boot
        else ""
    )
    return Finding(
        id="crash_anr_audit.no-crash-loops",
        title="No crash loops, system crashes or foreground ANRs",
        symptom="info",
        severity="info",
        basis="measured",
        window="since_boot",
        summary=(
            "No system_server crash or watchdog, no foreground ANR or crash "
            f"since boot, and no crash loop in the last {RECENT_DAYS} days."
            f"{extra} Counts are lower bounds: the dropbox, exit-info and log "
            "buffers keep a limited history."
        ),
        metrics={
            k: metrics.get(k)
            for k in (
                "crash_records_since_boot",
                "anr_records_since_boot",
                "records_since_boot_phase",
                "tombstones",
            )
        },
    )


def _dropbox_tag_rows(entries: list[_DropboxEntry]) -> list[Row]:
    by_tag: dict[str, list[datetime]] = defaultdict(list)
    for e in entries:
        by_tag[e.tag].append(e.ts)
    rows: list[Row] = [
        {
            "tag": tag,
            "count": len(times),
            "first": min(times).isoformat(sep=" "),
            "last": max(times).isoformat(sep=" "),
        }
        for tag, times in by_tag.items()
    ]
    rows.sort(key=lambda r: -r["count"])
    return rows


def _collect_events(
    ctx: Context,
    result: Result,
) -> tuple[list[CrashEvent], dict[str, Any]]:
    events: list[CrashEvent] = []
    metrics: dict[str, Any] = {}
    if dropbox := ctx.sources.get("dropbox"):
        entries = parse_dropbox(dropbox)
        metrics["dropbox_entries"] = len(entries)
        result.add_table("dropbox_tags", _dropbox_tag_rows(entries))
        events += _dropbox_events(dropbox, entries)
    if exit_info := ctx.sources.get("exit_info"):
        events += _exit_info_events(exit_info)
    tombstones = [
        e
        for t in ctx.sources.members("tombstones")
        if not t.origin.endswith(".pb") and (e := _tombstone_event(t))
    ]
    metrics["tombstones"] = len(tombstones)
    events += tombstones
    events += [
        e for t in ctx.sources.members("anr_traces") if (e := _anr_trace_event(t))
    ]
    events += _logcat_events(ctx)
    return events, metrics


def _crash_metrics(rows: list[Row], metrics: dict[str, Any]) -> None:
    since = [r for r in rows if r["since_boot"]]
    for kind in ("crash", "native", "anr", "watchdog", "system_restart"):
        metrics[f"{kind}_records_since_boot"] = sum(
            1 for r in since if r["kind"] == kind
        )
    metrics["records_since_boot_phase"] = sum(1 for r in since if not r["during_boot"])
    by_source = Counter((r["source"], r["kind"]) for r in rows)
    metrics.update({f"{s}_{k}_total": n for (s, k), n in sorted(by_source.items())})
    tombs = [r for r in rows if r["source"] == "tombstone" and r["time"]]
    if tombs:
        newest = max(tombs, key=itemgetter("time"))
        metrics["newest_tombstone"] = newest["time"]
        metrics["newest_tombstone_process"] = newest["process"]


@analyzer("crash_anr_audit", after=("windows", "process_cpu_since_boot"))
def crash_anr_audit(ctx: Context) -> Result:
    """Audit crashes, ANRs, watchdogs, tombstones, crash loops and reboots."""
    result = Result("crash_anr_audit", window="since_boot")
    events, metrics = _collect_events(ctx, result)
    current, boots = _boot_reasons(ctx)
    if not events and not boots and "dropbox_entries" not in metrics:
        msg = "no dropbox, exit-info, tombstones, logs or boot reasons"
        raise SkipError(msg)
    w = ctx.windows
    rows = [_event_row(e, w.boot_time) for e in events]
    rows.sort(key=lambda r: r["time"] or "", reverse=True)
    result.add_table("events", rows)
    now = w.log_reference()
    recent = (now - timedelta(days=RECENT_DAYS)).isoformat(sep=" ")
    loops = _loops(events, w.boot_time)
    result.add_table("loops", loops)
    result.tables["boot_reasons"] = boots
    restarted = [
        r["process"]
        for r in result_table(ctx, "process_cpu_since_boot", "core_daemons")
        if r["restarted"]
    ]
    _crash_metrics(rows, metrics)
    reboot_cutoff = (now - timedelta(days=REBOOT_RECENT_DAYS)).isoformat(sep=" ")
    unexpected = [
        b
        for b in boots
        if b["kind"] == "unexpected" and b["recorded_at"] >= reboot_cutoff
    ]
    metrics.update(
        {
            "events": len(rows),
            "crash_loops_recent": sum(1 for r in loops if r["last"] >= recent),
            "crash_loops_older": sum(1 for r in loops if r["last"] < recent),
            "boot_reason": current,
            "boot_reason_kind": boot_reason_kind(current) if current else None,
            "battery_shutdowns_in_history": sum(
                1 for b in boots if b["kind"] == "battery"
            ),
            "unexpected_reboots_recent": len(unexpected),
            "core_daemons_restarted": len(restarted),
        },
    )
    result.metrics.update(metrics)
    result.notes.append(
        "Dropbox, exit-info (a few records per app) and the log buffers are "
        "rings, so all counts are lower bounds. Loops count one source at a "
        "time so the same crash seen in two places is not counted twice.",
    )
    if older := metrics["crash_loops_older"]:
        result.notes.append(
            f"{older} older crash or ANR loops (more than {RECENT_DAYS} days "
            "before capture) are listed in the loops table only.",
        )
    if unnamed := sum(1 for e in events if e.process == "?"):
        result.metrics["unattributed_records"] = unnamed
        result.notes.append(
            f"{unnamed} records name no process (for example a dropbox "
            "listing without the entry text); they form no crash loop.",
        )
    if stale := sum(1 for e in events if e.stale):
        result.notes.append(
            f"{stale} logcat records are stamped before the boot (written "
            "before the clock was set); they are counted as boot-time events.",
        )
    _add_crash_findings(result, rows, loops, unexpected, recent)
    return result


def _add_crash_findings(
    result: Result,
    rows: list[Row],
    loops: list[Row],
    unexpected: list[Row],
    recent: str,
) -> None:
    system = [
        r
        for r in rows
        if r["kind"] in {"watchdog", "system_restart"}
        or (r["process"] == "system_server" and r["kind"] in {"crash", "native"})
    ]
    system = [r for r in system if r["since_boot"] or (r["time"] or "") >= recent]
    if system:
        result.findings.append(_system_crash_finding(system))
    recent_loops = [r for r in loops if r["last"] >= recent]
    if recent_loops:
        result.findings.append(_loop_finding(recent_loops))
    foreground = [
        r
        for r in rows
        if r["since_boot"] and r["foreground"] and r["kind"] in {"anr", "crash"}
    ]
    if foreground:
        result.findings.append(_foreground_finding(foreground))
    if unexpected:
        result.findings.append(_reboot_finding(unexpected))
    if not result.findings:
        result.findings.append(_quiet_finding(result.metrics, rows))
