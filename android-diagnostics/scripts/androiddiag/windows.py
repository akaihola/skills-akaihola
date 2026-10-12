"""Time anchors shared by every analyzer: capture time, boot, last full charge.

Each data source covers its own window (since boot, since the last charge, the
log buffer, a 24-hour bucket). Analyzers label their numbers with a window
name from ``model.WINDOWS``; this analyzer fills ``ctx.windows`` so they can
convert between wall-clock time and those windows.
"""

from __future__ import annotations

import contextlib
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .batterystats import load_since_charge
from .common import load_event_log
from .model import Context, Evidence, Result, Windows, analyzer

if TYPE_CHECKING:
    from .batterystats import SinceCharge

_NOW_RTC_RE = re.compile(
    r"nowRTC=\d+=(?P<rtc>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.\d+)? "
    r"nowELAPSED=(?P<elapsed>\d+)",
)
_START_CLOCK_RE = re.compile(r"^(\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d)")
_SYSTEM_STARTS_RE = re.compile(r"^(\d+), currently on battery: (true|false)")
_POWERED_RE = re.compile(r"^\s*(AC|USB|Wireless|Dock) powered: (true|false)")
_CLOCK_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ([+-]\d{4})$")
_UPTIME_RE = re.compile(r"^(\d+(?:\.\d+)?) \d+(?:\.\d+)?$")

# 'Start clock time' later than the history's RESET record by more than this
# is the boot time of a reboot within the period, not the last full charge.
START_CLOCK_SLACK_S = 120


def _parse_clock(ctx: Context, windows: Windows, evidence: list[Evidence]) -> None:
    """Read ``live/clock.txt``: epoch, local time with offset, /proc/uptime."""
    clock = ctx.sources.get("clock")
    if clock is None:
        return
    for i, line in enumerate(clock.lines):
        if m := _CLOCK_RE.match(line.strip()):
            windows.dump_time = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S")
            windows.utc_offset = m[2]
            evidence.append(clock.evidence(i))
        elif (m := _UPTIME_RE.match(line.strip())) and windows.dump_time:
            windows.boot_time = windows.dump_time - timedelta(seconds=float(m[1]))


def _parse_bugreport_time(ctx: Context, windows: Windows) -> None:
    br = ctx.sources.workdir.bugreport
    if br is None or windows.dump_time:
        return
    stamp = br.header.get("dumpstate_time")
    if stamp:
        windows.dump_time = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")


def _parse_alarm_boot(ctx: Context, windows: Windows, evidence: list[Evidence]) -> None:
    """Boot time = alarm manager's nowRTC minus nowELAPSED (ms since boot)."""
    alarm = ctx.sources.get("alarm")
    if alarm is None or windows.boot_time:
        return
    for i, m in alarm.find(_NOW_RTC_RE):
        rtc = datetime.strptime(m["rtc"], "%Y-%m-%d %H:%M:%S")
        windows.boot_time = rtc - timedelta(milliseconds=int(m["elapsed"]))
        if windows.dump_time is None:
            windows.dump_time = rtc
        evidence.append(alarm.evidence(i))
        return


def _parse_since_charge(
    since: SinceCharge,
    windows: Windows,
    evidence: list[Evidence],
) -> int | None:
    """Read the since-charge header; return the ``System starts`` count."""
    starts: int | None = None
    used: list[int] = []
    if (found := since.header("Start clock time")) and (
        m := _START_CLOCK_RE.match(found[0])
    ):
        windows.since_charge_start = datetime.strptime(m[1], "%Y-%m-%d-%H-%M-%S")
        used.append(found[1])
    if (found := since.header("System starts")) and (
        m := _SYSTEM_STARTS_RE.match(found[0])
    ):
        starts = int(m[1])
        windows.on_battery_at_capture = m[2] == "true"
        used.append(found[1])
    for label, real, awake in (
        ("Time on battery", "on_battery_s", "on_battery_uptime_s"),
        (
            "Time on battery screen off",
            "screen_off_on_battery_s",
            "screen_off_uptime_s",
        ),
    ):
        if seconds := since.duration_s(label):
            setattr(windows, real, seconds[0])
            setattr(windows, awake, seconds[1])
            used.append(since.headers[label][1])
    evidence.extend(since.text.evidence(i) for i in sorted(used))
    return starts


def _check_start_clock(
    ctx: Context,
    starts: int | None,
    evidence: list[Evidence],
    result: Result,
) -> None:
    """Prefer the history's RESET record when a reboot re-stamped the start.

    batterystats moves 'Start clock time' to the boot time whenever the wall
    clock is set (AOSP ``BatteryStatsImpl.adjustStartClockTime``), so after
    a reboot within the period it no longer marks the last full charge.
    """
    windows = ctx.windows
    printed = windows.since_charge_start
    if printed is None:
        return
    # Imported here: battery_history registers its own analyzers on import.
    from .battery_history import load_history  # ruff: ignore[import-outside-top-level]

    history = load_history(ctx)
    records = history.records if history else []
    resets = [pos for pos, r in enumerate(records) if r.command == "RESET" and r.clock]
    after = records[resets[-1] + 1 :] if resets else records
    rebooted = bool(starts) or any(r.command == "START" for r in after)
    if not rebooted:
        return
    reset_clock = records[resets[-1]].clock if resets else None
    if history is None or reset_clock is None:
        result.notes.append(
            f"'Start clock time' may be the boot time of a reboot within the "
            f"period (System starts: {starts}); the battery history has no "
            "RESET record to confirm the last full charge.",
        )
        return
    if reset_clock >= printed - timedelta(seconds=START_CLOCK_SLACK_S):
        return
    windows.since_charge_start = reset_clock
    evidence.append(history.evidence(resets[-1]))
    result.metrics["start_clock_time"] = printed.isoformat(sep=" ")
    result.notes.append(
        f"'Start clock time' {printed:%Y-%m-%d %H:%M:%S} is the boot time of a "
        f"reboot within the period; the last full charge is taken from the "
        f"battery history's RESET record instead ({reset_clock:%Y-%m-%d %H:%M:%S}).",
    )


_GETPROP_TZ_RE = re.compile(r"^\[persist\.sys\.timezone\]: \[([^\]]+)\]")
_NOW_RTC_EPOCH_RE = re.compile(
    r"nowRTC=(?P<epoch>\d+)=(?P<local>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)",
)


def _format_offset(offset: timedelta) -> str:
    minutes = round(offset.total_seconds() / 60)
    sign = "-" if minutes < 0 else "+"
    hours, mins = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}{mins:02d}"


def _fill_zone(ctx: Context, windows: Windows) -> None:
    """Read the phone's time zone from the ``persist.sys.timezone`` property."""
    getprop = ctx.sources.get("getprop")
    for _, m in getprop.find(_GETPROP_TZ_RE) if getprop else []:
        with contextlib.suppress(ZoneInfoNotFoundError, ValueError, OSError):
            windows.zone = ZoneInfo(m[1])
        return


def _fill_utc_offset(ctx: Context, windows: Windows) -> None:
    """Without a clock dump, use the time zone or the alarm clock pair."""
    if windows.utc_offset:
        return
    if windows.zone is not None and windows.dump_time is not None:
        offset = windows.dump_time.replace(tzinfo=windows.zone).utcoffset()
        if offset is not None:
            windows.utc_offset = _format_offset(offset)
            return
    alarm = ctx.sources.get("alarm")
    if alarm is None:
        return
    for _, m in alarm.find(_NOW_RTC_EPOCH_RE):
        local = datetime.fromisoformat(m["local"])
        utc = datetime.fromtimestamp(int(m["epoch"]) / 1000, tz=UTC)
        # Round to the 15-minute grid that real time zones use.
        quarter_hours = round((local - utc.replace(tzinfo=None)).total_seconds() / 900)
        windows.utc_offset = _format_offset(timedelta(minutes=15 * quarter_hours))
        return


def _fill_plugged_at(ctx: Context, windows: Windows, evidence: list[Evidence]) -> None:
    """When the phone was plugged in at capture, find when that happened.

    Sources in order: the battery history's last plug-in, the event log's
    last ``battery_status`` plug-in, then the last full charge plus the time
    on battery (an estimate that assumes one unplugged stretch).
    """
    if windows.plugged_at or windows.on_battery_at_capture is not False:
        return
    # Imported here: battery_history registers its own analyzers on import.
    from .battery_history import load_timeline  # ruff: ignore[import-outside-top-level]

    timeline = load_timeline(ctx)
    if timeline and timeline.plug_ins and timeline.plugged_at_end:
        pos = timeline.plug_ins[-1]
        if stamp := timeline.history.wall(pos):
            windows.plugged_at = stamp
            windows.plugged_at_source = "battery history plug-in record"
            evidence.append(timeline.history.evidence(pos))
            return
    start = windows.since_charge_start
    events = load_event_log(ctx)
    states = events.battery_states()
    plug_ins = [
        t
        for t in events.power_transitions()
        if t.on and (start is None or t.ts > start)
    ]
    if plug_ins and states[-1].on:
        windows.plugged_at = plug_ins[-1].ts
        windows.plugged_at_source = "event log battery_status"
        evidence.append(Evidence(plug_ins[-1].ref, plug_ins[-1].line))
        return
    if start and windows.on_battery_s:
        windows.plugged_at = start + timedelta(seconds=windows.on_battery_s)
        windows.plugged_at_source = "since-charge start + time on battery (estimate)"


def _parse_battery_dump(ctx: Context, windows: Windows) -> None:
    """Fall back to ``dumpsys battery`` for the plug state."""
    if windows.on_battery_at_capture is not None:
        return
    battery = ctx.sources.get("battery")
    if battery is None:
        return
    powered = [m[2] == "true" for _, m in battery.find(_POWERED_RE)]
    if powered:
        windows.on_battery_at_capture = not any(powered)


@analyzer("windows", after=())
def windows(ctx: Context) -> Result:
    """Fill ``ctx.windows`` from the clock, alarm and batterystats dumps."""
    found = Windows()
    evidence: list[Evidence] = []
    result = Result("windows", window="snapshot")
    _parse_clock(ctx, found, evidence)
    _parse_bugreport_time(ctx, found)
    _parse_alarm_boot(ctx, found, evidence)
    since = load_since_charge(ctx)
    starts = _parse_since_charge(since, found, evidence) if since else None
    _parse_battery_dump(ctx, found)
    _fill_zone(ctx, found)
    _fill_utc_offset(ctx, found)
    ctx.windows = found
    _check_start_clock(ctx, starts, evidence, result)
    _fill_plugged_at(ctx, found, evidence)
    result.metrics.update(found.to_dict())
    if found.dump_time and found.boot_time:
        result.metrics["uptime_h"] = round(
            (found.dump_time - found.boot_time).total_seconds() / 3600,
            2,
        )
    if found.on_battery_at_capture is False:
        result.notes.append(
            "The phone was on external power at capture: live states such as "
            "battery saver, Doze and thermal status describe charging, not use.",
        )
    if not evidence:
        result.notes.append("No time anchors found; windows are unknown.")
    result.tables["anchors"] = [{"ref": e.ref, "line": e.excerpt} for e in evidence]
    return result
