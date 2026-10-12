"""Tests for the shared since-charge parser (androiddiag.batterystats).

Every dump below is invented; only the layouts follow real batterystats.
"""

from __future__ import annotations

from textwrap import dedent

import pytest
from androiddiag.batterystats import load_since_charge, parse_since_charge
from androiddiag.source import Text

# Android 12-14 layout, decimal-comma locale, a sub-100 mAh discharge.
CHARGED = dedent(
    """\
    Discharge step durations:
      #0: +5m0s0ms to 90 (power-save-off)

    Statistics since last charge:
      System starts: 0, currently on battery: true
      Estimated battery capacity: 3000 mAh
      Time on battery: 2h 0m 0s 0ms (95,5%) realtime, 30m 0s 0ms (23,9%) uptime
      Time on battery screen off: 1h 30m 0s 0ms (75,0%) realtime, 10m 0s 0ms (8,3%) uptime
      Time on battery screen doze: 1m 0s 0ms (0,8%)
      Total run time: 2h 5m 0s 0ms realtime, 35m 0s 0ms uptime
      Discharge: 84.7 mAh
      Screen off discharge: 31.25 mAh
      Screen on discharge: 53.4 mAh
      Start clock time: 2026-01-15-10-00-00
      Screen on: 30m 0s 0ms (25,0%) 4x, Interactive: 29m 0s 0ms (24,2%)

      Device battery use since last full charge
        Amount discharged (lower bound): 3
        Amount discharged (upper bound): 4

      Estimated power use (mAh):
        Capacity: 3000, Computed drain: 80.5, actual drain: 90.0-120
        Global
          screen: 40.0 apps: 40.0 duration: 30m 0s 0ms
          cpu: 30.5 apps: 29.0
          wifi: 4.00 apps: 3.50 duration: 10m 0s 0ms
          idle: 0.500 apps: 0 duration: 2h 0m 0s 0ms
        UID u0a101: 50,5 fg: 10,0 bg: 0,500 ( screen=40.0 (25m 0s 0ms) cpu=10.5 cpu:fg=9.00 wifi=0.0100 (1s 0ms) )
        UID 1000: 20.0 fg: 0.100 ( cpu=19.5 wakelock=0.500 (5m 0s 0ms) )

      All kernel wake locks:
      Kernel Wake lock PowerManagerService.WakeLocks: 5m 0s 0ms (50 times) realtime
      Kernel Wake lock a000000.example,bus:example,charger: 12ms (3 times) realtime
      Kernel Wake lock : 9ms (2 times) realtime

      All wakeup reasons:
      Wakeup reason Abort: Pending Wakeup Sources: EXAMPLE_WS: 1m 0s 0ms (40 times) realtime
      Wakeup reason 12 example_irq: 2m 0s 0ms (100 times) realtime
      Wakeup reason Abort: Last active Wakeup Source: example realtime

      u0a101:
        Wake lock ExampleLock: 1s 0ms partial (2 times) max=600 actual=1200 realtime
        Proc com.example.app:
          CPU: 1m 0s 0ms usr + 30s 0ms krn ; 10s 0ms fg
          3 starts
        Proc com.example.app:remote:
          CPU: 0ms usr + 500ms krn
      1000:
        Total cpu time: u=2m 0s 0ms s=1m 0s 0ms
        Proc system:
          CPU: 2m 0s 0ms usr + 1m 0s 0ms krn ; 0ms fg
          2 crashes 1 anrs

    Per process state tracking available: true
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

# Android 15+ layout with power-state sub-blocks and Samsung's capacity line.
PER_STATE = dedent(
    """\
    Statistics since last charge:
      System starts: 0, currently on battery: true
      Discharge: 200 mAh
      Estimated power use (mAh):
        Capacity: 4000, Rated: 3900, Typical: 4000, Computed drain: 150, actual drain: 150
        Global
        screen: 2.00 apps: 2.00
        cpu: 100 apps: 100 duration: 1h 0m 0s 0ms
        gnss: 40.0 apps: 0 duration: 50m 0s 0ms
        audio: 8.00 apps: 8.00
          (on battery, screen on)
          screen: 0.500 apps: 0.500
          cpu: 5.00 apps: 5.00 duration: 1m 0s 0ms
          (on battery, screen off/doze)
          cpu: 80.0 apps: 80.0 duration: 55m 0s 0ms
          gnss: 39.0 apps: 0 duration: 49m 0s 0ms
          (not on battery, screen on)
          screen: 1.50 apps: 1.50
          cpu: 10.0 apps: 10.0 duration: 2m 0s 0ms
          (not on battery, screen off/doze)
          cpu: 5.00 apps: 5.00 duration: 2m 0s 0ms
          gnss: 1.00 apps: 0 duration: 1m 0s 0ms
      UID 1000: 60.0 bg: 59.0 (20s 0ms) fgs: 1.00 (40s 0ms)
          cpu=60.0 cpu:bg=59.0 cpu:fgs=1.00 wakelock=0.200 (1m 0s 0ms)
          (on battery, screen on) cpu=2.00 cpu:bg=2.00
          (on battery, screen off/doze) cpu=50.0 cpu:bg=50.0 wakelock=0.200 (1m 0s 0ms)
          (not on battery, screen on) cpu=8.00 cpu:bg=8.00
      UID u0a55: 1.00 fg: 1.00
          screen=1.00 cpu=0.0100

      All kernel wake locks:
      Kernel Wake lock example_ipc: 10m 0s 0ms (70 times) realtime
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

# Android 11 and older: Uid rows and device rows, with smearing.
LEGACY = dedent(
    """\
    Statistics since last charge:
      System starts: 2, currently on battery: true
      Estimated power use (mAh):
        Capacity: 5000, Computed drain: 100, actual drain: 0
        Uid u0a120: 60.0 ( cpu=60.0 ) Including smearing: 90.0 ( screen=20.0 proportional=10.0 )
        Screen: 25.0 Excluded from smearing
        Cell standby: 5,50 ( radio=5,50 ) Excluded from smearing
        Uid 1000: 9.50 ( cpu=9.40 wifi=0.100 sensor=0.00100 ) Excluded from smearing
        Idle: 0.500 Excluded from smearing

    """,  # ruff: ignore[line-too-long] - dump lines are long
)


def _text(body: str, origin: str = "live/batterystats_charged.txt") -> Text:
    return Text(origin=origin, text=body)


def _parse(body: str):
    found = parse_since_charge(_text(body))
    assert found is not None
    return found


def test_header_values_with_decimal_mah_and_comma_percentages():
    since = _parse(CHARGED)
    assert since.start == 3
    assert [x for _, x in since.lines() if x.strip()][-1].strip() == "2 crashes 1 anrs"
    assert since.header("Start clock time") == ("2026-01-15-10-00-00", 13)
    assert since.duration_s("Time on battery") == (7200.0, 1800.0)
    assert since.duration_s("Time on battery screen off") == (5400.0, 600.0)
    assert since.duration_s("Time on battery screen doze") == (60.0, None)
    assert since.duration_s("Screen on") == (1800.0, None)
    assert since.duration_s("Discharge") is None
    assert since.mah("Discharge") == pytest.approx(84.7)
    assert since.mah("Screen off discharge") == pytest.approx(31.25)
    assert since.mah("Estimated battery capacity") == 3000
    assert since.mah("Time on battery") is None
    assert since.header("Amount discharged (lower bound)") == ("3", 17)
    assert since.evidence("Discharge")[0].ref == "live/batterystats_charged.txt:11"
    assert since.evidence("No such label") == []


def test_list_entries_are_not_headers():
    since = _parse(CHARGED)
    assert not [label for label in since.headers if label.startswith("Kernel")]
    assert not [label for label in since.headers if label.startswith("Wakeup")]


def test_power_model_android_14():
    power = _parse(CHARGED).power
    assert power is not None
    assert (power.capacity, power.computed_drain) == (3000, 80.5)
    assert (power.actual_drain_min, power.actual_drain_max) == (90.0, 120)
    assert power.rated is None
    assert power.global_components["cpu"].apps_mah == pytest.approx(29.0)
    assert power.global_components["screen"].duration_s == 1800
    assert power.state_components == {}
    assert power.on_battery_components() == {
        "screen": 40.0,
        "cpu": 30.5,
        "wifi": 4.0,
        "idle": 0.5,
    }
    assert power.modelled_mah() == pytest.approx(75.0)
    app = power.uids[10101]
    assert app.total == pytest.approx(50.5)
    assert app.states == {"fg": 10.0, "bg": 0.5}
    assert app.components == {"screen": 40.0, "cpu": 10.5, "wifi": 0.01}
    assert app.durations == {"screen": 1500.0, "wifi": 1.0}
    assert app.on_battery() == app.components
    assert power.uids[1000].durations == {"wakelock": 300.0}
    assert power.unparsed == 0


def test_power_model_per_state_keeps_global_and_sums_on_battery():
    power = _parse(PER_STATE).power
    assert power is not None
    assert (power.capacity, power.rated, power.typical) == (4000, 3900, 4000)
    assert power.computed_drain == 150
    # The last "(not on battery ...)" block must not overwrite Global.
    assert power.global_components["cpu"].mah == 100
    assert power.global_components["gnss"].mah == pytest.approx(40.0)
    assert list(power.state_components) == [
        "on battery, screen on",
        "on battery, screen off/doze",
        "not on battery, screen on",
        "not on battery, screen off/doze",
    ]
    on_battery = power.on_battery_components()
    assert on_battery["cpu"] == pytest.approx(85.0)
    assert on_battery["gnss"] == pytest.approx(39.0)
    assert on_battery["screen"] == pytest.approx(0.5)
    # No state data for audio: its all-states value is kept.
    assert on_battery["audio"] == pytest.approx(8.0)
    assert power.modelled_mah() == pytest.approx(132.5)
    assert power.unparsed == 0


def test_uid_continuation_lines_per_state():
    power = _parse(PER_STATE).power
    assert power is not None
    system = power.uids[1000]
    assert system.states == {"bg": 59.0, "fgs": 1.0}
    assert system.components == {"cpu": 60.0, "wakelock": 0.2}
    assert system.durations == {"wakelock": 60.0}
    assert system.power_states["on battery, screen off/doze"] == {
        "cpu": 50.0,
        "wakelock": 0.2,
    }
    assert system.on_battery() == {"cpu": 52.0, "wakelock": 0.2}
    assert len(system.lines) == 5
    assert power.uids[10055].components == {"screen": 1.0, "cpu": 0.01}


def test_power_block_ends_before_kernel_wakelocks():
    since = _parse(PER_STATE)
    assert [w.name for w in since.kernel_wakelocks] == ["example_ipc"]
    assert since.mah("Discharge") == 200


def test_legacy_power_model():
    power = _parse(LEGACY).power
    assert power is not None
    assert power.actual_drain_min == power.actual_drain_max == 0
    assert power.global_components == {}
    assert power.on_battery_components() == {}
    assert power.modelled_mah() is None
    assert power.device_rows == {
        "Screen": (25.0, 5),
        "Cell standby": (5.5, 6),
        "Idle": (0.5, 8),
    }
    app = power.uids[10120]
    assert app.total == pytest.approx(60.0)
    # Smearing shares are not components of the app.
    assert app.components == {"cpu": 60.0}
    assert power.uids[1000].components == {"cpu": 9.4, "wifi": 0.1, "sensor": 0.001}


def test_kernel_wakelocks_and_wakeup_reasons():
    since = _parse(CHARGED)
    names = [(w.name, w.seconds, w.count) for w in since.kernel_wakelocks]
    assert names == [
        ("PowerManagerService.WakeLocks", 300.0, 50),
        ("a000000.example,bus:example,charger", 0.012, 3),
        ("", 0.009, 2),
    ]
    reasons = [(r.name, r.seconds, r.count) for r in since.wakeup_reasons]
    assert reasons == [
        ("Abort: Pending Wakeup Sources: EXAMPLE_WS", 60.0, 40),
        ("12 example_irq", 120.0, 100),
        ("Abort: Last active Wakeup Source: example", None, None),
    ]


def test_uid_blocks_and_proc_cpu():
    since = _parse(CHARGED)
    assert set(since.uid_blocks) == {10101, 1000}
    assert since.uid_blocks[1000][0][1].strip().startswith("Total cpu time")
    procs = {(p.uid, p.name): p for p in since.procs}
    app = procs[10101, "com.example.app"]
    assert (app.usr_s, app.krn_s, app.fg_s, app.starts) == (60.0, 30.0, 10.0, 3)
    assert app.cpu_s == pytest.approx(90.0)
    assert app.cpu_index == app.index + 1
    remote = procs[10101, "com.example.app:remote"]
    assert (remote.cpu_s, remote.fg_s) == (0.5, None)
    system = procs[1000, "system"]
    assert (system.crashes, system.anrs) == (2, 1)


def test_no_block_returns_none():
    assert parse_since_charge(_text("Battery History:\n  0 (1) 100\n")) is None


def test_headerless_charged_dump_is_read_whole():
    body = "  Discharge: 12.5 mAh\n  Time on battery: 1h 0m 0s 0ms (100,0%) realtime\n"
    assert parse_since_charge(_text(body)) is None
    since = parse_since_charge(_text(body), whole=True)
    assert since is not None
    assert since.start == -1
    assert since.mah("Discharge") == pytest.approx(12.5)


def test_load_prefers_charged_then_full_dump(context_factory):
    full = "Battery History:\n  Discharge: 1 mAh\n" + CHARGED.replace("84.7", "99.9")
    ctx = context_factory(live={"batterystats": full, "batterystats_charged": CHARGED})
    since = load_since_charge(ctx)
    assert since is not None
    assert since.mah("Discharge") == pytest.approx(84.7)
    assert load_since_charge(ctx) is since

    ctx = context_factory(live={"batterystats": full})
    since = load_since_charge(ctx)
    assert since is not None
    assert since.text.origin == "live/batterystats.txt"
    # The history before the block is not read.
    assert since.mah("Discharge") == pytest.approx(99.9)


def test_load_headerless_charged(context_factory):
    ctx = context_factory(live={"batterystats_charged": "  Discharge: 7.25 mAh\n"})
    since = load_since_charge(ctx)
    assert since is not None
    assert since.mah("Discharge") == pytest.approx(7.25)
    assert load_since_charge(context_factory(live={"battery": "x"})) is None


def test_load_from_bugreport_service(context_factory):
    ctx = context_factory(services={"batterystats": PER_STATE})
    since = load_since_charge(ctx)
    assert since is not None
    assert since.text.origin == "bugreport:dumpsys batterystats"
    assert since.power is not None
    assert since.power.uids[1000].total == pytest.approx(60.0)
