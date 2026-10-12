"""Memory pressure, low-memory kills and process churn.

These analyzers answer "is the phone short of memory, and does that make it
slow or drain the battery?". They keep what the data shows (kill counts, free
memory at the moment of a kill, kernel counters) apart from mechanisms, which
the dumps rarely show directly:

- ``exit_info_audit``: why processes died, from ``dumpsys activity exit-info``.
  The framework keeps only the last 16 exits per package and UID, so counts for
  busy packages are lower bounds.
- ``lmkd_kills``: what the low-memory killer daemon reported at each kill
  (reason, free memory, page cache, pressure), from the event and main logs.
- ``kills_vs_screen_events``: whether kills cluster after the screen turns on
  or off.
- ``memory_snapshot``: what holds RAM at collection time (PSS, swap, OOM
  groups).
- ``vmstat_reclaim_io``: reclaim, refault and swap counters since boot.
- ``psi_pressure``: pressure stall information (how long tasks waited for CPU,
  memory or I/O).
- ``zone_watermarks_offline``: per-zone free memory against the kernel
  watermarks, and memory blocks taken offline or brought online.
- ``am_memory_config``: the activity manager's cached-app freezer, compaction
  and cached-process limits.
- ``process_churn``: bursts of process starts and kill-restart loops.

Counts from log buffers and the exit-info history are lower bounds: both are
ring buffers. Kills of cached processes are normal reaping; they matter because
the apps the user returns to then start from scratch (cold starts).
"""

from __future__ import annotations

import bisect
import itertools
import operator
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .common import (
    Transition,
    iter_logcat,
    load_event_log,
    load_ps,
    load_settings,
    parse_decimal,
    parse_size_bytes,
    ps_cpu_by_name,
)
from .model import Context, Evidence, Finding, Result, SkipError, analyzer
from .source import Text

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .common import EventLog, LogLine

Row = dict[str, Any]

# --- Limits and thresholds ---------------------------------------------------

# ApplicationExitInfo reason and subreason codes (AOSP ApplicationExitInfo).
REASON_LOW_MEMORY = 3
REASON_EXCESSIVE_RESOURCE_USAGE = 9
SUBREASON_EXCESSIVE_CPU = 7
# AOSP keeps this many exits per package and UID
# (config_app_exit_info_history_list_size); a full list hides older exits.
DEFAULT_EXIT_HISTORY = 16
# RunningAppProcessInfo importance: 400 is cached; 200 or lower is something
# the user can see (foreground, foreground service, visible).
IMPORTANCE_CACHED = 400
IMPORTANCE_VISIBLE = 200
# An exit record and an lmkd kill of the same PID this close together are the
# same death; the activity manager records the exit after lmkd's kill.
EXIT_KILL_PAIR_WINDOW = timedelta(seconds=10)

# More than ~10 low-memory kills per hour means cached apps rarely survive
# between uses; at 30 per hour almost every app switch is a cold start.
LMK_RATE_MEDIUM_PER_H = 10.0
LMK_RATE_HIGH_PER_H = 30.0
# Twenty kills within one minute is a kill storm rather than gradual trimming.
LMK_BURST_PER_MIN = 20
# The same process killed ten times a day restarts cold every couple of hours.
REPEAT_KILLS_PER_DAY = 10
# The first minutes after boot start and trim many processes by design, so the
# since-boot kill rate is also given without them.
BOOT_SETTLE = timedelta(minutes=15)
# Rates and per-day extrapolations need a window of hours: boot loads every
# library from flash, so counters taken minutes after boot are boot I/O.
MIN_RATE_HOURS = 1.0
# A handful of kills of visible processes is already noticeable to the user.
VISIBLE_KILLS_MEDIUM = 5
# Two excessive-CPU kills on battery mean the app keeps doing it.
EXCESSIVE_CPU_MEDIUM = 2

# A kill with over 1 GiB of MemFree means memory was not exhausted overall.
KILL_FREE_MEMORY_KIB = 1024 * 1024
# Several such kills rule out a single odd sample.
KILL_FREE_MIN_COUNT = 3
# More than ten kills within ten seconds is a kill storm.
KILL_STORM_WINDOW = timedelta(seconds=10)
KILL_STORM_COUNT = 10
# CPU some-stall above 30 % (avg10) at kill time: killing and restarting apps
# competes with what the user is doing.
PSI_CPU_AT_KILL_PCT = 30.0
# lmkd oom_score_adj: 900 and above are cached processes, 200 and below are
# visible to the user.
ADJ_CACHED = 900
ADJ_VISIBLE = 200

# Kills up to three whole minutes (bins 0, 1 and 2) after a screen transition
# are attributed to it.
SCREEN_WINDOW = timedelta(minutes=3)
# More than five kills per screen-on, repeatedly, means the apps the user is
# about to open are being killed; ten or more is severe.
KILLS_PER_SCREEN_ON_MEDIUM = 5.0
KILLS_PER_SCREEN_ON_HIGH = 10.0
SCREEN_BURST_MIN_KILLS = 5
SCREEN_BURSTS_MIN = 2
# Plugging in wakes the screen, and usagestats truncates times to the second:
# a screen-on this close before the plug-in belongs to the plug-in.
PLUG_WAKE_MARGIN = timedelta(seconds=5)
# Screen-off stretches at least this long are checked for background kills.
LONG_SCREEN_OFF = timedelta(minutes=30)
SCREEN_OFF_KILLS_PER_H = 10.0

# OOM groups whose processes lmkd kills last (adj 250 or lower), except the
# foreground app itself, which the user is using.
PINNED_GROUPS = frozenset(
    {
        "Persistent",
        "Persistent Service",
        "Visible",
        "Perceptible",
        "Perceptible Medium",
        "Perceptible Low",
        "Heavy Weight",
        "Backup",
    },
)
# A third-party process costing over 100 MiB of physical RAM while pinned is a
# large share of the RAM left for cached apps on a 4-8 GB phone.
RESIDENT_HOG_MIB = 100.0
# Fewer cached processes than a quarter of the cached-process limit (or than
# eight when the limit is unknown) means the cache is nearly empty.
CACHED_LOW_SHARE = 0.25
CACHED_LOW_DEFAULT = 8
# Less than 10 % of swap free means swap is nearly exhausted.
SWAP_FREE_LOW_PCT = 10.0

# Kernel counter rates (catalogue flags): sustained refaults over 100 pages/s
# or major faults over 20/s mean the page cache is thrashing.
REFAULT_PAGES_PER_S = 100.0
MAJFAULT_PER_S = 20.0
# Over 1,000 direct-reclaim stalls a day: apps block on memory allocation.
ALLOCSTALL_PER_DAY = 1000.0
# Compaction failing more than half the time, over at least 100 stalls.
COMPACT_FAIL_PCT = 50.0
COMPACT_STALL_MIN = 100

# PSI: memory some > 10 % or full > 2 % (avg10) is a stalled phone; io full
# > 5 % is storage-bound; over 1 % of uptime in memory stalls, or 10 % in CPU
# stalls, since boot is chronic.
PSI_MEMORY_SOME_AVG10_PCT = 10.0
PSI_MEMORY_FULL_AVG10_PCT = 2.0
PSI_IO_FULL_AVG10_PCT = 5.0
PSI_MEMORY_SOME_SHARE_PCT = 1.0
PSI_CPU_SOME_SHARE_PCT = 10.0

# /proc/zoneinfo counts 4 KiB pages on Android devices.
PAGE_KIB = 4
# Zones smaller than 256 MiB (DMA zones) are too small to judge.
SMALL_ZONE_KIB = 256 * 1024
# A Movable zone of at least 10 % of RAM can be taken offline as a block.
HOTPLUG_ZONE_SHARE = 0.10
# A kernel-time anchor further away than this is unreliable, because the
# kernel log clock stops while the phone is suspended.
ANCHOR_MAX_DISTANCE_S = 60.0

# Process churn: more than 20 starts in a minute is a burst; three starts of
# the same process within a minute, or two kill-then-restart pairs within two
# minutes each, is a loop.
START_BURST_PER_MIN = 20
RAPID_STARTS = 3
RAPID_WINDOW = timedelta(seconds=60)
RESTART_GAP = timedelta(seconds=120)
RESTART_LOOP_MIN = 2
# Work released by a plug-in lands within about a minute.
PLUG_IN_FLOOD_WINDOW = timedelta(seconds=60)
# Five or more starts without a hosting reason within one second look like a
# prelaunch feature rather than app components.
EMPTY_HOSTING_BURST = 5
EMPTY_HOSTING_WINDOW = timedelta(seconds=1)
# Triggers up to a minute before a burst minute are listed with it.
TRIGGER_LOOKBACK = timedelta(seconds=60)

_MIB = 1024
_GIB_KIB = 1024 * 1024
_PCT = 100.0
_NOT_SHOWN = "This is a time correlation; the mechanism is not shown."
_RESTRICT = "Settings > Apps > <app> > App battery usage > Restricted"

# --- Shared helpers ----------------------------------------------------------


def _parse_wall(text: str) -> datetime | None:
    """Parse ``YYYY-MM-DD HH:MM:SS[.fff]`` local wall time."""
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in text else "%Y-%m-%d %H:%M:%S"
    try:
        return datetime.strptime(text, fmt)
    except ValueError:
        return None


def _fmt(ts: datetime | None, spec: str = "seconds") -> str | None:
    """Format a timestamp for metrics and tables."""
    return ts.isoformat(sep=" ", timespec=spec) if ts else None


_NON_DIGIT_RE = re.compile(r"\D")


def _kb(text: str) -> int:
    """Parse a kilobyte count with any thousands separator (``375,877``)."""
    sign = -1 if text.strip().startswith("-") else 1
    return sign * int(_NON_DIGIT_RE.sub("", text))


def _mib(kib: float | None) -> float | None:
    """Convert KiB to MiB, rounded."""
    return None if kib is None else round(kib / _MIB, 1)


def _rate(count: float, hours: float | None) -> float | None:
    """Return ``count`` per hour; None for an unknown or too short window."""
    return round(count / hours, 1) if hours and hours >= MIN_RATE_HOURS else None


def _hours(start: datetime | None, end: datetime | None) -> float | None:
    """Return the hours between two times, or None."""
    if start is None or end is None or end <= start:
        return None
    return (end - start).total_seconds() / 3600


def _int_at(values: list[str], index: int) -> int | None:
    """Return ``values[index]`` as an int, or None."""
    try:
        return int(values[index])
    except (IndexError, ValueError):
        return None


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


# --- Event log ---------------------------------------------------------------

# battery_saver_mode starts with the previous and the new full and adaptive
# saver states.
_SAVER_FULL_NOW_FIELD = 2


def _payload(line: LogLine) -> str:
    """Return an event payload without its surrounding brackets."""
    payload = line.message.strip()
    if payload.startswith("[") and payload.endswith("]"):
        payload = payload[1:-1]
    return payload


def _fields(line: LogLine) -> list[str]:
    return _payload(line).split(",")


def _cite_event(events: EventLog, line: LogLine) -> Evidence:
    """Cite one event-log line."""
    text = events.text
    if text is None:
        return Evidence(events.ref(line))
    return text.evidence(line.lineno - text.first_line)


@dataclass
class _BatteryWindow:
    start: datetime
    end: datetime
    how: str
    ends_with_plug_in: bool

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    def contains(self, ts: datetime) -> bool:
        return self.start <= ts < self.end


def _battery_window(ctx: Context) -> _BatteryWindow | None:
    """Return the on-battery stretch since the last full charge, if known."""
    w = ctx.windows
    span = w.battery_span()
    if span is None:
        return None
    charging = w.on_battery_at_capture is False
    if charging:
        how = w.plugged_at_source or "plug-in time"
    elif w.on_battery_at_capture:
        how = "on battery at capture"
    else:
        how = "capture time (charging state unknown)"
    return _BatteryWindow(*span, how, ends_with_plug_in=charging)


def _plug_in_time(ctx: Context, events: EventLog) -> datetime | None:
    """Return the plug-in before capture, or the first one in the event log."""
    w = ctx.windows
    if w.on_battery_at_capture is False and w.plugged_at is not None:
        return w.plugged_at
    plugs = [t.ts for t in events.power_transitions() if t.on]
    return plugs[0] if plugs else None


def _battery_metrics(battery: _BatteryWindow | None) -> Row:
    """Describe the on-battery window in metrics."""
    if battery is None:
        return {"on_battery_window": None}
    return {
        "on_battery_start": _fmt(battery.start),
        "on_battery_end": _fmt(battery.end, "milliseconds"),
        "on_battery_h": round(battery.hours, 2),
        "on_battery_end_source": battery.how,
    }


# --- Activity manager blocks ------------------------------------------------

_AM_HEADER = "ACTIVITY MANAGER "
_EXIT_INFO_HEADER = "ACTIVITY MANAGER PROCESS EXIT INFO"
_LMK_HEADER = "ACTIVITY MANAGER LMK KILLS"
_AM_LMK_TOTAL_RE = re.compile(r"^\s+Total number of kills: (\d+)")
_AM_LMK_ADJ_RE = re.compile(r"^\s+kills at or below oom_adj (\d+): (\d+)")


def _activity_block(ctx: Context, key: str, header: str) -> Text | None:
    """Return a live dump, or the same block cut from the bugreport activity dump."""
    text = ctx.sources.get(key)
    if text is not None:
        return text
    activity = ctx.sources.get("activity")
    if activity is None:
        return None
    lines = activity.lines
    start = next((i for i, line in enumerate(lines) if line.startswith(header)), None)
    if start is None:
        return None
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith(_AM_HEADER)),
        len(lines),
    )
    body = "\n".join(lines[start:end])
    return Text(activity.origin, body, activity.first_line + start)


@dataclass
class _AmLmk:
    """The activity manager's count of lmkd kills since it started (no ring buffer)."""

    total: int
    by_adj: dict[int, int]
    evidence: Evidence


def _am_lmk_counts(ctx: Context) -> _AmLmk | None:
    """Parse ``dumpsys activity lmk``: total kills and kills at or below each adj."""
    text = _activity_block(ctx, "activity_lmk", _LMK_HEADER)
    if text is None:
        return None
    total: _AmLmk | None = None
    by_adj: dict[int, int] = {}
    for i, line in enumerate(text.lines):
        if m := _AM_LMK_TOTAL_RE.match(line):
            total = _AmLmk(int(m[1]), by_adj, text.evidence(i))
        elif m := _AM_LMK_ADJ_RE.match(line):
            by_adj[int(m[1])] = int(m[2])
    return total


# --- Exit info ---------------------------------------------------------------

_EXIT_PACKAGE_RE = re.compile(r"^\s+package: (\S+)")
_EXIT_UID_RE = re.compile(r"^\s+Historical Process Exit for uid=(\d+)")
_EXIT_TS_RE = re.compile(
    r"timestamp=(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?) pid=(\d+) realUid=(\d+)",
)
# Reason names can nest parentheses ("APP CRASH(EXCEPTION)"): match greedily
# up to the next fixed keyword instead of up to the first closing parenthesis.
_EXIT_PROCESS_RE = re.compile(
    r"process=(\S+) reason=(\d+) \((.*)\) subreason=(\d+) \((.*)\) status=(-?\d+)",
)
# State may be "empty" or "44 bytes"; description may contain spaces.
_EXIT_IMPORTANCE_RE = re.compile(
    r"importance=(\d+) pss=(\S+) rss=(\S+) description=(.*) state=(.*) trace=",
)


@dataclass
class _Exit:
    ts: datetime
    package: str
    section: tuple[str, str]
    pid: int
    uid: int
    index: int
    process: str = ""
    reason: int = -1
    reason_name: str = "UNPARSED"
    subreason: int = 0
    subreason_name: str = ""
    importance: int | None = None
    rss_kib: int | None = None
    description: str = ""
    excerpt: str = ""

    @property
    def is_excessive_cpu(self) -> bool:
        return self.reason == REASON_EXCESSIVE_RESOURCE_USAGE and (
            self.subreason == SUBREASON_EXCESSIVE_CPU
            or self.description.startswith("excessive cpu")
        )

    @property
    def label(self) -> str:
        """Name the process; shared names (WebView sandboxes) get their host."""
        name = self.process or self.package
        if ":sandboxed_process" in name:
            return f"{self.package} (WebView sandbox)"
        if self.package and not name.startswith(self.package):
            return f"{name} (in {self.package})"
        return name


@dataclass
class _ExitInfo:
    records: list[_Exit]
    sections: dict[tuple[str, str], list[_Exit]]
    skipped: int


def _parse_exit_details(line: str, record: _Exit) -> bool:
    """Fill ``record`` from its ``process=`` or ``importance=`` line."""
    if m := _EXIT_PROCESS_RE.search(line):
        record.process = m[1]
        record.reason, record.reason_name = int(m[2]), m[3]
        record.subreason, record.subreason_name = int(m[4]), m[5]
        record.excerpt = f"{record.ts:%Y-%m-%d %H:%M:%S} {line}"
        return True
    if m := _EXIT_IMPORTANCE_RE.search(line):
        record.importance = int(m[1])
        record.description = m[4].strip()
        try:
            record.rss_kib = parse_size_bytes(m[3]) // 1024
        except ValueError:
            record.rss_kib = None
        return True
    return False


def _parse_exit_info(text: Text) -> _ExitInfo:
    """Parse ``dumpsys activity exit-info`` into records grouped by section."""
    info = _ExitInfo([], defaultdict(list), 0)
    package = uid_section = ""
    current: _Exit | None = None
    for i, line in enumerate(text.lines):
        stripped = line.lstrip()
        if stripped.startswith("timestamp="):
            m = _EXIT_TS_RE.match(stripped)
            ts = _parse_wall(m[1]) if m else None
            current = None
            if m is None or ts is None:
                info.skipped += 1
                continue
            section = (package, uid_section)
            current = _Exit(ts, package, section, int(m[2]), int(m[3]), i)
            info.records.append(current)
            info.sections[section].append(current)
        elif stripped.startswith(("process=", "importance=")):
            if current is None or not _parse_exit_details(stripped, current):
                info.skipped += 1
        elif m := _EXIT_PACKAGE_RE.match(line):
            package, current = m[1], None
        elif m := _EXIT_UID_RE.match(line):
            uid_section, current = m[1], None
    info.sections = dict(info.sections)
    return info


def _load_exit_info(ctx: Context) -> tuple[Text, _ExitInfo] | None:
    """Return the exit-info dump and its records, parsed once per run."""

    def build() -> tuple[Text, _ExitInfo] | None:
        text = _activity_block(ctx, "exit_info", _EXIT_INFO_HEADER)
        return (text, _parse_exit_info(text)) if text is not None else None

    return ctx.sources.memo("memory.exit_info", build)


def _history_cap(sections: dict[tuple[str, str], list[_Exit]]) -> int:
    """Return the per-section ring-buffer size.

    The largest section size counts as the cap when at least two sections
    reach it (a plateau); otherwise the AOSP default is assumed.
    """
    sizes = Counter(len(v) for v in sections.values())
    if not sizes:
        return DEFAULT_EXIT_HISTORY
    largest = max(sizes)
    return largest if sizes[largest] > 1 else DEFAULT_EXIT_HISTORY


def _scope(ctx: Context, latest: datetime) -> tuple[str, datetime, datetime]:
    """Return the window name, start and end used for "since boot" counts."""
    end = ctx.windows.dump_time or latest
    if ctx.windows.boot_time is not None:
        return "since_boot", ctx.windows.boot_time, end
    return "last_24h", end - timedelta(hours=24), end


@dataclass
class _ExitScope:
    """Exit records split into the windows that the findings use."""

    name: str
    start: datetime
    end: datetime
    battery: _BatteryWindow | None
    cap: int
    full: set[tuple[str, str]]
    filled: set[tuple[str, str]]
    records: list[_Exit]
    after_plug: int | None
    am_lmk: _AmLmk | None = None
    # lmkd's oom_score_adj at the kill, by exit record line index
    kill_adj: dict[int, int] = field(default_factory=dict)

    @property
    def hours(self) -> float | None:
        return _hours(self.start, self.end)

    def am_rate(self) -> float | None:
        """Return the activity manager's lmkd kills per hour since boot."""
        if self.am_lmk is None or self.name != "since_boot":
            return None
        return _rate(self.am_lmk.total, self.hours)

    @property
    def settled_hours(self) -> float | None:
        return _hours(self.start + BOOT_SETTLE, self.end)

    @property
    def lmk(self) -> list[_Exit]:
        return [r for r in self.records if r.reason == REASON_LOW_MEMORY]

    @property
    def settled(self) -> list[_Exit]:
        return [r for r in self.lmk if r.ts >= self.start + BOOT_SETTLE]

    def on_battery(self, record: _Exit) -> bool:
        return bool(self.battery and self.battery.contains(record.ts))

    @property
    def lmk_battery(self) -> list[_Exit]:
        return [r for r in self.lmk if self.on_battery(r)]

    @property
    def excessive(self) -> list[_Exit]:
        return sorted(
            (r for r in self.records if r.is_excessive_cpu),
            key=operator.attrgetter("ts"),
            reverse=True,
        )

    @property
    def visible(self) -> list[_Exit]:
        return [
            r
            for r in self.lmk
            if r.importance is not None and r.importance <= IMPORTANCE_VISIBLE
        ]

    @property
    def visible_confirmed(self) -> list[_Exit]:
        """Visible kills that lmkd's own records do not contradict.

        Exit-info importance is the state when the activity manager handled
        the death, which can be after it raised a cached process lmkd had
        picked. lmkd chooses victims only by oom_score_adj.
        """
        am = self.am_lmk
        if self.name == "since_boot" and am and am.by_adj.get(ADJ_VISIBLE) == 0:
            return []
        return [
            r
            for r in self.visible
            if self.kill_adj.get(r.index, ADJ_VISIBLE) <= ADJ_VISIBLE
        ]

    @property
    def cached(self) -> list[_Exit]:
        return [
            r
            for r in self.lmk
            if r.importance is not None and r.importance >= IMPORTANCE_CACHED
        ]

    def battery_rate(self) -> float | None:
        if self.battery is None:
            return None
        return _rate(len(self.lmk_battery), self.battery.hours)


def _kill_adjs(ctx: Context, records: list[_Exit]) -> dict[int, int]:
    """Return lmkd's oom_score_adj for exit records that match a logged kill."""
    by_pid: dict[int, list[_Kill]] = defaultdict(list)
    for k in _lmkd_records(ctx).all:
        by_pid[k.pid].append(k)
    found: dict[int, int] = {}
    for r in records:
        for k in by_pid.get(r.pid, []):
            if k.adj is not None and abs(k.ts - r.ts) <= EXIT_KILL_PAIR_WINDOW:
                found[r.index] = k.adj
                break
    return found


def _exit_scope(ctx: Context, info: _ExitInfo) -> _ExitScope:
    battery = _battery_window(ctx)
    name, start, end = _scope(ctx, max(r.ts for r in info.records))
    cap = _history_cap(info.sections)
    full = {k for k, v in info.sections.items() if len(v) >= cap}
    filled = {k for k in full if min(r.ts for r in info.sections[k]) >= start}
    plug = _plug_in_time(ctx, load_event_log(ctx))
    after_plug = None
    if plug is not None:
        after_plug = sum(
            1
            for r in info.records
            if r.reason == REASON_LOW_MEMORY
            and plug <= r.ts < plug + PLUG_IN_FLOOD_WINDOW
        )
    records = [r for r in info.records if start <= r.ts <= end]
    visible = [
        r
        for r in records
        if r.reason == REASON_LOW_MEMORY
        and r.importance is not None
        and r.importance <= IMPORTANCE_VISIBLE
    ]
    return _ExitScope(
        name,
        start,
        end,
        battery,
        cap,
        full,
        filled,
        records,
        after_plug,
        _am_lmk_counts(ctx),
        _kill_adjs(ctx, visible),
    )


def _am_lmk_metrics(es: _ExitScope) -> Row:
    """Compare exit-info with the activity manager's lmkd kill counter."""
    am = es.am_lmk
    if am is None:
        return {"lmkd_kills_am_counter": None}
    lmk = len(es.lmk)
    return {
        "lmkd_kills_am_counter": am.total,
        "lmkd_kills_am_counter_per_h": es.am_rate(),
        "lmkd_kills_am_counter_adj_900_or_less": am.by_adj.get(ADJ_CACHED),
        "lmkd_kills_am_counter_adj_200_or_less": am.by_adj.get(ADJ_VISIBLE),
        "exit_info_share_of_am_counter_pct": (
            round(_PCT * lmk / am.total, 1)
            if am.total and es.name == "since_boot"
            else None
        ),
    }


def _exit_metrics(es: _ExitScope) -> Row:
    s = es.name
    lmk = es.lmk
    per_minute = Counter(_minute(r.ts) for r in lmk)
    worst = max(per_minute.items(), key=operator.itemgetter(1), default=(None, 0))
    days = max((es.hours or 24) / 24, 1.0)
    per_process = Counter(r.label for r in lmk)
    batt = es.battery
    return {
        f"window_start_{s}": _fmt(es.start),
        f"window_h_{s}": round(es.hours, 2) if es.hours else None,
        f"exits_{s}": len(es.records),
        f"low_memory_kills_{s}": len(lmk),
        f"low_memory_processes_{s}": len({r.process for r in lmk}),
        f"low_memory_kills_per_h_{s}": _rate(len(lmk), es.hours),
        "low_memory_kills_first_15min": len(lmk) - len(es.settled),
        f"low_memory_kills_per_h_{s}_after_first_15min": _rate(
            len(es.settled), es.settled_hours
        ),
        f"low_memory_cached_share_pct_{s}": (
            round(_PCT * len(es.cached) / len(lmk), 1) if lmk else None
        ),
        f"low_memory_kills_visible_{s}": len(es.visible),
        "low_memory_kills_visible_contradicted_by_lmkd": (
            len(es.visible) - len(es.visible_confirmed)
        ),
        f"max_low_memory_kills_per_min_{s}": worst[1],
        f"max_low_memory_kills_minute_{s}": _fmt(worst[0], "minutes"),
        f"low_memory_burst_minutes_{s}": sum(
            1 for n in per_minute.values() if n >= LMK_BURST_PER_MIN
        ),
        f"processes_killed_{REPEAT_KILLS_PER_DAY}x_per_day_{s}": sum(
            1 for n in per_process.values() if n / days >= REPEAT_KILLS_PER_DAY
        ),
        f"excessive_cpu_kills_{s}": len(es.excessive),
        **_battery_metrics(batt),
        "low_memory_kills_on_battery": len(es.lmk_battery) if batt else None,
        "low_memory_kills_per_h_on_battery": es.battery_rate(),
        "excessive_cpu_kills_on_battery": (
            sum(1 for r in es.excessive if es.on_battery(r)) if batt else None
        ),
        "low_memory_kills_60s_after_plug_in": es.after_plug,
    }


def _reason_rows(es: _ExitScope) -> list[Row]:
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for r in es.records:
        key = (f"{r.reason} {r.reason_name}", f"{r.subreason} {r.subreason_name}")
        counts[key][0] += 1
        counts[key][1] += es.on_battery(r)
    rows: list[Row] = [
        {"reason": k[0], "subreason": k[1], "count": v[0], "on_battery": v[1]}
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1][0])
    ]
    return rows


def _time_rows(es: _ExitScope, fmt: str, key: str, minimum: int) -> list[Row]:
    total = Counter(r.ts.strftime(fmt) for r in es.lmk)
    batt = Counter(r.ts.strftime(fmt) for r in es.lmk_battery)
    rows: list[Row] = [
        {key: k, "kills": n, "on_battery": batt.get(k, 0)}
        for k, n in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= minimum
    ]
    return rows


def _process_rows(es: _ExitScope) -> list[Row]:
    by_label: dict[str, list[_Exit]] = defaultdict(list)
    for r in es.lmk:
        by_label[r.label].append(r)
    rows: list[Row] = [
        {
            "process": label,
            "kills": len(rs),
            "kills_on_battery": sum(1 for r in rs if es.on_battery(r)),
            "last_kill": _fmt(max(r.ts for r in rs)),
            "history_full": any(r.section in es.full for r in rs),
        }
        for label, rs in sorted(by_label.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    return rows


def _exit_tables(es: _ExitScope, info: _ExitInfo, result: Result) -> None:
    excessive: list[Row] = [
        {
            "time": _fmt(r.ts, "milliseconds"),
            "process": r.label,
            "uid": r.uid,
            "on_battery": es.on_battery(r),
            "description": r.description,
        }
        for r in es.excessive
    ]
    visible: list[Row] = [
        {
            "time": _fmt(r.ts, "milliseconds"),
            "process": r.label,
            "importance": r.importance,
            "lmkd_adj": es.kill_adj.get(r.index),
        }
        for r in sorted(es.visible, key=operator.attrgetter("ts"), reverse=True)
    ]
    filled_key = f"filled_{es.name}"
    full: list[Row] = [
        {
            "package": k[0],
            "uid": k[1],
            "records": len(info.sections[k]),
            "oldest": _fmt(min(r.ts for r in info.sections[k])),
            filled_key: k in es.filled,
        }
        for k in sorted(es.full)
    ]
    full.sort(key=lambda row: (not row[filled_key], row["oldest"] or ""))
    tables = {
        "reasons": _reason_rows(es),
        "low_memory_by_hour": _time_rows(es, "%Y-%m-%d %H:00", "hour", 1),
        "low_memory_bursts": _time_rows(
            es, "%Y-%m-%d %H:%M", "minute", LMK_BURST_PER_MIN
        ),
        "low_memory_by_process": _process_rows(es),
        "excessive_cpu_kills": excessive,
        "visible_low_memory_kills": visible,
        "sections_with_full_history": full,
    }
    for name, rows in tables.items():
        result.add_table(name, rows)


def _exit_evidence(text: Text, records: list[_Exit], limit: int = 3) -> list[Evidence]:
    """Cite the first record of each of the busiest minutes."""
    by_minute: dict[datetime, list[_Exit]] = defaultdict(list)
    for r in records:
        by_minute[_minute(r.ts)].append(r)
    busiest = sorted(by_minute.values(), key=len, reverse=True)[:limit]
    firsts = [min(rs, key=operator.attrgetter("ts")) for rs in busiest]
    return [text.evidence(r.index, r.excerpt) for r in firsts]


def _span(es: _ExitScope) -> str:
    return "since boot" if es.name == "since_boot" else "in the last 24 h"


def _lmk_rate_finding(es: _ExitScope, text: Text) -> Finding | None:
    lmk = es.lmk
    rate_scope = _rate(len(es.settled), es.settled_hours)
    rate_batt = es.battery_rate()
    rates = (rate_scope, rate_batt, es.am_rate())
    worst = max((r for r in rates if r is not None), default=0.0)
    if not lmk or worst < LMK_RATE_MEDIUM_PER_H:
        return None
    settled = ""
    if rate_scope is not None:
        settled = f" ({rate_scope:.0f}/h after the first 15 min)"
    parts = [
        (
            f"At least {len(lmk)} low-memory kills {_span(es)} across "
            f"{len({r.process for r in lmk})} processes{settled}."
        ),
    ]
    if es.battery and rate_batt is not None:
        parts.append(
            f"On battery ({es.battery.hours:.1f} h) there were "
            f"{len(es.lmk_battery)} ({rate_batt:.0f}/h).",
        )
    # process_churn.plug_in_flood reports the minute after plug-in; its kills
    # stay in the metrics here.
    if es.am_lmk is not None and es.am_rate() is not None and es.am_lmk.total:
        parts.append(
            f"The activity manager counted {es.am_lmk.total} lmkd kills since boot "
            f"({es.am_rate():.0f}/h), so exit-info holds only "
            f"{_PCT * len(lmk) / es.am_lmk.total:.0f}% of them.",
        )
    cached_pct = _PCT * len(es.cached) / len(lmk)
    parts.append(
        f"{cached_pct:.0f}% were cached or empty processes, so the cost is cold "
        "starts when the user returns to them.",
    )
    top = Counter(r.label for r in lmk).most_common(5)
    parts.extend(
        [
            "Killed most often: " + ", ".join(f"{p} x{n}" for p, n in top) + ".",
            (
                f"Lower bound: exit-info keeps {es.cap} exits per package, and "
                f"{len(es.filled)} packages filled that history within the window."
            ),
        ],
    )
    return Finding(
        id="exit_info_audit.low_memory_kills",
        title="Apps are killed for low memory many times an hour",
        symptom="slowness",
        severity="high" if worst >= LMK_RATE_HIGH_PER_H else "medium",
        basis="measured",
        window=es.name,
        summary=" ".join(parts),
        metrics={
            "low_memory_kills": len(lmk),
            "kills_per_h_after_first_15min": rate_scope,
            "kills_on_battery": len(es.lmk_battery) if es.battery else None,
            "kills_per_h_on_battery": rate_batt,
            "am_counter_kills_per_h": es.am_rate(),
            "cached_share_pct": round(cached_pct, 1),
            "sections_filled": len(es.filled),
        },
        evidence=[
            *_exit_evidence(text, es.lmk_battery or lmk),
            *([es.am_lmk.evidence] if es.am_lmk else []),
        ],
        recommendation=(
            "Lower the background memory demand: uninstall apps that are not "
            f"used, and set rarely used apps that run in the background to "
            f"Restricted ({_RESTRICT}). Do not use Developer options > "
            "Background process limit; it makes cold starts more frequent."
        ),
        followups=[
            "lmkd_kills: the free memory and lmkd reason at each logged kill",
            "kills_vs_screen_events: whether kills cluster right after unlock",
            "memory_snapshot: which processes hold RAM",
            "Collect again after a day of normal use to see if the rate persists",
        ],
    )


def _excessive_cpu_finding(es: _ExitScope, text: Text) -> Finding | None:
    excessive = es.excessive
    if not excessive:
        return None
    on_batt = sum(1 for r in excessive if es.on_battery(r)) if es.battery else None
    listed = ", ".join(
        f"{p} x{n}" for p, n in Counter(r.label for r in excessive).most_common(5)
    )
    batt_text = f" ({on_batt} on battery)" if on_batt is not None else ""
    return Finding(
        id="exit_info_audit.excessive_cpu_kills",
        title="The system killed background apps for excessive CPU use",
        symptom="battery",
        severity="medium" if (on_batt or 0) >= EXCESSIVE_CPU_MEDIUM else "low",
        basis="measured",
        window=es.name,
        summary=(
            f"{len(excessive)} kills for excessive CPU {_span(es)}{batt_text}: "
            f"{listed}. Android kills a cached app that uses more than its "
            "allowed share of a CPU core over a five-minute check."
        ),
        metrics={"kills": len(excessive), "kills_on_battery": on_batt},
        evidence=[text.evidence(r.index, r.excerpt) for r in excessive[:3]],
        recommendation=(
            "Check what the app does in the background (location, sensors, "
            "sync) and turn off features you do not need, or set it to "
            f"Restricted ({_RESTRICT}). Report repeated kills to the app developer."
        ),
        followups=[
            (
                "process_churn: whether a broadcast or alarm restarts the app "
                "right after each kill (a restart loop)"
            ),
        ],
    )


def _visible_kill_finding(es: _ExitScope, text: Text) -> Finding | None:
    visible = es.visible_confirmed
    if not visible:
        return None
    raised = len(es.visible) - len(visible)
    raised_text = (
        f" lmkd picked {raised} more at a cached oom_score_adj; their importance "
        "was raised afterwards."
        if raised
        else ""
    )
    return Finding(
        id="exit_info_audit.visible_low_memory_kills",
        title="Low-memory kills hit foreground or visible processes",
        symptom="slowness",
        severity="medium" if len(visible) >= VISIBLE_KILLS_MEDIUM else "low",
        basis="measured",
        window=es.name,
        summary=(
            f"{len(visible)} low-memory kills {_span(es)} hit processes at "
            f"importance {IMPORTANCE_VISIBLE} or lower (foreground, foreground "
            "service or visible), which the user notices as an app closing "
            f"or a service restarting.{raised_text}"
        ),
        metrics={"kills": len(visible), "raised_after_lmkd_pick": raised},
        evidence=[text.evidence(r.index, r.excerpt) for r in visible[:3]],
        recommendation=(
            "Reduce memory pressure (see exit_info_audit.low_memory_kills); if "
            "one app is affected repeatedly, update it or check it for leaks."
        ),
        followups=["memory_snapshot: free memory and the largest processes"],
    )


@analyzer("exit_info_audit")
def exit_info_audit(ctx: Context) -> Result:
    """Count process exits by reason since boot and on battery."""
    loaded = _load_exit_info(ctx)
    if loaded is None:
        msg = "no dumpsys activity exit-info"
        raise SkipError(msg)
    text, info = loaded
    if not info.records:
        msg = "exit-info has no parsable records"
        raise SkipError(msg)
    es = _exit_scope(ctx, info)
    result = Result("exit_info_audit", window=es.name)
    if info.skipped:
        result.notes.append(f"{info.skipped} exit-info lines could not be parsed.")
    if es.name != "since_boot":
        result.notes.append("Boot time unknown: 'since boot' means the last 24 h.")
    result.metrics = {
        "exit_records_total": len(info.records),
        "exit_sections_total": len(info.sections),
        "exit_history_per_section": es.cap,
        "sections_with_full_history": len(es.full),
        f"sections_filled_{es.name}": len(es.filled),
        **_exit_metrics(es),
        **_am_lmk_metrics(es),
    }
    _exit_tables(es, info, result)
    result.notes.append(
        f"Exit-info keeps {es.cap} exits per package and UID; {len(es.filled)} "
        "sections filled that history within the window, so their counts are "
        "lower bounds.",
    )
    if raised := len(es.visible) - len(es.visible_confirmed):
        result.notes.append(
            f"{raised} low-memory exits show importance {IMPORTANCE_VISIBLE} or "
            "lower, but lmkd picked them at a cached oom_score_adj (its kill "
            "record, or the activity manager's count of no lmkd kills at adj "
            f"{ADJ_VISIBLE} or lower since boot): the activity manager raised "
            "them after lmkd's choice, so they are not counted as visible kills.",
        )
    findings = (
        _lmk_rate_finding(es, text),
        _excessive_cpu_finding(es, text),
        _visible_kill_finding(es, text),
    )
    result.findings = [f for f in findings if f is not None]
    return result


# --- lmkd kills --------------------------------------------------------------

_KILL_TEXT_RE = re.compile(
    r"Kill '(?P<name>[^']*)' \((?P<pid>\d+)\), uid (?P<uid>\d+), "
    r"oom_(?:score_)?adj (?P<adj>-?\d+) to free (?P<rss>\d+)kB(?: rss)?"
    r"(?:, (?P<swap>\d+)kB swap)?(?:; reason: (?P<reason>.*))?$",
)
_KILL_TEXT_LINE_RE = re.compile(r"lowmemorykiller\s*: Kill '")
_MEMINFO_LINE_RE = re.compile(r"^(\w[\w()]*):\s+(\d+) kB")
# killinfo payload: pid, uid, oom_adj, min_oom_adj, rss kB, kill_reason, then
# the meminfo fields from MemFree (index 6) and Cached (7). AOSP logs an
# Unevictable field before SwapTotal (index 12); some vendor builds omit it
# (index 11). CmaFree comes 12 places later. Other vendors insert fields
# (Samsung logs MemTotal at index 6), so the meminfo fields are read only
# once SwapTotal is found where AOSP puts it.
_KILLINFO_MIN_FIELDS = 8
_MEM_FREE_INDEX = 6
_CACHED_INDEX = 7
_SWAP_TOTAL_INDEXES = (11, 12)
_CMA_OFFSET = 12
_PSI_FIELDS = 5
_PSI_CPU_SOME = 4
_PAIR_WINDOW = timedelta(seconds=5)
_ADJ_UNKNOWN = 1001
# AOSP lmkd kill_reasons enum; the numbering changes between lmkd versions, so
# the paired "reason:" text from the main log wins when it is present.
_LMKD_REASONS = {
    0: "pressure after kill",
    1: "not responding",
    2: "low swap and thrashing",
    3: "low mem and swap",
    4: "low mem and thrashing",
    5: "direct reclaim and thrashing",
    6: "low mem and swap utilization",
    7: "low file cache after thrashing",
    8: "low mem (watermark)",
    9: "direct reclaim stuck",
}
_MEM_FACTOR_CRITICAL = "3"


@dataclass
class _Kill:
    ts: datetime
    pid: int
    uid: int | None
    adj: int | None
    rss_kib: int | None
    evidence: Evidence
    name: str = ""
    reason_code: int | None = None
    reason_text: str = ""
    reason_from: str = ""
    values: list[str] = field(default_factory=list)
    mem_free_kib: int | None = None
    cached_kib: int | None = None
    swap_free_kib: int | None = None
    cma_free_kib: int | None = None
    psi: tuple[float, ...] | None = None

    @property
    def psi_cpu(self) -> float | None:
        return self.psi[_PSI_CPU_SOME] if self.psi else None


def _proc_meminfo(ctx: Context) -> dict[str, int]:
    """Return ``/proc/meminfo`` as ``{field: kB}``."""
    text = ctx.sources.get("proc_meminfo")
    if text is None:
        return {}
    return {
        m[1]: int(m[2]) for line in text.lines if (m := _MEMINFO_LINE_RE.match(line))
    }


def _killinfo_psi(values: list[str]) -> tuple[float, ...] | None:
    """Return the trailing PSI avg10 floats of a killinfo record, if present."""
    tail = values[-_PSI_FIELDS:]
    if len(values) <= _PSI_FIELDS or not all("." in v for v in tail):
        return None
    try:
        return tuple(float(v) for v in tail)
    except ValueError:
        return None


def _parse_killinfo(events: EventLog) -> list[_Kill]:
    """Parse ``killinfo`` event payloads (comma lists)."""
    kills: list[_Kill] = []
    for line in events.by_tag("killinfo"):
        values = [v.strip() for v in _fields(line)]
        pid = _int_at(values, 0)
        if pid is None or len(values) < _KILLINFO_MIN_FIELDS:
            continue
        kills.append(
            _Kill(
                ts=line.ts,
                pid=pid,
                uid=_int_at(values, 1),
                adj=_int_at(values, 2),
                rss_kib=_int_at(values, 4),
                evidence=_cite_event(events, line),
                reason_code=_int_at(values, 5),
                values=values,
                psi=_killinfo_psi(values),
            ),
        )
    return kills


def _swap_total_index(kills: list[_Kill], swap_total_kib: int | None) -> int | None:
    """Find where SwapTotal sits in killinfo, validating the layout."""
    for idx in _SWAP_TOTAL_INDEXES:
        pairs = [(_int_at(k.values, idx), _int_at(k.values, idx + 1)) for k in kills]
        valid = [(t, f) for t, f in pairs if t is not None and f is not None]
        if not valid or len(valid) < len(pairs):
            continue
        totals = {t for t, _ in valid}
        if swap_total_kib is not None:
            if totals == {swap_total_kib}:
                return idx
        elif len(totals) == 1 and all(0 <= f <= t for t, f in valid):
            return idx
    return None


def _parse_kill_texts(ctx: Context) -> tuple[list[_Kill], int]:
    """Parse lmkd ``Kill '...'`` lines from the main log."""
    text = ctx.sources.get("logcat_system")
    if text is None:
        return [], 0
    reference = ctx.windows.log_reference()
    kills: list[_Kill] = []
    skipped = 0
    for i, line in enumerate(text.lines):
        if not _KILL_TEXT_LINE_RE.search(line):
            continue
        parsed = next(iter_logcat(line, reference, text.first_line + i), None)
        m = _KILL_TEXT_RE.search(parsed.message) if parsed else None
        if parsed is None or m is None:
            skipped += 1
            continue
        kill = _Kill(
            ts=parsed.ts,
            pid=int(m["pid"]),
            uid=int(m["uid"]),
            adj=int(m["adj"]),
            rss_kib=int(m["rss"]),
            evidence=text.evidence(i),
            name=m["name"],
            reason_text=(m["reason"] or "").strip(),
        )
        kill.reason_from = "main log" if kill.reason_text else ""
        kills.append(kill)
    return kills, skipped


@dataclass
class _LmkdRecords:
    """lmkd kills as logged: killinfo events and main-log Kill lines."""

    infos: list[_Kill]
    texts: list[_Kill]
    skipped: int

    @property
    def all(self) -> list[_Kill]:
        return [*self.infos, *self.texts]


def _lmkd_records(ctx: Context) -> _LmkdRecords:
    """Parse the lmkd kill records once per run; callers must not modify them."""

    def build() -> _LmkdRecords:
        texts, skipped = _parse_kill_texts(ctx)
        return _LmkdRecords(_parse_killinfo(load_event_log(ctx)), texts, skipped)

    return ctx.sources.memo("memory.lmkd_records", build)


def _pid_names(events: EventLog) -> dict[int, str]:
    """Map PIDs to process names from process start, death and kill events."""
    names: dict[int, str] = {}
    for tag, name_index in (("am_proc_start", 3), ("am_proc_died", 2), ("am_kill", 2)):
        for line in events.by_tag(tag):
            parts = _fields(line)
            pid = _int_at(parts, 1)
            if pid is not None and len(parts) > name_index:
                names[pid] = parts[name_index]
    return names


def _pair_kills(infos: list[_Kill], texts: list[_Kill]) -> list[_Kill]:
    """Copy name and reason from Kill lines to killinfo records with the same PID.

    Returns the Kill lines that have no killinfo twin.
    """
    by_pid: dict[int, list[_Kill]] = defaultdict(list)
    for t in texts:
        by_pid[t.pid].append(t)
    used: set[int] = set()
    for k in infos:
        twin = next(
            (
                t
                for t in by_pid.get(k.pid, [])
                if id(t) not in used and abs(t.ts - k.ts) <= _PAIR_WINDOW
            ),
            None,
        )
        if twin is not None:
            used.add(id(twin))
            k.name, k.reason_text, k.reason_from = (
                twin.name,
                twin.reason_text,
                "main log",
            )
    return [t for t in texts if id(t) not in used]


def _merge_kills(
    infos: list[_Kill], texts: list[_Kill], ctx: Context, names: dict[int, str]
) -> list[_Kill]:
    """Merge killinfo and Kill lines; fill in names and reason texts."""
    kills = [*infos, *_pair_kills(infos, texts)]
    learned: dict[int, Counter[str]] = defaultdict(Counter)
    for k in kills:
        if k.reason_code is not None and k.reason_from == "main log" and k.reason_text:
            learned[k.reason_code][k.reason_text] += 1
    for k in kills:
        if not k.name:
            fallback = ctx.packages.name(k.uid) if k.uid is not None else ""
            k.name = names.get(k.pid) or fallback
        if k.reason_text or k.reason_code is None:
            continue
        if k.reason_code in learned:
            k.reason_text = learned[k.reason_code].most_common(1)[0][0]
            k.reason_from = "same kill_reason code as logged kills"
        else:
            k.reason_text = _LMKD_REASONS.get(k.reason_code, f"code {k.reason_code}")
            k.reason_from = "AOSP kill_reason enum (version-specific)"
    kills.sort(key=operator.attrgetter("ts"))
    return kills


def _max_in_window(
    times: list[datetime], window: timedelta
) -> tuple[int, datetime | None]:
    """Return the most sorted ``times`` within one ``window``, and its start."""
    best, start, j = 0, None, 0
    for i, ts in enumerate(times):
        while ts - times[j] > window:
            j += 1
        if i - j + 1 > best:
            best, start = i - j + 1, times[j]
    return best, start


def _kill_row(k: _Kill) -> Row:
    return {
        "time": _fmt(k.ts, "milliseconds"),
        "process": k.name,
        "pid": k.pid,
        "adj": k.adj,
        "rss_mib": _mib(k.rss_kib),
        "reason": k.reason_text,
        "reason_from": k.reason_from,
        "mem_free_mib": _mib(k.mem_free_kib),
        "cached_mib": _mib(k.cached_kib),
        "swap_free_mib": _mib(k.swap_free_kib),
        "cma_free_mib": _mib(k.cma_free_kib),
        "psi_cpu_some_avg10_pct": k.psi_cpu,
    }


@dataclass
class _LmkdFacts:
    kills: list[_Kill]
    battery: _BatteryWindow | None
    plug_in: datetime | None
    events: EventLog

    def in_flood(self, ts: datetime) -> bool:
        return self.plug_in is not None and (
            self.plug_in <= ts < self.plug_in + PLUG_IN_FLOOD_WINDOW
        )

    @property
    def on_battery(self) -> list[_Kill]:
        b = self.battery
        return [k for k in self.kills if b and b.contains(k.ts)]

    @property
    def big_free(self) -> list[_Kill]:
        return [k for k in self.kills if (k.mem_free_kib or 0) > KILL_FREE_MEMORY_KIB]

    def storm(self, *, outside_flood: bool) -> tuple[int, datetime | None]:
        times = [
            k.ts for k in self.kills if not (outside_flood and self.in_flood(k.ts))
        ]
        return _max_in_window(times, KILL_STORM_WINDOW)


def _values_range(values: Iterable[int | None]) -> tuple[float | None, float | None]:
    present = [v for v in values if v is not None]
    return (_mib(min(present)), _mib(max(present))) if present else (None, None)


def _lmkd_metrics(f: _LmkdFacts, layout: str | None) -> Row:
    kills = f.kills
    free = [k.mem_free_kib for k in kills if k.mem_free_kib is not None]
    storm, storm_start = f.storm(outside_flood=False)
    storm_out, storm_out_start = f.storm(outside_flood=True)
    factors = f.events.by_tag("am_mem_factor")
    span = f.events.span()
    free_b = _values_range(k.mem_free_kib for k in f.on_battery)
    cached_b = _values_range(k.cached_kib for k in f.on_battery)
    exit_metrics = {
        "lmkd_kills_logged": len(kills),
        "killinfo_layout": layout,
        "event_log_start": _fmt(span[0]) if span else None,
        "event_log_end": _fmt(span[1]) if span else None,
        "first_kill": _fmt(kills[0].ts, "milliseconds"),
        "last_kill": _fmt(kills[-1].ts, "milliseconds"),
        "top_reason": Counter(k.reason_text or "unknown" for k in kills).most_common(1)[
            0
        ][0],
        "mem_free_at_kill_min_mib": _mib(min(free)) if free else None,
        "mem_free_at_kill_median_mib": _mib(statistics.median(free)) if free else None,
        "mem_free_at_kill_max_mib": _mib(max(free)) if free else None,
        "kills_mem_free_over_1gib": len(f.big_free),
        "kills_adj_below_900": sum(
            1 for k in kills if (k.adj or ADJ_CACHED) < ADJ_CACHED
        ),
        "kills_adj_200_or_less": sum(
            1 for k in kills if k.adj is not None and k.adj <= ADJ_VISIBLE
        ),
        "max_kills_in_10s": storm,
        "max_kills_in_10s_start": _fmt(storm_start, "milliseconds"),
        "max_kills_in_10s_outside_plug_in": storm_out,
        "max_kills_in_10s_outside_plug_in_start": _fmt(storm_out_start, "milliseconds"),
        "plug_in_time": _fmt(f.plug_in, "milliseconds"),
        "lmkd_kills_60s_after_plug_in": sum(1 for k in kills if f.in_flood(k.ts)),
        **_battery_metrics(f.battery),
        "lmkd_kills_on_battery": len(f.on_battery) if f.battery else None,
        "on_battery_mem_free_at_kill_min_mib": free_b[0],
        "on_battery_mem_free_at_kill_max_mib": free_b[1],
        "on_battery_cached_at_kill_min_mib": cached_b[0],
        "on_battery_cached_at_kill_max_mib": cached_b[1],
        "am_mem_factor_events": len(factors),
        "am_mem_factor_critical_events": sum(
            1 for e in factors if _fields(e)[0].strip() == _MEM_FACTOR_CRITICAL
        ),
    }
    for index, name in enumerate(
        ("memory_some", "memory_full", "io_some", "io_full", "cpu_some")
    ):
        values = [k.psi[index] for k in kills if k.psi]
        exit_metrics[f"psi_{name}_avg10_at_kill_max_pct"] = max(values, default=None)
    return exit_metrics


def _free_memory_finding(f: _LmkdFacts, m: Row) -> Finding | None:
    big = f.big_free
    if len(big) < KILL_FREE_MIN_COUNT:
        return None
    lo, hi = _values_range(k.mem_free_kib for k in big)
    c_lo, c_hi = _values_range(k.cached_kib for k in big)
    reason = Counter(k.reason_text for k in big).most_common(1)[0][0]
    parts = [
        (
            f"{len(big)} of {len(f.kills)} lmkd kills in the log ({m['first_kill']} "
            f"to {m['last_kill']}) happened with {lo:.0f}-{hi:.0f} MiB MemFree"
        ),
    ]
    if c_lo is not None and c_hi is not None:
        parts.append(f" and {c_lo:.0f}-{c_hi:.0f} MiB of page cache")
    parts.append(f"; lmkd's reason: '{reason}'.")
    b_lo, b_hi = (
        m["on_battery_mem_free_at_kill_min_mib"],
        m["on_battery_mem_free_at_kill_max_mib"],
    )
    if b_lo is not None:
        parts.append(
            f" {len(f.on_battery)} of the kills were on battery, with MemFree "
            f"{b_lo:.0f}-{b_hi:.0f} MiB.",
        )
    parts.append(
        " Why lmkd sees a breached watermark with that much free memory is not "
        "shown by the log.",
    )
    return Finding(
        id="lmkd_kills.kills_with_free_memory",
        title="lmkd kills apps while more than 1 GiB of RAM is free",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="log_coverage",
        summary="".join(parts),
        metrics={"kills": len(big), "mem_free_min_mib": lo, "mem_free_max_mib": hi},
        evidence=[k.evidence for k in big[:3]],
        recommendation=(
            "Free memory is not the limit here, so closing apps will not help "
            "much. Check zone_watermarks_offline for a memory zone below its "
            "watermark or memory taken offline, and report lmkd kills with "
            "gigabytes free to the phone maker with a bugreport. Reducing "
            "always-running apps still lowers the kill rate."
        ),
        followups=[
            "zone_watermarks_offline: free memory per zone and lmkd's watermark",
            (
                "Take a bugreport right after 5+ minutes of screen-off to catch "
                "'mem-offline' kernel messages"
            ),
        ],
    )


def _storm_finding(f: _LmkdFacts) -> Finding | None:
    """Report the largest kill storm outside the minute after plug-in.

    Storms in that minute are part of process_churn.plug_in_flood.
    """
    count, start = f.storm(outside_flood=True)
    if count <= KILL_STORM_COUNT or start is None:
        return None
    window = [
        k
        for k in f.kills
        if start <= k.ts <= start + KILL_STORM_WINDOW and not f.in_flood(k.ts)
    ]
    cpu = max((k.psi_cpu for k in window if k.psi_cpu is not None), default=None)
    severe = cpu is not None and cpu > PSI_CPU_AT_KILL_PCT
    summary = f"{count} lmkd kills within 10 s from {_fmt(start)}"
    if cpu is not None:
        summary += f"; CPU some-stall (avg10) reached {cpu:.0f}% at kill time"
    summary += (
        ". Killing and restarting apps at once competes with what the user is doing."
    )
    return Finding(
        id="lmkd_kills.kill_storm",
        title="lmkd killed many apps within seconds",
        symptom="slowness",
        severity="medium" if severe else "low",
        basis="measured",
        window="log_coverage",
        summary=summary,
        metrics={"kills_in_10s": count, "psi_cpu_some_avg10_max_pct": cpu},
        evidence=[k.evidence for k in window[:3]],
        recommendation=(
            "Look at what happened just before the storm (unlock, plug-in, an app "
            "launch) in process_churn; restrict apps that start many background "
            "jobs at once."
        ),
        followups=["process_churn: process starts around the same minute"],
    )


def _visible_lmkd_finding(f: _LmkdFacts) -> Finding | None:
    visible = [k for k in f.kills if k.adj is not None and k.adj <= ADJ_VISIBLE]
    if not visible:
        return None
    names = ", ".join(sorted({k.name for k in visible})[:5])
    return Finding(
        id="lmkd_kills.visible_kills",
        title="lmkd killed foreground or visible processes",
        symptom="slowness",
        severity="high",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{len(visible)} lmkd kills hit processes at oom_score_adj "
            f"{ADJ_VISIBLE} or lower, which the user sees: {names}."
        ),
        metrics={"kills": len(visible)},
        evidence=[k.evidence for k in visible[:3]],
        recommendation=(
            "This is severe memory pressure: remove or restrict memory-heavy "
            "background apps, and check memory_snapshot for the largest ones."
        ),
        followups=["memory_snapshot: free memory, swap and the largest processes"],
    )


def _layout_label(infos: list[_Kill], swap_idx: int | None) -> str | None:
    if not infos:
        return None
    labels = {
        11: "vendor (no Unevictable field; SwapTotal is field 12)",
        12: "AOSP (SwapTotal is field 13)",
    }
    return labels.get(swap_idx, "unvalidated")


def _apply_layout(infos: list[_Kill], swap_idx: int | None) -> None:
    """Read the meminfo fields once the killinfo layout is known."""
    if swap_idx is None:
        return
    for k in infos:
        k.mem_free_kib = _int_at(k.values, _MEM_FREE_INDEX)
        k.cached_kib = _int_at(k.values, _CACHED_INDEX)
        k.swap_free_kib = _int_at(k.values, swap_idx + 1)
        k.cma_free_kib = _int_at(k.values, swap_idx + _CMA_OFFSET)


def _lmkd_tables(f: _LmkdFacts, result: Result) -> None:
    ordered = sorted(
        f.kills,
        key=lambda k: (
            _ADJ_UNKNOWN if k.adj is None else k.adj,
            -(k.mem_free_kib or 0),
        ),
    )
    reasons = Counter(k.reason_text or "unknown" for k in f.kills)
    am_reasons = Counter(
        ",".join(_fields(e)[4:-1]).split(" #", maxsplit=1)[0] or "unknown"
        for e in f.events.by_tag("am_kill")
    )
    result.add_table("kills", [_kill_row(k) for k in ordered])
    for name, counts in (("reasons", reasons), ("am_kill_reasons", am_reasons)):
        result.add_table(
            name, [{"reason": r, "kills": n} for r, n in counts.most_common()]
        )


def _lmkd_notes(ctx: Context, kills: list[_Kill], result: Result) -> None:
    exit_result = ctx.results.get("exit_info_audit")
    exit_lmk = (
        exit_result.metrics.get("low_memory_kills_since_boot") if exit_result else None
    )
    if exit_lmk:
        result.metrics["low_memory_kills_since_boot_from_exit_info"] = exit_lmk
        result.notes.append(
            f"The lmkd reason is known only for the {len(kills)} kills inside the "
            f"log window; exit-info counts {exit_lmk} low-memory kills since boot.",
        )
    by_code = sum(1 for k in kills if k.reason_from.startswith("same kill_reason"))
    if by_code:
        result.notes.append(
            f"{by_code} kills have no Kill line in the main log (it rotates faster); "
            "their reason text is taken from logged kills with the same kill_reason.",
        )


@analyzer("lmkd_kills", after=("windows", "exit_info_audit"))
def lmkd_kills(ctx: Context) -> Result:
    """Report lmkd kills: reason, free memory and pressure at each kill."""
    events = load_event_log(ctx)
    records = _lmkd_records(ctx)
    # Copies: pairing fills in names and reasons, and other analyzers share
    # the parsed records.
    infos = [replace(k) for k in records.infos]
    texts = [replace(k) for k in records.texts]
    if not infos and not texts:
        msg = "no lmkd kill records (killinfo events or lowmemorykiller lines)"
        raise SkipError(msg)
    result = Result("lmkd_kills", window="log_coverage")
    if records.skipped:
        result.notes.append(
            f"{records.skipped} lowmemorykiller lines could not be parsed."
        )
    swap_idx = _swap_total_index(infos, _proc_meminfo(ctx).get("SwapTotal"))
    if infos and swap_idx is None:
        result.notes.append(
            "The killinfo layout could not be validated against SwapTotal, so "
            "MemFree, page cache, swap and CmaFree at each kill are not read: "
            "vendor builds insert fields before them.",
        )
    _apply_layout(infos, swap_idx)
    kills = _merge_kills(infos, texts, ctx, _pid_names(events))
    battery = _battery_window(ctx)
    facts = _LmkdFacts(kills, battery, _plug_in_time(ctx, events), events)
    result.metrics = {
        **_lmkd_metrics(facts, _layout_label(infos, swap_idx)),
        "killinfo_records": len(infos),
        "kill_text_lines": len(texts),
        "am_kill_events": len(events.by_tag("am_kill")),
    }
    _lmkd_notes(ctx, kills, result)
    storm, storm_start = facts.storm(outside_flood=False)
    if storm > KILL_STORM_COUNT and storm_start and facts.in_flood(storm_start):
        result.notes.append(
            f"The largest kill storm ({storm} kills within 10 s) came in the "
            "minute after plug-in; process_churn.plug_in_flood reports that "
            "minute.",
        )
    _lmkd_tables(facts, result)
    findings = (
        _free_memory_finding(facts, result.metrics),
        _storm_finding(facts),
        _visible_lmkd_finding(facts),
    )
    result.findings = [f for f in findings if f is not None]
    return result


# --- Kills versus screen transitions ----------------------------------------

_USAGE_SCREEN_RE = re.compile(
    r'time="(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)" '
    r"type=(SCREEN_INTERACTIVE|SCREEN_NON_INTERACTIVE)\b",
)


def _usage_transitions(usage: Text) -> list[Transition]:
    """Return SCREEN_INTERACTIVE/NON_INTERACTIVE events from usagestats."""
    found: dict[tuple[datetime, bool], Transition] = {}
    for i, line in enumerate(usage.lines):
        if "type=SCREEN_" not in line:
            continue
        m = _USAGE_SCREEN_RE.search(line)
        ts = _parse_wall(m[1]) if m else None
        if m is None or ts is None:
            continue
        on = m[2] == "SCREEN_INTERACTIVE"
        cite = usage.evidence(i)
        found.setdefault((ts, on), Transition(ts, on, cite.ref, cite.excerpt))
    return list(found.values())


def _screen_transitions(ctx: Context, events: EventLog) -> tuple[list[Transition], str]:
    """Return screen on/off transitions, from usagestats or the event log.

    Repeated states collapse into the first, but not across a boot: a reboot
    ends the previous screen state.
    """
    usage = ctx.sources.get("usagestats")
    found = _usage_transitions(usage) if usage is not None else []
    source = usage.origin if usage is not None else ""
    if not found and events.text is not None:
        found = events.screen_transitions()
        source = events.text.origin
    found.sort(key=operator.attrgetter("ts"))
    boot = ctx.windows.boot_time
    collapsed: list[Transition] = []
    for t in found:
        last = collapsed[-1] if collapsed else None
        rebooted = last is not None and boot is not None and last.ts < boot <= t.ts
        if last is None or last.on != t.on or rebooted:
            collapsed.append(t)
    return collapsed, source


@dataclass
class _ScreenStats:
    kills: int = 0
    early_on: int = 0
    first_min_on: int = 0
    early_off: int = 0
    later_on: int = 0
    later_off: int = 0
    unknown: int = 0
    screen_ons: int = 0
    screen_offs: int = 0
    ons_with_burst: int = 0

    def per_screen_on(self) -> float | None:
        return round(self.early_on / self.screen_ons, 1) if self.screen_ons else None

    def add(self, transition: Transition | None, delta: timedelta) -> None:
        """Count one kill ``delta`` after its latest preceding ``transition``."""
        self.kills += 1
        if transition is None:
            self.unknown += 1
        elif delta >= SCREEN_WINDOW:
            self.later_on += transition.on
            self.later_off += not transition.on
        elif transition.on:
            self.early_on += 1
            self.first_min_on += delta < timedelta(minutes=1)
        else:
            self.early_off += 1


@dataclass
class _ScreenWindow:
    start: datetime
    end: datetime
    count_end: datetime  # transitions after this belong to the next window


def _classify(
    kills: list[datetime],
    transitions: list[Transition],
    window: _ScreenWindow,
) -> tuple[_ScreenStats, Counter[int]]:
    """Attribute each kill in the window to the latest transition before it."""
    times = [t.ts for t in transitions]
    stats = _ScreenStats()
    per_transition: Counter[int] = Counter()
    for kill in kills:
        if not window.start <= kill < window.end:
            continue
        j = bisect.bisect_right(times, kill) - 1
        transition = transitions[j] if j >= 0 else None
        delta = kill - times[j] if j >= 0 else timedelta(0)
        stats.add(transition, delta)
        if transition is not None and delta < SCREEN_WINDOW:
            per_transition[j] += 1
    for j, t in enumerate(transitions):
        if not window.start <= t.ts < window.count_end:
            continue
        stats.screen_ons += t.on
        stats.screen_offs += not t.on
        stats.ons_with_burst += t.on and per_transition[j] >= SCREEN_BURST_MIN_KILLS
    return stats, per_transition


def _stats_metrics(prefix: str, stats: _ScreenStats) -> Row:
    return {
        f"{prefix}_low_memory_kills": stats.kills,
        f"{prefix}_kills_0_3min_after_screen_on": stats.early_on,
        f"{prefix}_kills_first_min_after_screen_on": stats.first_min_on,
        f"{prefix}_kills_0_3min_after_screen_off": stats.early_off,
        f"{prefix}_kills_screen_on_later": stats.later_on,
        f"{prefix}_kills_screen_off_later": stats.later_off,
        f"{prefix}_kills_before_first_transition": stats.unknown,
        f"{prefix}_screen_ons": stats.screen_ons,
        f"{prefix}_screen_offs": stats.screen_offs,
        f"{prefix}_kills_per_screen_on": stats.per_screen_on(),
        f"{prefix}_screen_ons_with_burst": stats.ons_with_burst,
    }


def _overlap_label(
    start: datetime, end: datetime, battery: _BatteryWindow | None
) -> str:
    if battery is None:
        return "unknown"
    if battery.start <= start and end <= battery.end:
        return "yes"
    if end <= battery.start or start >= battery.end:
        return "no"
    return "partly"


def _screen_off_stretches(
    kills: list[datetime],
    transitions: list[Transition],
    battery: _BatteryWindow | None,
) -> list[Row]:
    """Return screen-off stretches of at least LONG_SCREEN_OFF with their kills."""
    rows: list[Row] = []
    for off, on in itertools.pairwise(transitions):
        if off.on or not on.on or on.ts - off.ts < LONG_SCREEN_OFF:
            continue
        hi = bisect.bisect_left(kills, on.ts)
        total = hi - bisect.bisect_left(kills, off.ts)
        later = max(hi - bisect.bisect_left(kills, off.ts + SCREEN_WINDOW), 0)
        hours = (on.ts - off.ts).total_seconds() / 3600
        rows.append(
            {
                "start": _fmt(off.ts),
                "end": _fmt(on.ts),
                "duration_min": round(hours * 60),
                "kills": total,
                "kills_after_first_3min": later,
                "kills_per_h": round(later / hours, 1),
                "on_battery": _overlap_label(off.ts, on.ts, battery),
            },
        )
    rows.sort(key=lambda r: (-r["kills"], r["start"]))
    return rows


@dataclass
class _ScreenFacts:
    transitions: list[Transition]
    scope_name: str
    scope: _ScreenStats
    per_transition: Counter[int]
    battery_stats: _ScreenStats | None
    # kills after each transition inside the on-battery window
    battery_per_transition: Counter[int]
    stretches: list[Row]


def _screen_on_finding(f: _ScreenFacts) -> Finding | None:
    batt = f.battery_stats
    use_batt = batt is not None and batt.screen_ons >= SCREEN_BURSTS_MIN
    stats = batt if use_batt and batt is not None else f.scope
    per_on = stats.per_screen_on()
    if (
        per_on is None
        or per_on < KILLS_PER_SCREEN_ON_MEDIUM
        or stats.ons_with_burst < SCREEN_BURSTS_MIN
    ):
        return None
    where = {"since_boot": "Since boot", "last_24h": "In the last 24 h"}
    label = "On battery" if use_batt else where.get(f.scope_name, f.scope_name)
    counts = f.battery_per_transition if use_batt else f.per_transition
    top = sorted(
        (j for j, t in enumerate(f.transitions) if t.on and counts[j]),
        key=lambda j: -counts[j],
    )[:3]
    return Finding(
        id="kills_vs_screen_events.kills_after_screen_on",
        title="Low-memory kills cluster in the minutes after the screen turns on",
        symptom="slowness",
        severity="high" if per_on >= KILLS_PER_SCREEN_ON_HIGH else "medium",
        basis="measured",
        window="on_battery" if use_batt else f.scope_name,
        summary=(
            f"{label}, {stats.early_on} of {stats.kills} low-memory kills came "
            f"within 3 min after a screen-on ({stats.first_min_on} in the first "
            f"minute): about {per_on:.0f} per screen-on over {stats.screen_ons} "
            f"screen-ons, {stats.ons_with_burst} of them followed by "
            f"{SCREEN_BURST_MIN_KILLS}+ kills. {stats.early_off} more came within "
            f"3 min after a screen-off. {_NOT_SHOWN}"
        ),
        metrics={
            "kills_per_screen_on": per_on,
            "kills_after_screen_on": stats.early_on,
            "kills_after_screen_off": stats.early_off,
            "screen_ons": stats.screen_ons,
            "screen_ons_with_burst": stats.ons_with_burst,
        },
        evidence=[Evidence(f.transitions[j].ref, f.transitions[j].line) for j in top],
        recommendation=(
            "Apps killed right after unlock are often the ones about to be opened, "
            "so they cold-start. Reduce always-running and background apps "
            f"({_RESTRICT}); if lmkd_kills shows kills with plenty of free memory, "
            "report it to the phone maker."
        ),
        followups=[
            "lmkd_kills: free memory and lmkd reason at the kills after unlock",
            "zone_watermarks_offline: memory taken offline while the screen is off",
            "process_churn: process starts in the same minutes",
        ],
    )


def _screen_off_finding(f: _ScreenFacts) -> Finding | None:
    busy = [s for s in f.stretches if s["kills_per_h"] >= SCREEN_OFF_KILLS_PER_H]
    if not busy:
        return None
    worst = busy[0]
    charging = (
        " It was outside the on-battery window, so the phone was probably "
        "charging; Android runs deferred maintenance then."
        if worst["on_battery"] == "no"
        else ""
    )
    return Finding(
        id="kills_vs_screen_events.kills_while_screen_off",
        title="Many low-memory kills while the screen was off",
        symptom="battery" if worst["on_battery"] == "yes" else "info",
        severity="low",
        basis="measured",
        window=f.scope_name,
        summary=(
            f"{worst['kills']} low-memory kills during the {worst['duration_min']} "
            f"min screen-off stretch from {worst['start']} "
            f"({worst['kills_per_h']:.0f}/h after its first 3 min).{charging} "
            "Background work starts processes that then get killed."
        ),
        metrics={"stretches": len(busy), "worst_kills": worst["kills"]},
        recommendation=(
            "Restrict background activity of apps that sync or run jobs often "
            f"({_RESTRICT})."
        ),
        followups=["process_churn and the job scheduler dump for what started then"],
    )


def _low_memory_times(ctx: Context) -> list[datetime]:
    loaded = _load_exit_info(ctx)
    if loaded is None:
        msg = "no dumpsys activity exit-info"
        raise SkipError(msg)
    _, info = loaded
    kills = sorted(r.ts for r in info.records if r.reason == REASON_LOW_MEMORY)
    if not kills:
        msg = "exit-info has no low-memory kills"
        raise SkipError(msg)
    return kills


def _screen_facts(
    kills: list[datetime],
    transitions: list[Transition],
    battery: _BatteryWindow | None,
    scope: tuple[str, datetime, datetime],
) -> _ScreenFacts:
    name, start, end = scope
    stats, per_transition = _classify(
        kills, transitions, _ScreenWindow(start, end, end)
    )
    battery_stats = None
    battery_counts: Counter[int] = Counter()
    if battery:
        count_end = (
            battery.end - PLUG_WAKE_MARGIN if battery.ends_with_plug_in else battery.end
        )
        window = _ScreenWindow(battery.start, battery.end, count_end)
        battery_stats, counts = _classify(kills, transitions, window)
        # A transition before the window can own kills inside it; cite only
        # transitions that belong to the window.
        battery_counts = Counter(
            {
                j: n
                for j, n in counts.items()
                if battery.start <= transitions[j].ts < count_end
            },
        )
    stretches = _screen_off_stretches(kills, transitions, battery)
    return _ScreenFacts(
        transitions,
        name,
        stats,
        per_transition,
        battery_stats,
        battery_counts,
        stretches,
    )


def _transition_rows(
    f: _ScreenFacts,
    battery: _BatteryWindow | None,
    scope: tuple[str, datetime, datetime],
) -> list[Row]:
    _, start, end = scope
    rows: list[Row] = [
        {
            "time": _fmt(t.ts),
            "screen": "on" if t.on else "off",
            "kills_0_3min": f.per_transition[j],
            "on_battery": bool(battery and battery.contains(t.ts)),
        }
        for j, t in enumerate(f.transitions)
        if start <= t.ts < end
    ]
    rows.sort(key=lambda r: (-r["kills_0_3min"], r["time"]))
    return rows


@analyzer("kills_vs_screen_events")
def kills_vs_screen_events(ctx: Context) -> Result:
    """Relate low-memory kills to screen-on and screen-off transitions."""
    kills = _low_memory_times(ctx)
    transitions, source = _screen_transitions(ctx, load_event_log(ctx))
    if not transitions:
        msg = "no screen on/off events (usagestats or event log screen_toggled)"
        raise SkipError(msg)
    battery = _battery_window(ctx)
    scope = _scope(ctx, kills[-1])
    facts = _screen_facts(kills, transitions, battery, scope)
    result = Result(
        "kills_vs_screen_events", window="on_battery" if battery else scope[0]
    )
    result.notes += [
        f"Screen transitions from {source}, {_fmt(transitions[0].ts)} onwards.",
        f"Kills are attributed to the latest screen transition before. {_NOT_SHOWN}",
    ]
    result.metrics = {
        **_battery_metrics(battery),
        **_stats_metrics(scope[0], facts.scope),
    }
    if facts.battery_stats is not None:
        result.metrics.update(_stats_metrics("on_battery", facts.battery_stats))
    result.add_table("transitions", _transition_rows(facts, battery, scope))
    result.add_table("long_screen_off", facts.stretches)
    findings = (_screen_on_finding(facts), _screen_off_finding(facts))
    result.findings = [f for f in findings if f is not None]
    return result


# --- Memory snapshot -----------------------------------------------------------

# Kilobyte numbers in meminfo: thousands may be grouped by ",", "." or spaces.
_NUM = r"\d[\d,.\u00a0\u202f ]*"
_SWAP_SUFFIX = rf"(?:\s+\(\s*(?P<swap>{_NUM})K in swap\))?\s*$"
_MEMINFO_PROC_RE = re.compile(
    rf"^\s+(?P<kb>{_NUM})K: (?P<name>.+?) \(pid (?P<pid>\d+)(?: / activities)?\)"
    + _SWAP_SUFFIX,
)
_MEMINFO_GROUP_RE = re.compile(
    rf"^\s+(?P<kb>{_NUM})K: (?P<name>[A-Z][A-Za-z ]+?)" + _SWAP_SUFFIX,
)
_MEMINFO_SECTION_RE = re.compile(
    r"^Total (PSS|RSS) by (process|OOM adjustment|category):",
)
_SUMMARY_RES = {
    "total_ram": re.compile(
        rf"Total RAM:\s+(?P<kb>{_NUM})K(?: \(status (?P<status>\w+)\))?"
    ),
    "free_ram": re.compile(rf"Free RAM:\s+(?P<kb>{_NUM})K"),
    "used_ram": re.compile(rf"Used RAM:\s+(?P<kb>{_NUM})K"),
    "lost_ram": re.compile(rf"Lost RAM:\s+(?P<kb>-?{_NUM})K"),
}
_ZRAM_RE = re.compile(
    rf"ZRAM:\s+(?P<phys>{_NUM})K physical used for\s+(?P<swap>{_NUM})K in swap "
    rf"\(\s*(?P<total>{_NUM})K total swap\)",
)
_UPTIME_RE = re.compile(r"Uptime: (\d+) Realtime: (\d+)")
_DETAIL_HEADER_RE = re.compile(r"^\*\* MEMINFO in pid (\d+) \[(.*)\] \*\*")
_DETAIL_TOTAL_RE = re.compile(
    r"TOTAL(?: PSS)?:\s+(\d+)(?:\s+TOTAL RSS:\s+(\d+))?"
    r"\s+TOTAL SWAP(?: PSS| \(KB\))?:\s+(\d+)",
)


@dataclass
class _MemProc:
    name: str
    pid: int
    pss_kib: int
    index: int
    swap_kib: int | None = None
    group: str = ""
    rss_kib: int | None = None
    detail_pss_kib: int | None = None
    detail: Evidence | None = None  # the per-process TOTAL line, if any


@dataclass
class _Meminfo:
    procs: list[_MemProc] = field(default_factory=list)
    groups: dict[str, list[int]] = field(default_factory=dict)  # [kB, processes]
    summary: Row = field(default_factory=dict)
    skipped: int = 0
    section: str = ""
    group: str = ""
    by_pid: dict[int, _MemProc] = field(default_factory=dict)
    rss: dict[int, int] = field(default_factory=dict)


def _meminfo_summary(line: str, summary: Row) -> None:
    """Fill the RAM summary fields found on ``line``."""
    for key, regex in _SUMMARY_RES.items():
        if m := regex.search(line):
            summary[f"{key}_kib"] = _kb(m["kb"])
            if key == "total_ram":
                summary["status"] = m["status"]
            return
    if m := _ZRAM_RE.search(line):
        summary["zram_physical_kib"] = _kb(m["phys"])
        summary["swap_used_kib"] = _kb(m["swap"])
        summary["swap_total_kib"] = _kb(m["total"])
    elif m := _UPTIME_RE.search(line):
        summary["realtime_ms"] = int(m[2])


def _meminfo_table_line(info: _Meminfo, line: str, index: int) -> bool:
    """Handle one indented table line; return False if it should have parsed."""
    proc = _MEMINFO_PROC_RE.match(line)
    if info.section == "RSS process" and proc:
        info.rss[int(proc["pid"])] = _kb(proc["kb"])
    elif info.section == "PSS process" and proc:
        new = _MemProc(proc["name"], int(proc["pid"]), _kb(proc["kb"]), index)
        new.swap_kib = _kb(proc["swap"]) if proc["swap"] else None
        info.procs.append(new)
        info.by_pid[new.pid] = new
    elif info.section == "PSS OOM adjustment" and proc:
        if (known := info.by_pid.get(int(proc["pid"]))) is not None:
            known.group = info.group
    elif info.section == "PSS OOM adjustment" and (g := _MEMINFO_GROUP_RE.match(line)):
        info.group = g["name"]
        info.groups[info.group] = [_kb(g["kb"]), 0]
    elif info.section in {"PSS process", "PSS OOM adjustment"}:
        return not line.strip()
    return True


def _parse_meminfo(text: Text) -> _Meminfo:
    """Parse the ``dumpsys meminfo`` summary (PSS by process and OOM group)."""
    info = _Meminfo()
    for i, line in enumerate(text.lines):
        if m := _MEMINFO_SECTION_RE.match(line):
            info.section = f"{m[1]} {m[2]}"
            continue
        if line.strip() and not line.startswith(" "):
            info.section = ""
        if info.section and "RAM:" not in line:
            info.skipped += not _meminfo_table_line(info, line, i)
        else:
            _meminfo_summary(line, info.summary)
    for proc in info.procs:
        proc.rss_kib = info.rss.get(proc.pid)
        if proc.group in info.groups:
            info.groups[proc.group][1] += 1
    return info


def _add_meminfo_detail(text: Text | None, info: _Meminfo) -> int:
    """Take PSS, RSS and SwapPss from per-process blocks; return their count."""
    blocks: set[int] = set()
    pid: int | None = None
    for i, line in enumerate(text.lines if text is not None else []):
        if m := _DETAIL_HEADER_RE.match(line):
            pid = int(m[1])
        elif text is not None and pid is not None:
            if not (m := _DETAIL_TOTAL_RE.search(line)):
                continue
            blocks.add(pid)
            if proc := info.by_pid.get(pid):
                proc.detail_pss_kib, proc.swap_kib = int(m[1]), int(m[3])
                proc.rss_kib = int(m[2]) if m[2] else proc.rss_kib
                proc.detail = text.evidence(i, f"[{proc.name}] {line}")
            pid = None
    return len(blocks)


def _third_party(ctx: Context) -> frozenset[str]:
    """Return the names of user-installed packages."""
    packages = ctx.packages
    return frozenset(
        name for app_id in packages.third_party for name in packages.packages(app_id)
    )


@dataclass
class _Snapshot:
    text: Text
    info: _Meminfo
    rows: list[Row]
    swap_total: int | None
    swap_free: int | None
    limit: int | None
    metrics: Row


def _snapshot_row(p: _MemProc, third: frozenset[str], ratio: float | None) -> Row:
    """Describe one process; resident = per-process PSS minus SwapPss.

    With a per-process dump, PSS, swap and RSS all come from it, so the three
    describe one moment.
    """
    pss = p.detail_pss_kib if p.detail_pss_kib is not None else p.pss_kib
    resident = pss - p.swap_kib if p.swap_kib is not None else None
    zram = p.swap_kib / ratio if p.swap_kib is not None and ratio else None
    physical = (
        resident + zram if resident is not None and zram is not None else resident
    )
    return {
        "process": p.name,
        "pid": p.pid,
        "pss_mib": _mib(pss),
        "swap_pss_mib": _mib(p.swap_kib),
        "resident_pss_mib": _mib(resident),
        "physical_estimate_mib": _mib(physical),
        "rss_mib": _mib(p.rss_kib),
        "oom_group": p.group,
        "third_party": p.name.split(":")[0] in third,
    }


def _swap_state(s: Row, proc_mem: dict[str, int]) -> tuple[int | None, int | None]:
    total = s.get("swap_total_kib") or proc_mem.get("SwapTotal")
    if "SwapFree" in proc_mem:
        return total, proc_mem["SwapFree"]
    used = s.get("swap_used_kib")
    return total, (total - used if total and used is not None else None)


def _snapshot_metrics(
    info: _Meminfo, proc_mem: dict[str, int], swap: tuple[int | None, int | None]
) -> Row:
    s = info.summary
    cached = info.groups.get("Cached", [0, 0])
    ratio = (
        s["swap_used_kib"] / s["zram_physical_kib"]
        if s.get("zram_physical_kib")
        else None
    )
    return {
        "processes": len(info.procs),
        "status": s.get("status"),
        "total_ram_mib": _mib(s.get("total_ram_kib")),
        "free_ram_mib": _mib(s.get("free_ram_kib")),
        "used_ram_mib": _mib(s.get("used_ram_kib")),
        "lost_ram_mib": _mib(s.get("lost_ram_kib")),
        "zram_physical_mib": _mib(s.get("zram_physical_kib")),
        "swap_used_mib": _mib(s.get("swap_used_kib")),
        "swap_total_mib": _mib(swap[0]),
        "swap_free_mib": _mib(swap[1]),
        "zram_compression_ratio": round(ratio, 2) if ratio else None,
        "mem_available_mib": _mib(proc_mem.get("MemAvailable")),
        "mem_free_mib": _mib(proc_mem.get("MemFree")),
        "cma_total_mib": _mib(proc_mem.get("CmaTotal")),
        "cached_group_pss_mib": _mib(cached[0]),
        "cached_processes": cached[1],
    }


def _hog_finding(snap: _Snapshot) -> Finding | None:
    hogs = [
        r
        for r in snap.rows
        if r["third_party"]
        and r["oom_group"] in PINNED_GROUPS
        and (r["physical_estimate_mib"] or r["pss_mib"] or 0) >= RESIDENT_HOG_MIB
    ]
    if not hogs:
        return None
    described = []
    for r in hogs[:5]:
        text = f"{r['process']} {r['pss_mib']:.0f} MiB PSS"
        if r["resident_pss_mib"] is not None:
            text += (
                f" ({r['resident_pss_mib']:.0f} resident + "
                f"{r['swap_pss_mib']:.0f} swapped, about "
                f"{r['physical_estimate_mib']:.0f} physical)"
            )
        described.append(f"{text} in {r['oom_group']}")
    by_name = {p.name: p for p in snap.info.procs}
    cited = [by_name[r["process"]] for r in hogs[:3] if r["process"] in by_name]
    return Finding(
        id="memory_snapshot.resident_third_party",
        title="Third-party apps hold large amounts of RAM at high importance",
        symptom="slowness",
        severity="low",
        basis="measured",
        window="snapshot",
        summary=(
            f"At capture, {len(hogs)} third-party "
            f"{'process costs' if len(hogs) == 1 else 'processes cost'} over "
            f"{RESIDENT_HOG_MIB:.0f} MiB each in groups lmkd kills last: "
            + "; ".join(described)
            + ". PSS changes by hundreds of MiB within minutes, so this is one moment."
        ),
        metrics={"processes": len(hogs)},
        evidence=[p.detail or snap.text.evidence(p.index) for p in cited],
        recommendation=(
            "Check whether each app needs to run all the time (a foreground service, "
            "a bound accessibility or text-to-speech service, a second launcher). "
            "Switch to a lighter alternative or uninstall apps that are not needed."
        ),
        followups=[
            (
                "Run `adb_ro.py --save meminfo_app --workdir WORKDIR -- dumpsys "
                "meminfo PACKAGE` and read TOTAL PSS and TOTAL SWAP PSS in "
                "WORKDIR/live/meminfo_app.txt: resident versus swapped memory now"
            ),
            (
                "Run `adb_ro.py --save procstats_day --workdir WORKDIR -- dumpsys "
                "procstats --hours 24 PACKAGE` and read "
                "WORKDIR/live/procstats_day.txt: how much of the day it ran"
            ),
        ],
    )


def _cached_finding(snap: _Snapshot) -> Finding | None:
    limit = snap.limit
    threshold = max(round(limit * CACHED_LOW_SHARE), 1) if limit else CACHED_LOW_DEFAULT
    count = snap.info.groups.get("Cached", [0, 0])[1]
    if not snap.info.groups or count >= threshold:
        return None
    against = f", against a cached-process limit of {limit}" if limit else ""
    return Finding(
        id="memory_snapshot.few_cached_processes",
        title="Almost no apps are kept cached in memory",
        symptom="slowness",
        severity="low",
        basis="measured",
        window="snapshot",
        summary=(
            f"Only {count} cached processes ({snap.metrics['cached_group_pss_mib']} "
            f"MiB) were in memory at capture{against}. Switching back to an app "
            "usually means a cold start. A snapshot taken right after a kill burst "
            "looks the same, so compare with exit_info_audit."
        ),
        metrics={"cached_processes": count, "limit": limit},
        recommendation=(
            "Reduce the memory held by always-running apps "
            "(see memory_snapshot.resident_third_party)."
        ),
        followups=["exit_info_audit: the low-memory kill rate"],
    )


def _swap_finding(snap: _Snapshot) -> Finding | None:
    total, free = snap.swap_total, snap.swap_free
    if not total or free is None or _PCT * free / total >= SWAP_FREE_LOW_PCT:
        return None
    return Finding(
        id="memory_snapshot.swap_nearly_full",
        title="Swap is nearly full",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=(
            f"Only {free / _MIB:.0f} of {total / _MIB:.0f} MiB swap was free; the "
            "phone can no longer compress idle memory and has to kill apps."
        ),
        metrics={"swap_free_mib": _mib(free), "swap_total_mib": _mib(total)},
        recommendation="Reduce always-running apps; restart the phone if it persists.",
        followups=["vmstat_reclaim_io: swap-in and swap-out since boot"],
    )


def _status_finding(snap: _Snapshot) -> Finding | None:
    status = snap.info.summary.get("status")
    if not status or status == "normal":
        return None
    return Finding(
        id="memory_snapshot.memory_status",
        title=f"The memory status was '{status}' at capture",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=f"dumpsys meminfo reported memory status '{status}', not normal.",
        metrics={"status": status},
        recommendation="Close or restrict memory-heavy apps and collect again.",
        followups=["exit_info_audit and lmkd_kills for the kill rate"],
    )


@analyzer(
    "memory_snapshot", requires=("meminfo",), after=("windows", "am_memory_config")
)
def memory_snapshot(ctx: Context) -> Result:
    """Summarise what holds RAM at collection time."""
    text = ctx.sources.get("meminfo")
    if text is None:
        msg = "no dumpsys meminfo"
        raise SkipError(msg)
    info = _parse_meminfo(text)
    if not info.procs and "total_ram_kib" not in info.summary:
        msg = "dumpsys meminfo has no PSS table or RAM summary"
        raise SkipError(msg)
    result = Result("memory_snapshot", window="snapshot")
    if info.skipped:
        result.notes.append(f"{info.skipped} meminfo table lines could not be parsed.")
    details = _add_meminfo_detail(ctx.sources.get("meminfo_detail"), info)
    proc_mem = _proc_meminfo(ctx)
    swap = _swap_state(info.summary, proc_mem)
    result.metrics = _snapshot_metrics(info, proc_mem, swap)
    config = ctx.results.get("am_memory_config")
    limit = config.metrics.get("cur_max_cached_processes") if config else None
    result.metrics["cached_process_limit"] = limit
    result.metrics["per_process_detail"] = details
    ratio = result.metrics["zram_compression_ratio"]
    third = _third_party(ctx)
    rows = [_snapshot_row(p, third, ratio) for p in info.procs]
    groups: list[Row] = [
        {"group": g, "pss_mib": _mib(v[0]), "processes": v[1]}
        for g, v in sorted(info.groups.items(), key=lambda kv: -kv[1][0])
    ]
    result.add_table("top_pss", rows)
    result.add_table("oom_groups", groups)
    if details:
        result.notes.append(
            "For processes in the per-process meminfo (the bugreport, which may "
            "be minutes apart from the summary), PSS, SwapPss and RSS come from "
            "that dump and resident PSS = TOTAL PSS minus SwapPss; the order "
            "follows the summary. The physical estimate adds SwapPss divided by "
            "the zram compression ratio.",
        )
    else:
        result.notes.append(
            "No per-process meminfo: PSS includes swapped-out pages (SwapPss), so "
            "resident memory is overstated for processes with much swap.",
        )
    snap = _Snapshot(text, info, rows, swap[0], swap[1], limit, result.metrics)
    findings = (
        _hog_finding(snap),
        _cached_finding(snap),
        _swap_finding(snap),
        _status_finding(snap),
    )
    result.findings = [f for f in findings if f is not None]
    return result


# --- vmstat --------------------------------------------------------------------

_VMSTAT_RE = re.compile(r"^([a-z_0-9]+) (\d+)$")
# Memory-management threads; per-node threads (kswapd0, kswapd-1:0) are summed.
_MEMORY_THREAD_RE = re.compile(r"^(kswapd|kcompactd|oom_reaper|lmkd)(?:[-\d].*)?$")
_PAGES_PER_GIB = _GIB_KIB / PAGE_KIB


def _uptime_s(ctx: Context) -> float | None:
    """Return seconds since boot at capture, from the windows or meminfo."""
    w = ctx.windows
    if w.boot_time and w.dump_time:
        return (w.dump_time - w.boot_time).total_seconds()
    text = ctx.sources.get("meminfo")
    for line in text.lines[:5] if text is not None else []:
        if m := _UPTIME_RE.search(line):
            return int(m[2]) / 1000
    return None


def _after_boot_note(uptime_s: float, consequence: str) -> str:
    return (
        f"Captured {uptime_s / 60:.0f} min after boot, when start-up work "
        f"dominates: {consequence}."
    )


def _memory_thread_cpu(ctx: Context) -> dict[str, int]:
    """Return CPU seconds since start of kswapd, kcompactd, oom_reaper and lmkd."""
    rows = load_ps(ctx)
    names = {r.name for r in rows if _MEMORY_THREAD_RE.match(r.name.strip("[]"))}
    cpu: dict[str, float] = defaultdict(float)
    for name, secs in ps_cpu_by_name(rows, names).items():
        m = _MEMORY_THREAD_RE.match(name.strip("[]"))
        if m:
            cpu[m[1]] += secs
    return {name: round(secs) for name, secs in cpu.items()}


def _vmstat_metrics(c: dict[str, int], uptime: float | None) -> Row:
    """Return the counters; rates only when ``uptime`` is long enough."""
    refault = c.get("workingset_refault") or (
        c.get("workingset_refault_anon", 0) + c.get("workingset_refault_file", 0)
    )
    allocstall = sum(v for k, v in c.items() if k.startswith("allocstall"))
    stall, fail = c.get("compact_stall"), c.get("compact_fail")
    steal_k, steal_d = c.get("pgsteal_kswapd", 0), c.get("pgsteal_direct", 0)
    pgpgin, pswpout = c.get("pgpgin"), c.get("pswpout")

    span = uptime if uptime and uptime >= MIN_RATE_HOURS * 3600 else None

    def per_s(value: float | None) -> float | None:
        return round(value / span, 1) if value is not None and span else None

    return {
        "uptime_h": round(uptime / 3600, 2) if uptime else None,
        "workingset_refault_pages": refault,
        "refault_gib": round(refault / _PAGES_PER_GIB, 1),
        "refault_pages_per_s": per_s(refault),
        "pgmajfault": c.get("pgmajfault"),
        "pgmajfault_per_s": per_s(c.get("pgmajfault")),
        "pgpgin_gib": round(pgpgin / _GIB_KIB, 1) if pgpgin is not None else None,
        "pgpgin_mib_per_s": per_s(pgpgin / _MIB) if pgpgin is not None else None,
        "pswpin_pages": c.get("pswpin"),
        "pswpout_pages": pswpout,
        "swap_out_gib": round(pswpout / _PAGES_PER_GIB, 1)
        if pswpout is not None
        else None,
        "allocstall": allocstall,
        "allocstall_per_day": round(allocstall / span * 86400) if span else None,
        "compact_stall": stall,
        "compact_fail": fail,
        "compact_success": c.get("compact_success"),
        "compact_fail_pct": round(_PCT * fail / stall, 1)
        if stall and fail is not None
        else None,
        "pgsteal_kswapd": steal_k,
        "pgsteal_direct": steal_d,
        "direct_reclaim_share_pct": (
            round(_PCT * steal_d / (steal_k + steal_d), 1)
            if steal_k + steal_d
            else None
        ),
        "pgmigrate_success": c.get("pgmigrate_success"),
        "oom_kill": c.get("oom_kill"),
    }


def _cite(text: Text, index: dict[str, int], *keys: str) -> list[Evidence]:
    return [text.evidence(index[k]) for k in keys if k in index]


def _thrashing_finding(m: Row, text: Text, index: dict[str, int]) -> Finding | None:
    refault, majflt = m["refault_pages_per_s"], m["pgmajfault_per_s"]
    if (refault or 0) <= REFAULT_PAGES_PER_S and (majflt or 0) <= MAJFAULT_PER_S:
        return None
    return Finding(
        id="vmstat_reclaim_io.page_cache_thrashing",
        title="The kernel keeps re-reading evicted memory from storage",
        symptom="both",
        severity="medium",
        basis="measured",
        window="since_boot",
        summary=(
            f"Since boot ({m['uptime_h']} h): {m['refault_gib']} GiB refaulted "
            f"({refault} pages/s), {m['pgmajfault']} major faults ({majflt}/s), "
            f"{m['pgpgin_gib']} GiB read from storage and {m['swap_out_gib']} GiB "
            "swapped out: pages are evicted and read back over and over. Whether "
            "this causes the stutter the user sees is not shown; there is no "
            "per-frame fault data."
        ),
        metrics={
            "refault_pages_per_s": refault,
            "pgmajfault_per_s": majflt,
            "pgpgin_gib": m["pgpgin_gib"],
        },
        evidence=_cite(text, index, "workingset_refault", "pgmajfault", "pgpgin"),
        recommendation=(
            "Reduce the number of always-running apps so that their code and data "
            "stay in memory; uninstall apps that are not used."
        ),
        followups=[
            (
                "At the end of a battery period, run `adb_ro.py --save "
                "vmstat_later --workdir WORKDIR -- cat /proc/vmstat` and subtract "
                "this capture's counters from WORKDIR/live/vmstat_later.txt: the "
                "difference happened on battery"
            ),
            "storage_io_per_uid: which apps read the most",
        ],
    )


def _allocstall_finding(m: Row, text: Text, index: dict[str, int]) -> Finding | None:
    if (m["allocstall_per_day"] or 0) <= ALLOCSTALL_PER_DAY:
        return None
    return Finding(
        id="vmstat_reclaim_io.direct_reclaim",
        title="Apps stall waiting for the kernel to free memory",
        symptom="slowness",
        severity="low",
        basis="measured",
        window="since_boot",
        summary=(
            f"{m['allocstall']} direct-reclaim stalls since boot (about "
            f"{m['allocstall_per_day']} a day): allocations had to wait while the "
            "kernel freed memory."
        ),
        metrics={"allocstall_per_day": m["allocstall_per_day"]},
        evidence=_cite(text, index, "allocstall_normal", "allocstall_movable"),
        recommendation="Reduce memory pressure (fewer always-running apps).",
        followups=["psi_pressure: memory stall time since boot"],
    )


def _compaction_finding(m: Row, text: Text, index: dict[str, int]) -> Finding | None:
    if (m["compact_stall"] or 0) < COMPACT_STALL_MIN or (
        m["compact_fail_pct"] or 0
    ) <= COMPACT_FAIL_PCT:
        return None
    return Finding(
        id="vmstat_reclaim_io.compaction_failures",
        title="Memory compaction mostly fails",
        symptom="slowness",
        severity="low",
        basis="measured",
        window="since_boot",
        summary=(
            f"{m['compact_fail']} of {m['compact_stall']} direct compaction "
            f"stalls failed ({m['compact_fail_pct']}%): memory is fragmented."
        ),
        metrics={"compact_fail_pct": m["compact_fail_pct"]},
        evidence=_cite(text, index, "compact_stall", "compact_fail"),
        recommendation="A restart defragments memory; reduce memory pressure.",
        followups=["zone_watermarks_offline: free memory per zone"],
    )


@analyzer("vmstat_reclaim_io", requires=("proc_vmstat",))
def vmstat_reclaim_io(ctx: Context) -> Result:
    """Summarise reclaim, refault, swap and compaction counters since boot."""
    text = ctx.sources.get("proc_vmstat")
    if text is None:
        msg = "no /proc/vmstat"
        raise SkipError(msg)
    counters: dict[str, int] = {}
    index: dict[str, int] = {}
    for i, line in enumerate(text.lines):
        if m := _VMSTAT_RE.match(line.strip()):
            counters[m[1]], index[m[1]] = int(m[2]), i
    if not counters:
        msg = "/proc/vmstat has no counters"
        raise SkipError(msg)
    result = Result("vmstat_reclaim_io", window="since_boot")
    uptime = _uptime_s(ctx)
    if uptime is None:
        result.notes.append("Uptime unknown: no per-second rates.")
    elif uptime < MIN_RATE_HOURS * 3600:
        result.notes.append(
            _after_boot_note(
                uptime,
                "boot reads every library from storage, so the counters are "
                "given without rates and are not judged as thrashing",
            ),
        )
    result.metrics = _vmstat_metrics(counters, uptime)
    for name, secs in sorted(_memory_thread_cpu(ctx).items()):
        result.metrics[f"{name}_cpu_s_since_start"] = secs
    result.notes.append(
        "Since-boot counters include time on the charger; they do not show how "
        "much happened on battery. pgpgin is in KiB, pswpin/pswpout in 4 KiB pages.",
    )
    findings = (
        _thrashing_finding(result.metrics, text, index),
        _allocstall_finding(result.metrics, text, index),
        _compaction_finding(result.metrics, text, index),
    )
    result.findings = [f for f in findings if f is not None]
    return result


# --- PSI -------------------------------------------------------------------------

_PSI_RE = re.compile(
    r"^(some|full) avg10=([\d.,]+) avg60=([\d.,]+) avg300=([\d.,]+) total=(\d+)",
)
_PSI_LIVE_HEADER_RE = re.compile(r"^== (cpu|memory|io)\s*$")
_PSI_RESOURCES = ("cpu", "memory", "io")


def _psi_lines(ctx: Context) -> dict[str, list[tuple[Text, int]]]:
    """Return ``{resource: [(text, line index)]}``, preferring the live dump."""
    found: dict[str, list[tuple[Text, int]]] = defaultdict(list)
    live = ctx.sources.get("proc_pressure")
    current = ""
    for i, line in enumerate(live.lines if live is not None else []):
        if m := _PSI_LIVE_HEADER_RE.match(line.strip()):
            current = m[1]
        elif current and live is not None:
            found[current].append((live, i))
    for resource in _PSI_RESOURCES:
        text = ctx.sources.get(f"psi_{resource}")
        if resource not in found and text is not None:
            found[resource] = [(text, i) for i in range(len(text.lines))]
    return found


def _memory_stall_finding(m: Row, cites: dict[str, Evidence]) -> Finding | None:
    some = m.get("memory_some_avg10_pct") or 0
    full = m.get("memory_full_avg10_pct") or 0
    share = m.get("memory_some_share_of_uptime_pct") or 0
    chronic = share > PSI_MEMORY_SOME_SHARE_PCT
    if (
        not chronic
        and some <= PSI_MEMORY_SOME_AVG10_PCT
        and full <= PSI_MEMORY_FULL_AVG10_PCT
    ):
        return None
    return Finding(
        id="psi_pressure.memory_stall",
        title="Tasks spend noticeable time waiting for memory",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="since_boot" if chronic else "snapshot",
        summary=(
            f"Memory some-stall {m.get('memory_some_total_s')} s since boot "
            f"({share}% of uptime); at capture, avg10 some {some}% and full {full}%."
        ),
        metrics={"share_pct": share, "some_avg10_pct": some},
        evidence=[cites[k] for k in ("memory_some", "memory_full") if k in cites],
        recommendation="Reduce memory pressure: fewer always-running apps.",
        followups=["vmstat_reclaim_io and lmkd_kills"],
    )


def _io_stall_finding(m: Row, cites: dict[str, Evidence]) -> Finding | None:
    full = m.get("io_full_avg10_pct") or 0
    if full <= PSI_IO_FULL_AVG10_PCT:
        return None
    return Finding(
        id="psi_pressure.io_stall",
        title="All tasks were blocked on storage at capture",
        symptom="slowness",
        severity="low",
        basis="measured",
        window="snapshot",
        summary=f"I/O full-stall avg10 was {full}% at capture.",
        metrics={"io_full_avg10_pct": full},
        evidence=[cites["io_full"]] if "io_full" in cites else [],
        recommendation="Check for heavy background I/O (updates, sync, backups).",
        followups=["vmstat_reclaim_io: refaults and reads from storage"],
    )


def _cpu_stall_finding(m: Row, cites: dict[str, Evidence]) -> Finding | None:
    share = m.get("cpu_some_share_of_uptime_pct") or 0
    if share <= PSI_CPU_SOME_SHARE_PCT:
        return None
    return Finding(
        id="psi_pressure.cpu_contention",
        title="Runnable tasks often wait for a CPU",
        symptom="slowness",
        severity="low",
        basis="measured",
        window="since_boot",
        summary=(
            f"CPU some-stall was {m['cpu_some_total_s']} s since boot "
            f"({share}% of uptime)."
        ),
        metrics={"share_pct": share},
        evidence=[cites["cpu_some"]] if "cpu_some" in cites else [],
        recommendation="Find the busiest processes (CPU analyzers) and restrict them.",
        followups=["cpu analyzers: per-process CPU time"],
    )


@analyzer("psi_pressure", after=("windows", "lmkd_kills"))
def psi_pressure(ctx: Context) -> Result:
    """Report pressure stall information for CPU, memory and I/O."""
    result = Result("psi_pressure", window="since_boot")
    uptime = _uptime_s(ctx)
    if uptime is not None and uptime < MIN_RATE_HOURS * 3600:
        result.notes.append(
            _after_boot_note(
                uptime,
                "stall totals are given without shares of uptime, which would "
                "measure boot rather than chronic stalls",
            ),
        )
        uptime = None
    cites: dict[str, Evidence] = {}
    for resource, lines in _psi_lines(ctx).items():
        for text, i in lines:
            m = _PSI_RE.match(text.lines[i].strip())
            if m is None:
                continue
            key = f"{resource}_{m[1]}"
            total_s = int(m[5]) / 1e6
            result.metrics.update(
                {
                    f"{key}_avg10_pct": parse_decimal(m[2]),
                    f"{key}_avg60_pct": parse_decimal(m[3]),
                    f"{key}_avg300_pct": parse_decimal(m[4]),
                    f"{key}_total_s": round(total_s, 1),
                    f"{key}_share_of_uptime_pct": (
                        round(_PCT * total_s / uptime, 2) if uptime else None
                    ),
                },
            )
            cites[key] = text.evidence(i)
    if not cites:
        msg = "no PSI data (/proc/pressure or the bugreport PSI sections)"
        raise SkipError(msg)
    lmkd = ctx.results.get("lmkd_kills")
    at_kill = lmkd.metrics if lmkd is not None and lmkd.status == "ok" else {}
    for resource in _PSI_RESOURCES:
        value = at_kill.get(f"psi_{resource}_some_avg10_at_kill_max_pct")
        if value is not None:
            result.metrics[f"{resource}_some_avg10_at_kill_max_pct"] = value
    result.notes.append(
        "avg10/avg60/avg300 describe the moment of capture (often charging, right "
        "after collection started); totals cover the whole uptime.",
    )
    findings = (
        _memory_stall_finding(result.metrics, cites),
        _io_stall_finding(result.metrics, cites),
        _cpu_stall_finding(result.metrics, cites),
    )
    result.findings = [f for f in findings if f is not None]
    return result


# --- Zones and memory hotplug ----------------------------------------------------

_ZONE_RE = re.compile(r"^Node (\d+), zone\s+(\w+)")
_ZONE_FIELD_RE = re.compile(
    r"^\s+(pages free|min|low|high|spanned|present|managed|nr_free_cma)\s+(\d+)\s*$",
)
_PROTECTION_RE = re.compile(r"^\s+protection: \((.*)\)")
_KERNEL_TS_RE = re.compile(r"^(?:<\d+>)?\[\s*(\d+\.\d+)\]")
_MEM_OFFLINE_RE = re.compile(r"mem-offline: (\w+) memory block (\S+)")
_ZONELISTS_RE = re.compile(r"Built (\d+) zonelists.*Total pages: (\d+)")
_OOM_REAPER_RE = re.compile(r"oom_reaper: reaped process (\d+) \(")


@dataclass
class _Zone:
    """One /proc/zoneinfo zone.

    ``protection`` is the zone's lowmem_reserve, indexed by the zone an
    allocation prefers (its classzone). An allocation that prefers this zone
    itself uses entry ``position`` (normally 0); the larger entries apply only
    to allocations that fall back here from a higher zone (Linux
    ``__zone_watermark_ok``).
    """

    node: int
    name: str
    index: int  # line index of the zone header
    position: int  # zone index within the node, empty zones included
    values: dict[str, int] = field(default_factory=dict)
    protection: list[int] = field(default_factory=list)

    def kib(self, key: str) -> int:
        return self.values.get(key, 0) * PAGE_KIB

    @property
    def free_noncma_kib(self) -> int:
        return self.kib("pages free") - self.kib("nr_free_cma")

    @property
    def min_kib(self) -> int:
        """The min watermark for allocations that prefer this zone."""
        own = self.protection[self.position : self.position + 1] or [0]
        return self.kib("min") + own[0] * PAGE_KIB

    @property
    def max_protection_kib(self) -> int:
        return max(self.protection, default=0) * PAGE_KIB

    @property
    def reserve_kib(self) -> int:
        """The min watermark for fallback allocations from the highest zone."""
        return self.kib("min") + self.max_protection_kib


def _parse_zoneinfo(text: Text) -> list[_Zone]:
    zones: list[_Zone] = []
    for i, line in enumerate(text.lines):
        if m := _ZONE_RE.match(line):
            node = int(m[1])
            position = sum(1 for z in zones if z.node == node)
            zones.append(_Zone(node, m[2], i, position))
        elif zones and (m := _ZONE_FIELD_RE.match(line)):
            zones[-1].values.setdefault(m[1], int(m[2]))
        elif zones and (m := _PROTECTION_RE.match(line)):
            zones[-1].protection = [int(v) for v in re.findall(r"\d+", m[1])]
    return [z for z in zones if z.values.get("managed") or z.values.get("present")]


def _zone_row(z: _Zone) -> Row:
    return {
        "zone": f"{z.node}:{z.name}",
        "free_mib": _mib(z.kib("pages free")),
        "free_cma_mib": _mib(z.kib("nr_free_cma")),
        "free_noncma_mib": _mib(z.free_noncma_kib),
        "min_mib": _mib(z.kib("min")),
        "low_mib": _mib(z.kib("low")),
        "high_mib": _mib(z.kib("high")),
        "protection_max_mib": _mib(z.max_protection_kib),
        "managed_mib": _mib(z.kib("managed")),
        "below_min": z.free_noncma_kib < z.min_kib,
        "below_min_plus_reserve": z.free_noncma_kib < z.reserve_kib,
    }


@dataclass
class _KernelEvent:
    kernel_s: float
    kind: str
    evidence: Evidence


def _kernel_anchors(ctx: Context, dmesg: Text) -> list[tuple[float, datetime]]:
    """Pair oom_reaper PIDs in dmesg with lmkd kills in logcat (kernel s, wall)."""
    kill_times: dict[int, datetime] = {}
    for k in _lmkd_records(ctx).all:
        kill_times.setdefault(k.pid, k.ts)
    anchors = []
    for line in dmesg.lines:
        if "oom_reaper" not in line:
            continue
        m, t = _OOM_REAPER_RE.search(line), _KERNEL_TS_RE.match(line)
        if m and t and int(m[1]) in kill_times:
            anchors.append((float(t[1]), kill_times[int(m[1])]))
    return sorted(anchors)


def _wall_time(
    kernel_s: float, anchors: list[tuple[float, datetime]]
) -> datetime | None:
    if not anchors:
        return None
    k, wall = min(anchors, key=lambda a: abs(a[0] - kernel_s))
    if abs(k - kernel_s) > ANCHOR_MAX_DISTANCE_S:
        return None
    return wall + timedelta(seconds=kernel_s - k)


def _hotplug_events(ctx: Context, result: Result) -> list[_KernelEvent]:
    """Find memory blocks taken offline or brought online in the kernel log."""
    dmesg = ctx.sources.get("dmesg")
    if dmesg is None:
        result.notes.append("No kernel log: memory hotplug events unknown.")
        return []
    found: list[_KernelEvent] = []
    zonelists = 0
    for i, line in enumerate(dmesg.lines):
        if "mem-offline" not in line and "zonelists" not in line:
            continue
        t = _KERNEL_TS_RE.match(line)
        if m := _MEM_OFFLINE_RE.search(line):
            kernel_s = float(t[1]) if t else -1.0
            found.append(_KernelEvent(kernel_s, m[1].lower(), dmesg.evidence(i)))
        elif _ZONELISTS_RE.search(line):
            zonelists += 1
    anchors = _kernel_anchors(ctx, dmesg) if found else []
    kinds = Counter(e.kind for e in found)
    first = _wall_time(found[0].kernel_s, anchors) if found else None
    result.metrics.update(
        {
            "mem_offline_events": len(found),
            "mem_onlined_blocks": kinds.get("onlined", 0),
            "mem_offlined_blocks": kinds.get("offlined", 0),
            "zonelist_rebuilds": zonelists,
            "first_hotplug_kernel_s": found[0].kernel_s if found else None,
            "first_hotplug_wall_time": _fmt(first),
            "kernel_time_anchors": len(anchors),
        },
    )
    if found and first is None:
        result.notes.append(
            "Hotplug times are kernel seconds only: no oom_reaper/lmkd PID pair is "
            "close enough to map them to wall time.",
        )
    rows: list[Row] = [
        {
            "kernel_s": e.kernel_s,
            "event": e.kind,
            "wall_time": _fmt(_wall_time(e.kernel_s, anchors)),
        }
        for e in found
    ]
    result.add_table("hotplug_events", rows)
    return found


def _zone_finding(
    text: Text, zones: list[_Zone], mem_free: int | None
) -> Finding | None:
    breached = [
        z
        for z in zones
        if z.free_noncma_kib < z.min_kib and z.kib("managed") >= SMALL_ZONE_KIB
    ]
    if not breached:
        return None
    z = breached[0]
    lots_free = mem_free is not None and mem_free > KILL_FREE_MEMORY_KIB
    free_text = f", while MemFree was {mem_free / _MIB:.0f} MiB" if mem_free else ""
    return Finding(
        id="zone_watermarks_offline.zone_below_watermark",
        title=f"The {z.name} memory zone is below its minimum watermark",
        symptom="slowness",
        severity="medium" if lots_free else "low",
        basis="measured",
        window="snapshot",
        summary=(
            f"At capture the {z.name} zone had {z.free_noncma_kib / _MIB:.0f} MiB "
            f"free outside CMA, below its min watermark "
            f"({z.min_kib / _MIB:.0f} MiB){free_text}. Allocations that cannot "
            "use CMA or another zone wait for the kernel to reclaim memory in "
            "this zone. Whether lmkd judges this zone on its own is not shown "
            "(stock lmkd sums all zones; see the lmkd_min_watermark metrics)."
        ),
        metrics={
            "free_noncma_mib": _mib(z.free_noncma_kib),
            "min_mib": _mib(z.min_kib),
            "mem_free_mib": _mib(mem_free),
        },
        evidence=[text.evidence(z.index)],
        recommendation=(
            "Report kills with plenty of free memory together with this zone state "
            "to the phone maker; it is kernel or lmkd tuning that users cannot "
            "change without root."
        ),
        followups=[
            "lmkd_kills: MemFree at each kill",
            (
                "After 5+ minutes of screen-off, run `adb_ro.py --save "
                "zoneinfo_idle --workdir WORKDIR -- cat /proc/zoneinfo` and "
                "compare the zones in WORKDIR/live/zoneinfo_idle.txt with this "
                "capture"
            ),
        ],
    )


def _hotplug_finding(
    m: Row, zones: list[_Zone], hotplug: list[_KernelEvent]
) -> Finding | None:
    managed = sum(z.kib("managed") for z in zones)
    movable = sum(z.kib("managed") for z in zones if z.name == "Movable")
    big_movable = bool(managed) and movable / managed >= HOTPLUG_ZONE_SHARE
    if not hotplug and not big_movable:
        return None
    parts = []
    if hotplug:
        when = m.get("first_hotplug_wall_time")
        parts.append(
            f"The kernel log shows {m['mem_onlined_blocks']} 'Onlined' and "
            f"{m['mem_offlined_blocks']} 'Offlined' memory-block messages"
            + (f" (first around {when})" if when else "")
            + ".",
        )
    if big_movable:
        parts.append(
            f"A Movable zone holds {movable / _GIB_KIB:.1f} GiB "
            f"({m['movable_zone_share_pct']}% of RAM).",
        )
    parts.append(
        "Some phones take a block of RAM offline to save power while idle; the "
        "phone then runs with less memory until it comes back. Offline timing is "
        "shown only if the kernel log covers it.",
    )
    return Finding(
        id="zone_watermarks_offline.memory_hotplug",
        title="Part of the RAM can be taken offline",
        symptom="both",
        severity="low",
        basis="measured" if hotplug else "inferred",
        window="snapshot",
        summary=" ".join(parts),
        metrics={
            "onlined": m.get("mem_onlined_blocks"),
            "offlined": m.get("mem_offlined_blocks"),
            "movable_share_pct": m.get("movable_zone_share_pct"),
        },
        evidence=[e.evidence for e in hotplug[:3]],
        recommendation=(
            "Nothing to change in settings. Include this with any report of "
            "low-memory kills to the phone maker."
        ),
        followups=[
            (
                "A bugreport taken after 5+ minutes of screen-off shows whether "
                "'Offlined memory block' messages follow screen-off or Doze"
            ),
        ],
    )


@analyzer("zone_watermarks_offline", requires=("proc_zoneinfo",))
def zone_watermarks_offline(ctx: Context) -> Result:
    """Check per-zone free memory against watermarks; find memory hotplug."""
    text = ctx.sources.get("proc_zoneinfo")
    if text is None:
        msg = "no /proc/zoneinfo"
        raise SkipError(msg)
    zones = _parse_zoneinfo(text)
    if not zones:
        msg = "/proc/zoneinfo has no zones"
        raise SkipError(msg)
    result = Result("zone_watermarks_offline", window="snapshot")
    result.notes.append(
        "Zone pages are assumed to be 4 KiB. below_min compares a zone with the "
        "watermark of allocations that prefer it; below_min_plus_reserve adds "
        "its largest lowmem reserve, which only refuses allocations falling "
        "back from a higher zone.",
    )
    rows = [_zone_row(z) for z in zones]
    result.add_table("zones", rows)
    meminfo = _proc_meminfo(ctx)
    mem_free = meminfo.get("MemFree")
    managed = sum(z.kib("managed") for z in zones)
    movable = sum(z.kib("managed") for z in zones if z.name == "Movable")
    # Stock lmkd's "min watermark is breached": MemFree minus CmaFree below
    # the sum of min + max protection over present zones (lmkd.cpp
    # calc_zone_watermarks and get_lowest_watermark).
    lmkd_min = sum(z.reserve_kib for z in zones if z.values.get("present"))
    free_noncma = mem_free - meminfo.get("CmaFree", 0) if mem_free is not None else None
    result.metrics = {
        "zones": len(zones),
        "zones_below_min": sum(1 for r in rows if r["below_min"]),
        "zones_below_min_plus_reserve": sum(
            1 for r in rows if r["below_min_plus_reserve"]
        ),
        "lmkd_min_watermark_mib": _mib(lmkd_min),
        "mem_free_noncma_mib": _mib(free_noncma),
        "lmkd_min_watermark_breached": (
            free_noncma < lmkd_min if free_noncma is not None else None
        ),
        "movable_zone_mib": _mib(movable) if movable else None,
        "movable_zone_share_pct": round(_PCT * movable / managed, 1)
        if movable
        else None,
        "mem_free_mib": _mib(mem_free),
    }
    hotplug = _hotplug_events(ctx, result)
    findings = (
        _zone_finding(text, zones, mem_free),
        _hotplug_finding(result.metrics, zones, hotplug),
    )
    result.findings = [f for f in findings if f is not None]
    return result


# --- Activity manager memory configuration -----------------------------------------

_AM_KEYS = {
    "use_freezer": "use_freezer",
    "use_compaction": "use_compaction",
    "freeze_binder_enabled": "freeze_binder_enabled",
    "max_cached_processes": "max_cached_processes",
    "mCustomizedMaxCachedProcesses": "customized_max_cached_processes",
    "CUR_MAX_CACHED_PROCESSES": "cur_max_cached_processes",
    "CUR_MAX_EMPTY_PROCESSES": "cur_max_empty_processes",
    "CUR_TRIM_EMPTY_PROCESSES": "cur_trim_empty_processes",
    "CUR_TRIM_CACHED_PROCESSES": "cur_trim_cached_processes",
    "power_check_interval": "power_check_interval_ms",
    "power_check_max_cpu_1": "power_check_max_cpu_1_pct",
    "power_check_max_cpu_2": "power_check_max_cpu_2_pct",
    "power_check_max_cpu_3": "power_check_max_cpu_3_pct",
    "power_check_max_cpu_4": "power_check_max_cpu_4_pct",
    "use_oom_re_ranking": "use_oom_re_ranking",
}
_AM_KV_RE = re.compile(r"^\s+(\w+)=(\S*)\s*$")
_APPS_FROZEN_RE = re.compile(r"^\s+Apps frozen: (\d+)")
_DEVICE_CONFIG_RE = re.compile(r"^(activity_manager(?:_native_boot)?)/(\w+)=(.*)$")
# Only memory-related device_config flags are kept in the metrics.
_MEMORY_FLAG_RE = re.compile(r"freez|compact|cached|empty|oom|lmk|swap|kill")
_GETPROP_RE = re.compile(r"^\[([\w.]+)\]: \[(.*)\]$")
_PROPERTY_RE = re.compile(r"lmk|use_freezer|prefetch")
_FREEZER_MIN_SDK = 31  # the cached-app freezer is on by default from Android 12


def _value(raw: str) -> bool | int | str:
    if raw in {"true", "false"}:
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        return raw


def _am_settings(text: Text, found: Row, cites: dict[str, Evidence]) -> None:
    """Read the activity manager constants and the CachedAppOptimizer block."""
    inside = False
    for i, line in enumerate(text.lines):
        if "activity_manager_constants:" in line:
            inside = True
        elif inside and line.startswith(("ACTIVITY MANAGER ", "DUMP OF SERVICE")):
            return
        elif inside and (m := _AM_KV_RE.match(line)):
            if (key := _AM_KEYS.get(m[1])) and key not in found:
                found[key] = _value(m[2])
                cites[key] = text.evidence(i)
        elif inside and (m := _APPS_FROZEN_RE.match(line)):
            found["apps_frozen"] = int(m[1])
            cites["apps_frozen"] = text.evidence(i)


def _device_config(ctx: Context, found: Row, cites: dict[str, Evidence]) -> None:
    """Read memory-related activity_manager flags from device_config."""
    entries: list[tuple[str, str, Text, int]] = []
    text = ctx.sources.get("device_config")
    for i, line in enumerate(text.lines if text is not None else []):
        if text is not None and (m := _DEVICE_CONFIG_RE.match(line.strip())):
            entries.append((f"{m[1]}_{m[2]}", m[3].strip(), text, i))
    live = ctx.sources.get("device_config_am")
    namespace = "activity_manager"
    for i, line in enumerate(live.lines if live is not None else []):
        stripped = line.strip()
        if stripped.startswith("==="):
            namespace = stripped.strip("= ") or namespace
        elif "=" in stripped and live is not None:
            key, _, value = stripped.partition("=")
            entries.append((f"{namespace}_{key.strip()}", value.strip(), live, i))
    for key, value, source, i in entries:
        if _MEMORY_FLAG_RE.search(key):
            found.setdefault(f"device_config_{key}", _value(value))
            cites.setdefault(f"device_config_{key}", source.evidence(i))


def _properties(ctx: Context, found: Row) -> None:
    """Read lmkd and freezer properties, the SDK level and the freezer setting."""
    text = ctx.sources.get("getprop")
    props = {}
    for line in text.lines if text is not None else []:
        if m := _GETPROP_RE.match(line.strip()):
            if m[1] == "ro.build.version.sdk":
                found["sdk"] = _value(m[2])
            elif _PROPERTY_RE.search(m[1]):
                props[m[1]] = m[2]
    found["properties"] = (
        "; ".join(f"{k}={v}" for k, v in sorted(props.items())) or None
    )
    br = ctx.sources.workdir.bugreport
    if "sdk" not in found and br is not None:
        sdk = br.header.get("android_sdk_version", "")
        found["sdk"] = int(sdk) if sdk.isdigit() else None
    settings = load_settings(ctx)
    freezer = settings.get("cached_apps_freezer") if settings else None
    if freezer is not None:
        found["cached_apps_freezer_setting"] = freezer[0]


def _freezer_finding(found: Row, cites: dict[str, Evidence]) -> Finding | None:
    use, frozen, sdk = (
        found.get("use_freezer"),
        found.get("apps_frozen"),
        found.get("sdk"),
    )
    if use is not False and not (frozen == 0 and use is not True):
        return None
    modern = isinstance(sdk, int) and sdk >= _FREEZER_MIN_SDK
    return Finding(
        id="am_memory_config.freezer_off",
        title="The cached-app freezer is off",
        symptom="both",
        severity="medium" if modern else "low",
        basis="measured",
        window="snapshot",
        summary=(
            f"use_freezer={use}, apps frozen: {frozen}. Android 12 and later "
            "normally freeze cached apps so they use no CPU; with the freezer off "
            "they can keep running code in the background until lmkd kills them."
        ),
        metrics={"use_freezer": use, "apps_frozen": frozen, "sdk": sdk},
        evidence=[cites[k] for k in ("use_freezer", "apps_frozen") if k in cites],
        recommendation=(
            "Developer options > 'Suspend execution for cached apps': set it to "
            "Enabled and restart the phone, then check that 'Apps frozen' in "
            "'dumpsys activity settings' is above 0. If it stays 0, the kernel "
            "does not support the freezer; report it to the phone maker."
        ),
        followups=[
            (
                "Run `adb_ro.py --save freezer_setting --workdir WORKDIR -- "
                "settings get global cached_apps_freezer` and read "
                "WORKDIR/live/freezer_setting.txt (disabled means switched off)"
            ),
            (
                "Run `adb_ro.py --save logcat_freezer --workdir WORKDIR -- "
                "logcat -d -b main,system` and grep WORKDIR/live/logcat_freezer.txt "
                "for 'freezer'; boot messages are there only if the log has not "
                "rotated since boot"
            ),
        ],
    )


def _compaction_off_finding(found: Row, cites: dict[str, Evidence]) -> Finding | None:
    if found.get("use_compaction") is not False:
        return None
    return Finding(
        id="am_memory_config.compaction_off",
        title="App memory compaction is off",
        symptom="info",
        severity="info",
        basis="measured",
        window="snapshot",
        summary=(
            "use_compaction=false: the activity manager does not compact the "
            "memory of cached apps into swap, so they take more RAM until killed."
        ),
        metrics={"use_compaction": False},
        evidence=[cites["use_compaction"]] if "use_compaction" in cites else [],
        recommendation="Nothing to change without root; context for the kill rate.",
        followups=[],
    )


@analyzer("am_memory_config")
def am_memory_config(ctx: Context) -> Result:
    """Report the cached-app freezer, compaction and cached-process limits."""
    found: Row = {}
    cites: dict[str, Evidence] = {}
    text = ctx.sources.get("activity_settings") or ctx.sources.get("activity")
    if text is not None:
        _am_settings(text, found, cites)
    _device_config(ctx, found, cites)
    if not found:
        msg = "no activity manager settings or device_config activity_manager flags"
        raise SkipError(msg)
    _properties(ctx, found)
    for flag in ("use_freezer", "use_compaction"):
        for ns in ("activity_manager_native_boot", "activity_manager"):
            key = f"device_config_{ns}_{flag}"
            if flag not in found and key in found:
                found[flag] = found[key]
                cites[flag] = cites[key]
    result = Result("am_memory_config", window="snapshot", metrics=found)
    if text is None:
        result.notes.append("No 'dumpsys activity settings': only device_config flags.")
    findings = (_freezer_finding(found, cites), _compaction_off_finding(found, cites))
    result.findings = [f for f in findings if f is not None]
    return result


# --- Process churn -----------------------------------------------------------------

# am_proc_start lists user, pid, uid, process, hosting type and hosting name;
# am_kill lists user, pid, process, adj, reason and rss.
_START_FIELDS = 4
_KILL_FIELDS = 3


@dataclass
class _Start:
    ts: datetime
    pid: int
    process: str
    hosting: str
    evidence: Evidence


@dataclass
class _ChurnKill:
    ts: datetime
    pid: int
    process: str


def _starts(events: EventLog) -> list[_Start]:
    """Parse ``am_proc_start`` payloads; the hosting name may contain commas."""
    found = []
    for line in events.by_tag("am_proc_start"):
        parts = _payload(line).split(",", 5)
        pid = _int_at(parts, 1)
        if pid is None or len(parts) < _START_FIELDS:
            continue
        hosting = parts[_START_FIELDS].strip() if len(parts) > _START_FIELDS else ""
        cite = _cite_event(events, line)
        found.append(_Start(line.ts, pid, parts[3], hosting, cite))
    return found


def _churn_kills(
    events: EventLog, ctx: Context, names: dict[int, str]
) -> list[_ChurnKill]:
    """Return activity-manager and lmkd kills, one per PID (a PID dies once)."""
    kills: dict[int, _ChurnKill] = {}
    for line in events.by_tag("am_kill"):
        parts = _fields(line)
        pid = _int_at(parts, 1)
        if pid is not None and len(parts) >= _KILL_FIELDS:
            kills.setdefault(pid, _ChurnKill(line.ts, pid, parts[2]))
    for k in _lmkd_records(ctx).all:
        name = k.name or names.get(k.pid, "")
        kills.setdefault(k.pid, _ChurnKill(k.ts, k.pid, name))
    return sorted(kills.values(), key=operator.attrgetter("ts"))


def _triggers(events: EventLog) -> list[tuple[datetime, str]]:
    """Return labelled events that release work: screen on, unlock, plug-in."""
    found = [(t.ts, "screen on") for t in events.screen_transitions() if t.on]
    labels = {"unlocked": "unlock", "charging": "charging"}
    for line in events.by_tag("device_idle_off_start"):
        reason = _payload(line).strip()
        found.append((line.ts, labels.get(reason, f"idle exit: {reason}")))
    found += [(t.ts, "plug-in") for t in events.power_transitions() if t.on]
    previous = None
    for line in events.by_tag("battery_saver_mode"):
        now = _int_at(_fields(line), _SAVER_FULL_NOW_FIELD)
        if now == 0 and previous == 1:
            found.append((line.ts, "battery saver off"))
        previous = now
    return sorted(found)


def _labels_near(triggers: list[tuple[datetime, str]], minute: datetime) -> str:
    labels: list[str] = []
    for ts, label in triggers:
        near = minute - TRIGGER_LOOKBACK <= ts < minute + timedelta(minutes=1)
        if near and label not in labels:
            labels.append(label)
    return ", ".join(labels)


@dataclass
class _Churn:
    starts: list[_Start]
    kills: list[_ChurnKill]
    triggers: list[tuple[datetime, str]]
    plug_in: datetime | None
    boot: datetime | None

    def booting(self, ts: datetime) -> bool:
        """Return whether ``ts`` falls in the start-up minutes after boot.

        The minute of the boot counts too: ``starts_per_minute`` rows start
        on the full minute.
        """
        b = self.boot
        return b is not None and _minute(b) <= ts < b + BOOT_SETTLE

    def in_flood(self, ts: datetime) -> bool:
        """Return whether ``ts`` falls in the two minutes after the plug-in."""
        p = self.plug_in
        return p is not None and p <= ts < p + 2 * PLUG_IN_FLOOD_WINDOW

    def settling(self, ts: datetime) -> bool:
        """Return whether ``ts`` falls in the work released by plug-in or boot."""
        return self.in_flood(ts) or self.booting(ts)

    def after_plug(self, items: Iterable[datetime]) -> int:
        p = self.plug_in
        return sum(1 for ts in items if p and p <= ts < p + PLUG_IN_FLOOD_WINDOW)


def _restart_row(
    name: str, starts: list[_Start], kills: list[datetime], churn: _Churn
) -> Row | None:
    """Describe one process's restarts; pairs after plug-in or boot are apart."""
    times = [s.ts for s in starts]
    rapid, _ = _max_in_window(times, RAPID_WINDOW)
    calm = [t for t in times if not churn.settling(t)]
    rapid_outside, _ = _max_in_window(calm, RAPID_WINDOW)
    pairs = []
    for kill in kills:
        j = bisect.bisect_right(times, kill)
        if j < len(times) and times[j] - kill <= RESTART_GAP:
            pairs.append((kill, (times[j] - kill).total_seconds()))
    if rapid < RAPID_STARTS and len(pairs) < RESTART_LOOP_MIN:
        return None
    outside = sum(1 for kill, _ in pairs if not churn.settling(kill))
    return {
        "process": name,
        "starts": len(starts),
        "kills": len(kills),
        "restarts_within_120s": len(pairs),
        "restarts_outside_plug_in_and_boot": outside,
        "min_restart_gap_s": round(min(g for _, g in pairs), 1) if pairs else None,
        "max_starts_in_60s": rapid,
        "loop_outside_plug_in_and_boot": (
            outside >= RESTART_LOOP_MIN or rapid_outside >= RAPID_STARTS
        ),
        "hosting": ", ".join(sorted({s.hosting or "''" for s in starts})),
        "first_start": _fmt(times[0]),
    }


def _restart_rows(churn: _Churn) -> tuple[list[Row], dict[str, _Start]]:
    """Return processes in kill-restart loops or rapid restarts, and first starts."""
    by_name: dict[str, list[_Start]] = defaultdict(list)
    for s in churn.starts:
        by_name[s.process].append(s)
    kills_by_name: dict[str, list[datetime]] = defaultdict(list)
    for k in churn.kills:
        kills_by_name[k.process].append(k.ts)
    rows = [
        row
        for name, starts in by_name.items()
        if (row := _restart_row(name, starts, kills_by_name.get(name, []), churn))
    ]
    rows.sort(
        key=lambda r: (
            not r["loop_outside_plug_in_and_boot"],
            -r["restarts_within_120s"],
            -r["max_starts_in_60s"],
            r["process"],
        ),
    )
    return rows, {name: starts[0] for name, starts in by_name.items()}


def _empty_hosting_bursts(starts: list[_Start]) -> list[list[_Start]]:
    """Group starts without a hosting reason that come within one second."""
    bursts: list[list[_Start]] = []
    current: list[_Start] = []
    for s in (s for s in starts if not s.hosting):
        if current and s.ts - current[0].ts > EMPTY_HOSTING_WINDOW:
            bursts.append(current)
            current = []
        current.append(s)
    bursts.append(current)
    return [b for b in bursts if len(b) >= EMPTY_HOSTING_BURST]


def _minute_rows(churn: _Churn) -> list[Row]:
    per_minute = Counter(_minute(s.ts) for s in churn.starts)
    kills = Counter(_minute(k.ts) for k in churn.kills)
    rows: list[Row] = [
        {
            "minute": _fmt(minute, "minutes"),
            "starts": n,
            "kills": kills.get(minute, 0),
            "after_plug_in": churn.in_flood(minute + timedelta(seconds=59)),
            "triggers": _labels_near(churn.triggers, minute),
        }
        for minute, n in sorted(per_minute.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return rows


def _burst_finding(rows: list[Row], churn: _Churn) -> Finding | None:
    """Report minutes with many starts, except after plug-in and boot."""
    bursts = [
        r
        for r in rows
        if r["starts"] > START_BURST_PER_MIN
        and not r["after_plug_in"]
        and not churn.booting(datetime.fromisoformat(r["minute"]))
    ]
    if not bursts:
        return None
    worst = bursts[0]
    near = f" (near: {worst['triggers']})" if worst["triggers"] else ""
    cited = [
        s for s in churn.starts if _fmt(_minute(s.ts), "minutes") == worst["minute"]
    ]
    return Finding(
        id="process_churn.start_burst",
        title="Bursts of process starts",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{len(bursts)} minutes had more than {START_BURST_PER_MIN} process "
            f"starts; the worst, {worst['minute']}, had {worst['starts']} starts "
            f"and {worst['kills']} kills{near}. Starting many processes at once "
            "competes with the app in use."
        ),
        metrics={"burst_minutes": len(bursts), "max_starts": worst["starts"]},
        evidence=[s.evidence for s in cited[:2]],
        recommendation=(
            "Find which apps start in the burst (table starts_per_minute and the "
            f"event log) and restrict their background activity ({_RESTRICT})."
        ),
        followups=["Check whether the bursts repeat at every unlock"],
    )


def _plug_flood_finding(m: Row) -> Finding | None:
    """Report the minute after plug-in; it owns the kill storm of that minute."""
    starts = m.get("starts_60s_after_plug_in") or 0
    kills = m.get("kills_60s_after_plug_in") or 0
    if starts <= START_BURST_PER_MIN and kills <= KILL_STORM_COUNT:
        return None
    exits = m.get("low_memory_exits_60s_after_plug_in")
    exit_text = f" ({exits} low-memory exits in exit-info)" if exits else ""
    return Finding(
        id="process_churn.plug_in_flood",
        title="Plugging in released a burst of deferred work",
        symptom="info",
        severity="info",
        basis="measured",
        window="log_coverage",
        summary=(
            f"In the minute after the plug-in at {m['plug_in_time']}: {starts} "
            f"process starts and {m['kills_60s_after_plug_in']} kills{exit_text}. "
            "Android runs jobs held back by Doze and Battery Saver when charging "
            "starts, so this is expected; if the phone was plugged in for this "
            "collection, it is an artefact of collecting."
        ),
        metrics={
            "starts": starts,
            "kills": m["kills_60s_after_plug_in"],
            "low_memory_exits": exits,
        },
        recommendation=(
            "Collect over wireless adb, or before plugging in, to see the phone as "
            "it is used on battery."
        ),
        followups=[],
    )


def _restart_finding(rows: list[Row], first: dict[str, _Start]) -> Finding | None:
    if not rows:
        return None
    loops = [r for r in rows if r["loop_outside_plug_in_and_boot"]]
    listed = "; ".join(
        f"{r['process']}: {r['starts']} starts, {r['kills']} kills, "
        f"{r['restarts_within_120s']} restarts within 120 s"
        + ("" if r["loop_outside_plug_in_and_boot"] else " (after plug-in or boot)")
        for r in rows[:3]
    )
    return Finding(
        id="process_churn.restart_loops",
        title="Processes are killed and started again in quick succession",
        symptom="both",
        severity="medium" if loops else "low",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{len(rows)} processes were started {RAPID_STARTS}+ times within a "
            f"minute or restarted within 120 s of a kill at least "
            f"{RESTART_LOOP_MIN} times ({len(loops)} outside the work released by "
            f"plug-in or boot): "
            f"{listed}. Each restart redoes the app's start-up work."
        ),
        metrics={
            "processes": len(rows),
            "kill_restart_loops_outside_plug_in_and_boot": len(loops),
        },
        evidence=[first[r["process"]].evidence for r in rows[:3]],
        recommendation=(
            "For an app that restarts right after being killed, check what wakes "
            "it (a broadcast receiver such as location updates, an alarm, a job) "
            "and turn that feature off or restrict the app."
        ),
        followups=["exit_info_audit: the kill reasons for these processes"],
    )


def _prelaunch_finding(bursts: list[list[_Start]]) -> Finding | None:
    if not bursts:
        return None
    b = bursts[0]
    return Finding(
        id="process_churn.prelaunch_burst",
        title="Several apps started at once without a component",
        symptom="slowness",
        severity="low",
        basis="inferred",
        window="log_coverage",
        summary=(
            f"{len(b)} processes started within one second at {_fmt(b[0].ts)} "
            "with no hosting type (no activity, service, broadcast or provider). "
            "This looks like an app-prelaunch or prefetch feature; the log does "
            f"not show its origin. Seen {len(bursts)} time(s) in the log."
        ),
        metrics={"bursts": len(bursts), "starts": len(b)},
        evidence=[s.evidence for s in b[:3]],
        recommendation=(
            "Watch whether this repeats at every Home press or unlock; if so, look "
            "for a vendor app-prelaunch setting."
        ),
        followups=["am_memory_config properties: prefetch or prelaunch flags"],
    )


@analyzer(
    "process_churn", requires=("logcat_events",), after=("windows", "exit_info_audit")
)
def process_churn(ctx: Context) -> Result:
    """Find bursts of process starts and kill-restart loops in the event log."""
    events = load_event_log(ctx)
    starts = _starts(events)
    if not starts:
        msg = "the event log has no am_proc_start lines"
        raise SkipError(msg)
    result = Result("process_churn", window="log_coverage")
    churn = _Churn(
        starts,
        _churn_kills(events, ctx, _pid_names(events)),
        _triggers(events),
        _plug_in_time(ctx, events),
        ctx.windows.boot_time,
    )
    minutes = _minute_rows(churn)
    restarts, first = _restart_rows(churn)
    empty = _empty_hosting_bursts(starts)
    hosting = Counter(s.hosting or "(none)" for s in starts)
    exit_result = ctx.results.get("exit_info_audit")
    first_ts, last_ts = events.span() or (None, None)
    span = _hours(first_ts, last_ts)
    result.metrics = {
        "event_log_start": _fmt(first_ts),
        "event_log_end": _fmt(last_ts),
        "event_log_coverage_min": round(span * 60, 1) if span else None,
        "process_starts": len(starts),
        "kills_logged": len(churn.kills),
        "max_starts_per_min": minutes[0]["starts"],
        "max_starts_minute": minutes[0]["minute"],
        "burst_minutes": sum(1 for r in minutes if r["starts"] > START_BURST_PER_MIN),
        "starts_with_empty_hosting": hosting.get("(none)", 0),
        "processes_in_restart_loops": len(restarts),
        "plug_in_time": _fmt(churn.plug_in, "milliseconds"),
        "starts_60s_after_plug_in": churn.after_plug(s.ts for s in starts)
        if churn.plug_in
        else None,
        "kills_60s_after_plug_in": churn.after_plug(k.ts for k in churn.kills)
        if churn.plug_in
        else None,
        "low_memory_exits_60s_after_plug_in": (
            exit_result.metrics.get("low_memory_kills_60s_after_plug_in")
            if exit_result
            else None
        ),
    }
    burst_rows: list[Row] = [
        {
            "time": _fmt(b[0].ts, "milliseconds"),
            "starts": len(b),
            "processes": ", ".join(s.process for s in b[:10]),
        }
        for b in empty
    ]
    result.add_table("starts_per_minute", minutes)
    result.add_table(
        "hosting_types",
        [{"hosting": h, "starts": n} for h, n in hosting.most_common()],
    )
    result.add_table("restart_loops", restarts)
    result.add_table("empty_hosting_bursts", burst_rows)
    result.notes.append(
        "Only the event-log window is covered; earlier churn is unknown."
    )
    boot_bursts = [
        r
        for r in minutes
        if r["starts"] > START_BURST_PER_MIN
        and churn.booting(datetime.fromisoformat(r["minute"]))
    ]
    if boot_bursts:
        result.notes.append(
            f"{len(boot_bursts)} minutes with over {START_BURST_PER_MIN} starts "
            "fall in the first 15 minutes after boot; that is start-up work, not "
            "reported as a burst.",
        )
    findings = (
        _burst_finding(minutes, churn),
        _plug_flood_finding(result.metrics),
        _restart_finding(restarts, first),
        _prelaunch_finding(empty),
    )
    result.findings = [f for f in findings if f is not None]
    return result
