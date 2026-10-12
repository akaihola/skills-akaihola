"""Tests for the windows analyzer and the Windows time helpers (invented data)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from textwrap import dedent
from zoneinfo import ZoneInfo

import pytest
from androiddiag.model import Windows
from androiddiag.windows import windows as fill_windows

# 2026-03-02 00:00:00 UTC
RESET_EPOCH_MS = 1_772_409_600_000
GETPROP_UTC = "[persist.sys.timezone]: [UTC]\n"


def charged(starts: int, start_clock: str, *, on_battery: bool) -> str:
    return dedent(
        f"""\
        Statistics since last charge:
          System starts: {starts}, currently on battery: {str(on_battery).lower()}
          Time on battery: 6h 0m 0s 0ms (95,0%) realtime, 1h 0m 0s 0ms (15,8%) uptime
          Time on battery screen off: 5h 0m 0s 0ms (79,2%) realtime, 40m 0s 0ms (10,5%) uptime
          Discharge: 250 mAh
          Start clock time: {start_clock}
        """,  # ruff: ignore[line-too-long] - dump lines are long
    )


def checkin(*rows: str) -> str:
    return "9,0,i,vers,36,215,TEST.1,TEST.2\n" + "\n".join(rows) + "\n"


REBOOT_HISTORY = checkin(
    f"9,h,0:RESET:TIME:{RESET_EPOCH_MS}",
    "9,h,0,Bl=95,Bs=d,+r,+S",
    "9,h,1800000,-S,-r",
    "9,h,7200000:SHUTDOWN",
    "9,h,1:START",
    f"9,h,0:TIME:{RESET_EPOCH_MS + 14_400_000}",
    "9,h,0,Bl=70,Bs=d,+r",
    "9,h,3600000,-r",
)


def test_start_clock_after_reboot_uses_history_reset(context_factory):
    ctx = context_factory(
        live={
            "batterystats_charged": charged(1, "2026-03-02-04-00-00", on_battery=True),
            "batterystats_checkin": REBOOT_HISTORY,
            "getprop": GETPROP_UTC,
        },
    )
    result = fill_windows(ctx)
    assert ctx.windows.since_charge_start == datetime(2026, 3, 2, 0, 0)
    assert result.metrics["since_charge_start"] == "2026-03-02 00:00:00"
    assert result.metrics["start_clock_time"] == "2026-03-02 04:00:00"
    assert any("reboot within the period" in note for note in result.notes)
    refs = [row["ref"] for row in result.tables["anchors"]]
    assert "live/batterystats_checkin.txt:2" in refs


def test_start_clock_kept_without_reboot(context_factory):
    history = REBOOT_HISTORY.replace("9,h,7200000:SHUTDOWN\n9,h,1:START\n", "")
    ctx = context_factory(
        live={
            "batterystats_charged": charged(0, "2026-03-02-04-00-00", on_battery=True),
            "batterystats_checkin": history,
            "getprop": GETPROP_UTC,
        },
    )
    result = fill_windows(ctx)
    assert ctx.windows.since_charge_start == datetime(2026, 3, 2, 4, 0)
    assert "start_clock_time" not in result.metrics


def test_reboot_without_reset_record_is_noted(context_factory):
    history = REBOOT_HISTORY.replace(":RESET:TIME:", ":TIME:")
    ctx = context_factory(
        live={
            "batterystats_charged": charged(2, "2026-03-02-04-00-00", on_battery=True),
            "batterystats_checkin": history,
            "getprop": GETPROP_UTC,
        },
    )
    result = fill_windows(ctx)
    assert ctx.windows.since_charge_start == datetime(2026, 3, 2, 4, 0)
    assert any("no RESET record" in note for note in result.notes)


def test_since_charge_header_fills_uptime_parts(context_factory):
    ctx = context_factory(
        live={
            "batterystats_charged": charged(0, "2026-03-02-08-00-00", on_battery=True),
        },
    )
    result = fill_windows(ctx)
    w = ctx.windows
    assert (w.on_battery_s, w.on_battery_uptime_s) == (21_600, 3600)
    assert (w.screen_off_on_battery_s, w.screen_off_uptime_s) == (18_000, 2400)
    assert w.on_battery_at_capture is True
    assert w.plugged_at is None
    assert w.plugged_at_source is None
    assert result.metrics["on_battery_uptime_s"] == 3600


def test_plugged_at_from_history(context_factory):
    history = checkin(
        f"9,h,0:RESET:TIME:{RESET_EPOCH_MS}",
        "9,h,0,Bl=95,Bs=d,+r",
        "9,h,3600000,Bl=80,-r",
        "9,h,600000,Bs=c,+BP",
    )
    ctx = context_factory(
        live={
            "batterystats_charged": charged(0, "2026-03-02-00-00-00", on_battery=False),
            "batterystats_checkin": history,
            "getprop": GETPROP_UTC,
        },
    )
    fill_windows(ctx)
    assert ctx.windows.plugged_at == datetime(2026, 3, 2, 1, 10)
    assert ctx.windows.plugged_at_source == "battery history plug-in record"


EVENTS = dedent(
    """\
    --------- beginning of events
    2026-03-02 05:00:00.000  1000  1500  1600 I battery_status: [3,2,1,0,Li-ion]
    2026-03-02 05:30:00.000  1000  1500  1600 I screen_toggled: 1
    2026-03-02 05:45:10.250  1000  1500  1600 I battery_status: [2,2,1,2,Li-ion]
    2026-03-02 05:50:00.000  1000  1500  1600 I screen_toggled: 0
    """,
)


def test_plugged_at_from_event_log(context_factory):
    ctx = context_factory(
        live={
            "batterystats_charged": charged(0, "2026-03-02-00-00-00", on_battery=False),
            "logcat_events": EVENTS,
        },
    )
    result = fill_windows(ctx)
    assert ctx.windows.plugged_at == datetime(2026, 3, 2, 5, 45, 10, 250_000)
    assert ctx.windows.plugged_at_source == "event log battery_status"
    refs = [row["ref"] for row in result.tables["anchors"]]
    assert "live/logcat_events.txt:4" in refs


def test_plugged_at_estimate(context_factory):
    ctx = context_factory(
        live={
            "batterystats_charged": charged(0, "2026-03-02-00-00-00", on_battery=False),
        },
    )
    fill_windows(ctx)
    assert ctx.windows.plugged_at == datetime(2026, 3, 2, 6, 0)
    assert ctx.windows.plugged_at_source == (
        "since-charge start + time on battery (estimate)"
    )


def test_zone_sets_offset_without_clock(context_factory):
    ctx = context_factory(
        live={
            "getprop": "[persist.sys.timezone]: [Europe/Berlin]\n",
            "alarm": "  nowRTC=1768471200000=2026-01-15 11:00:00 nowELAPSED=3600000\n",
        },
    )
    result = fill_windows(ctx)
    w = ctx.windows
    assert w.zone == ZoneInfo("Europe/Berlin")
    assert w.utc_offset == "+0100"
    assert w.boot_time == datetime(2026, 1, 15, 10, 0)
    assert result.metrics["zone"] == "Europe/Berlin"


def test_unknown_zone_falls_back_to_alarm_offset(context_factory):
    ctx = context_factory(
        live={
            "getprop": "[persist.sys.timezone]: [No/Such_Zone]\n",
            "alarm": "  nowRTC=1768471200000=2026-01-15 13:00:00 nowELAPSED=3600000\n",
        },
    )
    fill_windows(ctx)
    assert ctx.windows.zone is None
    assert ctx.windows.utc_offset == "+0300"


# --- Windows helpers -------------------------------------------------------------


def test_offset_and_local_from_epoch():
    july = datetime(2026, 7, 15, 9, 0, tzinfo=UTC).timestamp()
    fixed = Windows(utc_offset="+0100")
    assert fixed.offset() == timedelta(hours=1)
    assert fixed.local_from_epoch(july) == datetime(2026, 7, 15, 10, 0)
    # The time zone knows about summer time; the capture offset does not.
    zoned = Windows(utc_offset="+0100", zone=ZoneInfo("Europe/Berlin"))
    assert zoned.local_from_epoch(july) == datetime(2026, 7, 15, 11, 0)
    assert Windows(utc_offset="-05:30").offset() == -timedelta(hours=5, minutes=30)
    assert Windows(utc_offset="bogus").offset() is None
    assert Windows().local_from_epoch(july) is None
    assert Windows(zone=UTC).local_from_epoch(1e20) is None


def test_battery_span():
    start = datetime(2026, 3, 2, 0, 0)
    dump = datetime(2026, 3, 2, 8, 0)
    plug = datetime(2026, 3, 2, 6, 0)
    on_battery = Windows(since_charge_start=start, dump_time=dump)
    assert on_battery.battery_span() == (start, dump)
    charging = Windows(
        since_charge_start=start,
        dump_time=dump,
        plugged_at=plug,
        on_battery_at_capture=False,
    )
    assert charging.battery_span() == (start, plug)
    charging.plugged_at = None
    assert charging.battery_span() is None
    assert Windows(dump_time=dump).battery_span() is None


def test_log_reference_and_to_dict():
    dump = datetime(2026, 3, 2, 8, 0)
    assert Windows(dump_time=dump).log_reference() == dump
    assert Windows().log_reference() > dump
    out = Windows(dump_time=dump, zone=ZoneInfo("UTC")).to_dict()
    assert out["dump_time"] == "2026-03-02 08:00:00"
    assert out["zone"] == "UTC"
    assert out["plugged_at_source"] is None


@pytest.mark.parametrize("powered", [False, True])
def test_plug_state_from_battery_dump(context_factory, powered):
    ctx = context_factory(live={"battery": f"  AC powered: {str(powered).lower()}"})
    result = fill_windows(ctx)
    assert ctx.windows.on_battery_at_capture is (not powered)
    assert ctx.windows.since_charge_start is None
    assert "No time anchors found; windows are unknown." in result.notes
