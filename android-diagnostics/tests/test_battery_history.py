"""Tests for battery history replay, standby wakes and since-charge accounting.

All fixture text is invented: package names are com.example.*, wake reasons
and wakelock tags are made up, and times are arbitrary.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from operator import itemgetter
from textwrap import dedent

import pytest
from androiddiag import battery_history as bh
from androiddiag.model import SkipError, Windows
from androiddiag.source import Text

RESET_LOCAL = datetime(2026, 1, 15, 8, 0, 0)
RESET_EPOCH_MS = int(RESET_LOCAL.replace(tzinfo=UTC).timestamp() * 1000)
WLAN = "41 WLAN_EXAMPLE"
SPAN_START_MS = 600_000
HOUR_MS = 3_600_000

# History token names to checkin codes, for the subset the fixtures use.
FLAG_CODES = {
    "running": "r",
    "wake_lock": "w",
    "screen": "S",
    "plugged": "BP",
    "mobile_radio": "Pr",
    "screen_doze": "Sd",
}
VALUE_CODES = {
    "status": ("Bs", {"discharging": "d", "charging": "c"}),
    "plug": ("Bp", {"none": "n", "ac": "a"}),
    "charge": ("Bcc", {}),
    "device_idle": ("di", {}),
    "volt": ("Bv", {}),
}


def text_time(ms: int) -> str:
    """Format like batterystats: ``0``, ``+460ms``, ``+1s008ms``, ``+1h05m05s381ms``."""
    if ms == 0:
        return "0"
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, msec = divmod(rest, 1000)
    out = "+"
    if h:
        out += f"{h}h{m:02d}m{s:02d}s"
    elif m:
        out += f"{m}m{s:02d}s"
    elif s:
        out += f"{s}s"
    return out + (f"{msec:03d}ms" if out != "+" else f"{msec}ms")


@dataclass
class HistoryBuilder:
    """Build the same invented history as checkin rows and as a text dump."""

    events: list[tuple[int, int, list[str], str]] = field(default_factory=list)

    def add(self, t: int, *tokens: str, level: int = 100) -> None:
        self.events.append((t, level, list(tokens), ""))

    def command(self, t: int, name: str) -> None:
        self.events.append((t, 0, [], name))

    def ordered(self) -> list[tuple[int, int, list[str], str]]:
        return sorted(self.events, key=itemgetter(0))

    def text(self, *, details: bool = False) -> str:
        lines = ["Battery History (1% used, 10KB used of 4096KB, 3 strings using 1KB):"]
        for t, level, tokens, command in self.ordered():
            stamp = (RESET_LOCAL + timedelta(milliseconds=t)).strftime(
                "%Y-%m-%d-%H-%M-%S",
            )
            if command == "RESET":
                lines.append(f"{text_time(t):>21} (14) RESET:TIME: {stamp}")
            elif command == "TIME":
                lines.append(f"{text_time(t):>21} (40) TIME: {stamp}")
            else:
                body = " ".join([f"{level:03d}", *tokens])
                lines.append(f"{text_time(t):>21} (2) {body}")
            if details and command == "RESET":
                lines.append("                 Details: cpu=100u+50s")
        lines += ["", "Per-PID Stats:", "  PID 1 wake time: +1s"]
        return "\n".join(lines) + "\n"

    def checkin(self) -> str:
        pool: dict[tuple[str, str], int] = {}
        rows: list[str] = []
        prev = 0
        level = None
        for t, lvl, tokens, command in self.ordered():
            delta, prev = t - prev, t
            if command:
                epoch = RESET_EPOCH_MS + t
                name = "RESET:TIME" if command == "RESET" else "TIME"
                rows.append(f"9,h,{delta}:{name}:{epoch}")
                continue
            parts = []
            if lvl != level:
                parts.append(f"Bl={lvl}")
                level = lvl
            parts += [self._code(token, pool) for token in tokens]
            rows.append(",".join([f"9,h,{delta}", *parts]))
        head = ["9,0,i,vers,36,215,TEST.1,TEST.2"]
        head += [f'9,hsp,{i},{uid},"{tag}"' for (uid, tag), i in pool.items()]
        return "\n".join(head + rows) + "\n"

    @staticmethod
    def _code(token: str, pool: dict[tuple[str, str], int]) -> str:
        sign = token[0] if token[0] in "+-" else ""
        name, _, value = token.lstrip("+-").partition("=")
        if value and ":" in value and value.endswith('"'):
            uid, _, tag = value.partition(":")
            index = pool.setdefault((uid, tag.strip('"')), len(pool))
            code = "wr" if name == "wake_reason" else FLAG_CODES.get(name, name)
            return f"{sign}{code}={index}"
        if name in FLAG_CODES:
            return f"{sign}{FLAG_CODES[name]}"
        code, values = VALUE_CODES[name]
        return f"{code}={values.get(value, value)}"


def storm_history(
    *,
    period_ms: int = 3000,
    awake_ms: int = 1500,
    minutes: int = 60,
    gaps: list[int] | None = None,
) -> HistoryBuilder:
    """Unplug, an hour screen-off with a wake every ``period_ms``, plug in."""
    b = HistoryBuilder()
    b.command(0, "RESET")
    b.add(
        0,
        "status=discharging",
        "plug=none",
        "charge=2970",
        "+running",
        "+wake_lock",
        "+screen",
        "+plugged",
    )
    b.add(0, "-plugged")
    start, end = SPAN_START_MS, SPAN_START_MS + minutes * 60_000
    b.add(start, "-screen", level=99)
    b.add(start + 100, '-wake_lock=1000:"ExampleLock"', level=99)
    b.add(start + 1000, "-running", level=99)
    b.add(start + 5 * 60_000 + 1, "device_idle=full", level=99)
    b.command(start + 30 * 60_000 + 2, "TIME")
    t = start + 2000
    k = 0
    while t < end - 5000:
        b.add(t, "+running", f'wake_reason=0:"{WLAN}"', level=99)
        b.add(t + 200, 'wake_reason=0:"Abort: Pending Wakeup Sources: example_ws"')
        b.add(t + awake_ms, "-running", level=99)
        t += gaps[k % len(gaps)] if gaps else period_ms
        k += 1
    for step in range(1, minutes // 10 + 1):
        charge = 3000 * (99 - step) // 100
        b.add(start + step * 600_000 + 3, f"charge={charge}", level=99 - step // 2)
    b.add(end, "+running", "device_idle=off", "+screen", level=96)
    b.add(end + 300_000, "plug=ac", "status=charging", "+plugged", level=96)
    return b


def quiet_history() -> HistoryBuilder:
    """An hour screen-off with one short wake every two minutes."""
    return storm_history(period_ms=120_000, awake_ms=300)


@pytest.fixture
def ctx_for(context_factory):
    """Build a context with UTC times from live dumps and bugreport parts."""

    def build(live=None, windows=None, **bugreport):
        return context_factory(
            live=live,
            windows=windows or Windows(utc_offset="+0000"),
            **bugreport,
        )

    return build


# ---------------------------------------------------------------------------
# History parsing and replay


def test_text_time_format_round_trips():
    for ms in (0, 460, 1008, 622_819, 3_905_381, 90_000_000):
        text = text_time(ms)
        assert (0 if text == "0" else bh.parse_duration_ms(text)) == ms


def test_checkin_and_text_history_agree(ctx_for):
    builder = storm_history()
    from_checkin = ctx_for(live={"batterystats_checkin": builder.checkin()})
    from_text = ctx_for(live={"batterystats": builder.text()})
    results = []
    for ctx in (from_checkin, from_text):
        history = bh.battery_history(ctx)
        standby = bh.standby_wake(ctx)
        results.append((history.metrics, standby.metrics, ctx.windows.plugged_at))
    (h1, s1, p1), (h2, s2, p2) = results
    assert h1["format"] == "checkin"
    assert h2["format"] == "text"
    for key in ("on_battery_s", "screen_off_on_battery_s", "screen_off_spans"):
        assert h1[key] == h2[key]
    assert s1 == s2
    # Text TIME stamps are truncated to the second; checkin carries ms.
    expected = RESET_LOCAL + timedelta(minutes=75)
    assert p1 == expected
    assert p2 is not None
    assert abs(p2 - expected) < timedelta(seconds=1)


def test_history_replay_measures_spans_and_resumes(ctx_for):
    ctx = ctx_for(live={"batterystats_checkin": storm_history().checkin()})
    history = bh.battery_history(ctx)
    m = history.metrics
    assert m["has_reset"] is True
    assert m["screen_off_spans"] == 1
    assert m["screen_off_on_battery_s"] == pytest.approx(3600.0)
    assert m["on_battery_s"] == pytest.approx(4500.0)
    assert m["plugged_at_end"] is True
    assert m["charge_samples"] == 7
    assert history.tables["screen_off_spans"][0]["start"] == "2026-01-15 08:10:00"
    standby = bh.standby_wake(ctx).metrics
    expected = (HOUR_MS - 7000) // 3000 + 1
    assert standby["resumes"] == expected
    assert standby["resumes_per_h"] == pytest.approx(expected, abs=0.1)
    assert standby["resume_interval_median_s"] == pytest.approx(3.0)
    assert standby["awake_per_resume_median_s"] == pytest.approx(1.5)
    assert standby["asleep_between_resumes_median_s"] == pytest.approx(1.5)
    assert standby["awake_share_pct"] == pytest.approx(50, abs=0.5)
    assert standby["top_wake_reason"] == WLAN
    assert standby["suspend_aborts_in_history"] == expected
    assert standby["deep_idle_share_pct"] == pytest.approx(91.7, abs=0.1)


def test_continuation_lines_and_backward_steps_are_counted(ctx_for):
    builder = storm_history()
    builder.add(SPAN_START_MS + 2001, "volt=4000", level=99)
    builder.add(SPAN_START_MS + 1999, "volt=4001", level=99)
    text = builder.text(details=True)
    # Swap the two records so the second steps back in time by 2 ms.
    lines = text.splitlines()
    a = next(i for i, x in enumerate(lines) if "volt=4001" in x)
    b = next(i for i, x in enumerate(lines) if "volt=4000" in x)
    lines[a], lines[b] = lines[b], lines[a]
    ctx = ctx_for(live={"batterystats": "\n".join(lines) + "\n"})
    m = bh.battery_history(ctx).metrics
    assert m["continuation_lines"] == 1
    assert m["backward_time_steps"] >= 1
    assert m["unparsed_lines"] == 0


def test_wake_reason_on_a_same_time_record_is_attached():
    builder = HistoryBuilder()
    builder.command(0, "RESET")
    builder.add(0, "status=discharging", "plug=none", "+running")
    builder.add(1000, "-running")
    builder.add(5000, "+running")
    builder.add(5000, f'wake_reason=0:"{WLAN}"')
    builder.add(6000, "-running")
    history = bh.parse_text_history(Text("x", builder.text()))
    assert history is not None
    timeline = bh.build_timeline(history)
    assert [r.reason for r in timeline.resumes] == [WLAN]
    assert timeline.resumes[0].awake_ms == 1000


def test_history_without_reset_is_flagged(ctx_for):
    text = storm_history().text().replace("RESET:TIME:", "TIME:")
    result = bh.battery_history(ctx_for(live={"batterystats": text}))
    assert result.metrics["has_reset"] is False
    assert [f.id for f in result.findings] == ["battery_history.starts_after_reset"]


def test_plugged_at_is_not_overwritten(ctx_for):
    known = datetime(2026, 1, 15, 9, 0)
    ctx = ctx_for(
        live={"batterystats": storm_history().text()},
        windows=Windows(utc_offset="+0000", plugged_at=known),
    )
    bh.battery_history(ctx)
    assert ctx.windows.plugged_at == known


def test_screen_doze_counts_as_screen_off(ctx_for):
    """Always-on display time is screen off in batterystats, so in the replay too."""
    builder = storm_history()
    builder.add(SPAN_START_MS, "+screen_doze", level=99)
    ctx = ctx_for(live={"batterystats_checkin": builder.checkin()})
    history = bh.battery_history(ctx).metrics
    assert history["screen_off_on_battery_s"] == pytest.approx(3600.0)
    standby = bh.standby_wake(ctx).metrics
    assert standby["screen_doze_s"] == pytest.approx(3600.0)
    assert standby["resumes"] == (HOUR_MS - 7000) // 3000 + 1


def test_charge_sample_takes_the_level_of_its_own_record(ctx_for):
    builder = storm_history()
    builder.add(SPAN_START_MS + 30_000, "charge=2880", level=95)
    ctx = ctx_for(live={"batterystats_checkin": builder.checkin()})
    rows = bh.battery_history(ctx).tables["charge_series"]
    assert next(r for r in rows if r["charge_mah"] == 2880)["level"] == 95
    assert rows[0]["level"] == 100


# ---------------------------------------------------------------------------
# Standby findings and periodicity


def test_wake_storm_findings_fire(ctx_for):
    ctx = ctx_for(live={"batterystats": storm_history().text()})
    result = bh.standby_wake(ctx)
    # One finding owns the wake storm: rate, top reason and per-resume cost.
    [finding] = result.findings
    assert finding.id == "standby_wake.awake_share"
    assert (finding.severity, finding.basis) == ("high", "measured")
    assert finding.window == "screen_off_on_battery"
    assert f"'{WLAN}'" in finding.summary
    assert "Wi-Fi" in finding.summary
    assert "awake a median 1.5 s" in finding.summary
    assert finding.related == []
    assert finding.evidence
    assert finding.evidence[0].ref.startswith("live/batterystats.txt:")
    # Suspend aborts are owned by wakeup_reasons; the metrics stay here.
    assert result.metrics["suspend_aborts_per_resume"] == pytest.approx(1.0)


def test_wake_storm_with_low_awake_share_still_fires(ctx_for):
    ctx = ctx_for(live={"batterystats": storm_history(awake_ms=100).text()})
    result = bh.standby_wake(ctx)
    assert result.metrics["awake_share_pct"] < bh.AWAKE_SHARE_SUSPICIOUS_PCT
    [finding] = result.findings
    assert finding.title.endswith("resumed 1198 times per hour")
    assert finding.severity == "high"


def test_quiet_phone_has_no_standby_findings(ctx_for):
    ctx = ctx_for(live={"batterystats": quiet_history().text()})
    result = bh.standby_wake(ctx)
    assert result.metrics["awake_share_pct"] < bh.AWAKE_SHARE_SUSPICIOUS_PCT
    assert result.findings == []
    with pytest.raises(SkipError, match="screen-off resumes"):
        bh.wake_periodicity(ctx)


def test_periodic_sender_is_found(ctx_for):
    ctx = ctx_for(live={"batterystats": storm_history().text()})
    result = bh.wake_periodicity(ctx)
    assert result.metrics["period_s"] == pytest.approx(3.0, abs=0.01)
    assert result.metrics["harmonics"] == [6.0, 9.0, 12.0]
    [finding] = result.findings
    assert finding.id == "wake_periodicity.periodic_sender"
    assert finding.basis == "inferred"


def test_random_wakes_have_no_period(ctx_for):
    rng = random.Random(7)  # ruff: ignore[suspicious-non-cryptographic-random-usage] - deterministic fixture data
    gaps = [1200 + int(rng.expovariate(1 / 1800)) for _ in range(2000)]
    ctx = ctx_for(live={"batterystats": storm_history(awake_ms=500, gaps=gaps).text()})
    result = bh.wake_periodicity(ctx)
    assert result.metrics["period_s"] is None
    assert result.findings == []


# ---------------------------------------------------------------------------
# Since-charge accounting

CHARGED = dedent(
    """\
    Statistics since last charge:
      System starts: 2, currently on battery: false
      Estimated battery capacity: 2970 mAh
      Last learned battery capacity: 3000 mAh
      Min learned battery capacity: 2990 mAh
      Max learned battery capacity: 3000 mAh
      Time on battery: 4h 0m 0s 0ms (99,5%) realtime, 2h 0m 0s 0ms (50,0%) uptime
      {screen_off_line}
      Time on battery screen doze: 0ms (0,0%)
      Discharge: 600 mAh
      Screen off discharge: {off} mAh
      Screen doze discharge: 0 mAh
      Screen on discharge: {on} mAh
      Device light doze discharge: 0 mAh
      Device deep doze discharge: 210 mAh
      Start clock time: 2026-01-15-08-00-00
      Screen on: 1h 0m 0s 0ms (25,0%) 5x, Interactive: 1h 0m 0s 0ms (25,0%)
      Power save mode enabled: 0ms (0,0%)
      Device full idling: 2h 30m 0s 0ms (62,5%) 3x
      Idle mode full time: 2h 20m 0s 0ms (58,3%) 6x -- longest 50m 0s 0ms
      Connectivity changes: 12

      Device battery use since last full charge
        Amount discharged (lower bound): 20
        Amount discharged (upper bound): 21
        Amount discharged while screen on: 16
        Amount discharged while screen off: {level_off}
        Amount discharged while screen doze: 0

      Estimated power use (mAh):
        Capacity: 3000, Computed drain: 600, actual drain: 600-630
    """,
)


SCREEN_OFF_LINE = (
    "Time on battery screen off: 3h 0m 0s 0ms (75,0%) realtime, "
    "1h 30m 0s 0ms (37,5%) uptime"
)


def charged(off: int = 240, level_off: int = 4, *, comma: bool = True) -> str:
    text = CHARGED.format(
        off=off,
        on=600 - off,
        level_off=level_off,
        screen_off_line=SCREEN_OFF_LINE,
    )
    return text if comma else text.replace(",0%", ".0%").replace(",5%", ".5%")


@pytest.mark.parametrize("comma", [True, False])
def test_discharge_accounting_parses_both_decimal_styles(ctx_for, comma):
    ctx = ctx_for(live={"batterystats_charged": charged(comma=comma)})
    result = bh.discharge_accounting(ctx)
    m = result.metrics
    assert m["on_battery_s"] == pytest.approx(14400.0)
    assert m["screen_off_s"] == pytest.approx(10800.0)
    assert m["screen_on_s"] == pytest.approx(3600.0)
    assert m["screen_off_awake_share_pct"] == pytest.approx(50.0)
    assert m["discharge_mah_per_h"] == pytest.approx(150.0)
    assert m["screen_off_mah_per_h"] == pytest.approx(80.0)
    assert m["screen_on_mah_per_h"] == pytest.approx(360.0)
    # 210 mAh over 'Idle mode full time' (2h20m), not 'Device full idling'.
    assert m["deep_doze_mah_per_h"] == pytest.approx(90.0)
    assert m["screen_off_pct_per_h"] == pytest.approx(2.67)
    assert m["gauge_step_mah"] == pytest.approx(30.0)
    assert m["actual_drain_high_mah"] == pytest.approx(630.0)
    ids = {f.id: f for f in result.findings}
    assert ids["discharge_accounting.standby_drain"].severity == "high"
    assert "discharge_accounting.level_hides_idle_drain" in ids


def test_decimal_mah_and_doze_inside_screen_off(ctx_for):
    """Values under 100 mAh print with decimals; doze is part of screen off."""
    text = (
        charged()
        .replace("Discharge: 600 mAh", "Discharge: 84.7 mAh")
        .replace("Screen off discharge: 240 mAh", "Screen off discharge: 56.5 mAh")
        .replace("Screen on discharge: 360 mAh", "Screen on discharge: 28.2 mAh")
        .replace(
            "Time on battery screen doze: 0ms (0,0%)",
            "Time on battery screen doze: 3h 0m 0s 0ms (75,0%)",
        )
    )
    m = bh.discharge_accounting(ctx_for(live={"batterystats_charged": text})).metrics
    assert (m["discharge_mah"], m["screen_off_mah"]) == pytest.approx((84.7, 56.5))
    assert m["screen_on_mah"] == pytest.approx(28.2)
    assert m["screen_on_s"] == pytest.approx(3600.0)


def test_checkin_screen_on_charge_keeps_doze_in_screen_off(ctx_for):
    checkin = CHECKIN_CURRENT.replace(
        "9,0,l,dc,20,21,16,4,600,240,0,0,0,210",
        "9,0,l,dc,20,21,16,4,600,240,3,200,0,210",
    )
    m = bh.discharge_accounting(ctx_for(live={"batterystats_checkin": checkin})).metrics
    assert m["screen_on_mah"] == pytest.approx(360.0)
    assert m["screen_doze_mah"] == pytest.approx(200.0)


def test_level_skew_without_screen_on_level(ctx_for):
    text = charged().replace("    Amount discharged while screen on: 16\n", "")
    result = bh.discharge_accounting(ctx_for(live={"batterystats_charged": text}))
    skew = next(f for f in result.findings if f.id.endswith("level_hides_idle_drain"))
    assert "with it on" not in skew.summary
    assert skew.metrics["level_screen_on"] is None


def test_low_screen_off_drain_has_no_findings(ctx_for):
    ctx = ctx_for(live={"batterystats_charged": charged(off=30, level_off=1)})
    result = bh.discharge_accounting(ctx)
    assert result.metrics["screen_off_pct_per_h"] == pytest.approx(0.33)
    assert result.findings == []


CHECKIN_CURRENT = dedent(
    """\
    9,0,i,vers,36,215,TEST.1,TEST.2
    9,0,l,bt,0,14400000,7200000,14500000,7300000,1768464000000,10800000,5400000,2970,2990000,3000000,0
    9,0,l,dc,20,21,16,4,600,240,0,0,0,210
    9,0,l,m,3600000,0,0,0,0,0,3600000,0,12,8400000,6,9000000,3,0,0,0,0,0,0,0,3000000
    9,0,l,pws,3000,600,600,630
    """,
)


def test_discharge_accounting_from_checkin_rows(ctx_for):
    ctx = ctx_for(live={"batterystats_checkin": CHECKIN_CURRENT})
    m = bh.discharge_accounting(ctx).metrics
    assert m["source"] == "live/batterystats_checkin.txt"
    assert m["screen_off_mah_per_h"] == pytest.approx(80.0)
    assert m["screen_on_mah"] == pytest.approx(360.0)
    assert m["deep_doze_mah_per_h"] == pytest.approx(90.0)
    assert m["learned_capacity_mah"] == pytest.approx(3000.0)


# ---------------------------------------------------------------------------
# Capacity and gauge

HEALTH_HAL = dedent(
    """\
    ac: 0 usb: 1 wireless: 0 current_max: 500000 voltage_max: 5000000
    status: 2 health: 2 present: 1
    level: 84 voltage: 4300 temp: 290
    current now: 500000
    charge counter: {counter}
    cycle count: 412
    Full charge: {full}

    getHealthInfo -> {{.legacy = {{.batteryHealth = GOOD, .batteryCycleCount = 412, \
    .batteryFullCharge = {full}}}, .batteryFullChargeDesignCapacityUah = 3000000}}
    """,
)
HAL_MEMBER = "lshal-debug/android.hardware.health@2.1__IHealth_default.txt"


def test_worn_battery_is_flagged(ctx_for):
    hal = HEALTH_HAL.format(full=2160000, counter=1771200)
    ctx = ctx_for(live={"getprop": ""}, members={HAL_MEMBER: hal})
    result = bh.battery_capacity(ctx)
    m = result.metrics
    assert m["learned_capacity_mah"] == pytest.approx(2160.0)
    assert m["design_capacity_mah"] == pytest.approx(3000.0)
    assert m["state_of_health_pct"] == pytest.approx(72.0)
    assert m["cycle_count"] == 412
    assert m["hal_health"] == "GOOD"
    [finding] = result.findings
    assert finding.id == "battery_capacity.worn"
    assert finding.severity == "medium"


def test_power_profile_design_wins_and_healthy_battery_passes(ctx_for):
    hal = HEALTH_HAL.format(full=2900000, counter=2436000)
    ctx = ctx_for(
        live={"power_profile": "Power Profile:\n    battery.capacity=3100.0\n"},
        members={HAL_MEMBER: hal},
    )
    result = bh.battery_capacity(ctx)
    assert result.metrics["design_source"] == "power profile battery.capacity"
    assert result.metrics["state_of_health_pct"] == pytest.approx(93.5)
    assert result.findings == []


def test_gauge_counter_in_whole_percent_steps(ctx_for):
    ctx = ctx_for(
        live={
            "batterystats": storm_history().text(),
            "batterystats_charged": charged(),
        },
    )
    ctx.results["discharge_accounting"] = bh.discharge_accounting(ctx)
    result = bh.gauge_quantization(ctx)
    m = result.metrics
    assert m["soc_derived_counter"] is True
    assert m["step_mah"] == pytest.approx(30.0)
    assert m["min_screen_off_test_h"] == pytest.approx(1.5)
    assert m["clean_window_mah_per_h"] == pytest.approx(180.0)
    assert [f.id for f in result.findings] == ["gauge_quantization.soc_steps"]


def test_coulomb_counter_is_not_called_quantized(ctx_for):
    text = storm_history().text()
    for p in range(93, 99):
        whole = 3000 * p // 100
        text = text.replace(f"charge={whole}", f"charge={whole - 7}")
    ctx = ctx_for(live={"batterystats": text, "batterystats_charged": charged()})
    result = bh.gauge_quantization(ctx)
    assert result.metrics["soc_derived_counter"] is False
    assert result.findings == []


# ---------------------------------------------------------------------------
# Daily steps and shutdowns

DAILY = dedent(
    """\
    Daily stats:
      Current start time: 2026-01-15-03-00-00
      Next min deadline: 2026-01-16-01-00-00
      Current daily discharge step durations:
        #0: +5m0s0ms to 90 (screen-on, power-save-off, device-idle-off)
          Discharge total time: 8h 20m 0s 0ms  (from 1 steps)
      Daily from 2026-01-14-03-00-00 to 2026-01-15-03-00-00:
        Discharge step durations:
          #0: +30s0ms to 2 (screen-on)
          #1: +20s0ms to 3 (screen-on)
          #2: +15s0ms to 4 (screen-on)
          #3: +10m0s0ms to 5 (screen-on)
          #4: +12m0s0ms to 6 (screen-off, device-idle-on)
            Discharge total time: 20h 0m 0s 0ms  (from 5 steps)
            Discharge screen off device idle time: {idle1}  (from 1 steps)
        Charge step durations:
          #0: +3m0s0ms to 50
            Charge total time: 5h 0m 0s 0ms  (from 1 steps)
        Package changes:
          Update com.example.app vers=2
      Daily from 2026-01-13-03-00-00 to 2026-01-14-03-00-00:
        Discharge step durations:
          #0: +20m0s0ms to 40 (screen-off, device-idle-on)
          #1: +20m0s0ms to 41 (screen-off, device-idle-on)
            Discharge total time: 1d 9h 20m 0s 0ms  (from 2 steps)
            Discharge screen off device idle time: {idle2}  (from 2 steps)

    Statistics since last charge:
    """,
)


def daily(idle1: str = "1d 2h 0m 0s 0ms", idle2: str = "1d 9h 20m 0s 0ms") -> str:
    return DAILY.format(idle1=idle1, idle2=idle2)


def test_daily_steps_findings(ctx_for):
    ctx = ctx_for(
        live={"batterystats": daily(), "batterystats_charged": charged()},
    )
    result = bh.daily_steps(ctx)
    m = result.metrics
    assert m["days"] == 2
    assert m["discharge_steps"] == 7
    assert m["median_total_h"] == pytest.approx(26.67, abs=0.01)
    assert m["median_screen_off_idle_h"] == pytest.approx(29.67, abs=0.01)
    assert m["median_screen_off_idle_mah_per_h"] == pytest.approx(101.1, abs=0.1)
    assert m["fast_low_steps"] == 3
    assert m["deep_discharge_days"] == 1
    assert "current_day_screen_off_idle_h" not in m
    rows = result.tables["days"]
    assert rows[0]["min_level"] == 2
    ids = {f.id: f for f in result.findings}
    assert ids["daily_steps.idle_drain"].severity == "high"
    assert ids["daily_steps.low_level_collapse"].basis == "inferred"


def test_daily_steps_slow_idle_drain_has_no_idle_finding(ctx_for):
    text = daily(idle1="8d 0h 0m 0s 0ms", idle2="9d 0h 0m 0s 0ms")
    result = bh.daily_steps(ctx_for(live={"batterystats": text}))
    assert "daily_steps.idle_drain" not in {f.id for f in result.findings}


GETPROP = dedent(
    """\
    [persist.sys.boot.reason]: []
    [persist.sys.boot.reason.history]: [reboot,userrequested,1768471200
    shutdown,battery,1768380000
    shutdown,battery,1768379800]
    [ro.boot.bootreason]: [reboot,userrequested]
    [sys.boot.reason.last]: [reboot,userrequested]
    """,
)


def test_low_battery_shutdowns_join_multiline_getprop(ctx_for):
    ctx = ctx_for(live={"getprop": GETPROP, "batterystats": daily()})
    ctx.results["daily_steps"] = bh.daily_steps(ctx)
    result = bh.low_battery_shutdowns(ctx)
    m = result.metrics
    assert m["boot_history_entries"] == 3
    assert m["battery_shutdowns"] == 2
    assert m["ro_boot_bootreason"] == "reboot,userrequested"
    times = [row["time"] for row in result.tables["boots"]]
    expected = datetime.fromtimestamp(1768380000, tz=UTC).replace(tzinfo=None)
    assert times[1] == expected.isoformat(sep=" ")
    [finding] = result.findings
    assert finding.id == "low_battery_shutdowns.battery_shutdowns"
    assert finding.severity == "medium"
    assert finding.evidence[0].ref == "live/getprop.txt:2"
    # The shutdown owns the collapse it cites; daily_steps links back.
    collapse = next(
        f
        for f in ctx.results["daily_steps"].findings
        if f.id == "daily_steps.low_level_collapse"
    )
    assert finding.related == [collapse.id]
    assert collapse.related == [finding.id]


def test_no_battery_shutdowns_no_finding(ctx_for):
    getprop = "[persist.sys.boot.reason.history]: [reboot,userrequested,1768471200]\n"
    result = bh.low_battery_shutdowns(ctx_for(live={"getprop": getprop}))
    assert result.metrics["battery_shutdowns"] == 0
    assert result.findings == []


def test_crash_and_forced_reboots_are_unexpected(ctx_for):
    getprop = dedent(
        """\
        [persist.sys.boot.reason.history]: [reboot,longkey,1768471200
        kernel_panic,1768380000
        reboot,userrequested,1768300000]
        """,
    )
    result = bh.low_battery_shutdowns(ctx_for(live={"getprop": getprop}))
    kinds = [row["kind"] for row in result.tables["boots"]]
    assert kinds == ["forced", "crash", "requested"]
    [finding] = result.findings
    assert finding.id == "low_battery_shutdowns.unexpected_reboots"
    assert finding.metrics == {"unexpected": 2}


# ---------------------------------------------------------------------------
# Battery saver drain stats and the previous period

DRAIN_ROWS = (
    ("NonDoze NonIntr", "10m 20mAh(  1%) 120,0mAh/h", "30m 40mAh(  2%) 80,0mAh/h"),
    ("Intr", "60m 300mAh( 10%) 300,0mAh/h", "0m 0mAh(  0%) 0,0mAh/h"),
    ("Deep    NonIntr", "120m 100mAh(  3%) 50,0mAh/h", "0m 0mAh(  0%) 0,0mAh/h"),
    ("Intr", "0m 5mAh(  0%) 9999,0mAh/h", "0m 0mAh(  0%) 0,0mAh/h"),
    ("Light   NonIntr", "0m 0mAh(  0%) 0,0mAh/h", "0m 0mAh(  0%) 0,0mAh/h"),
    ("Intr", "0m 0mAh(  0%) 0,0mAh/h", "0m 0mAh(  0%) 0,0mAh/h"),
)
POWER = "\n".join(
    [
        "Battery saving stats:",
        "  Battery Saver is currently: OFF",
        "    Times full enabled: 2",
        "",
        "  Drain stats:",
        "                     Battery saver OFF                          ON",
        *(f"  {label:>15}:    {off}        {on}" for label, off, on in DRAIN_ROWS),
        "",
        "Battery saver policy (*NOTE* they only apply when battery saver is ON):",
    ],
)


@pytest.mark.parametrize("comma", [True, False])
def test_battery_saver_drain_stats(ctx_for, comma):
    power = POWER if comma else POWER.replace(",0mAh/h", ".0mAh/h")
    ctx = ctx_for(
        live={"power": power, "batterystats_charged": charged()},
        windows=Windows(
            utc_offset="+0000",
            boot_time=datetime(2026, 1, 15, 2, 0),
            since_charge_start=datetime(2026, 1, 15, 8, 0),
        ),
    )
    ctx.results["discharge_accounting"] = bh.discharge_accounting(ctx)
    result = bh.battery_saver_drain(ctx)
    m = result.metrics
    assert m["minutes"] == 220
    assert m["mah"] == 465
    assert m["saver_currently"] == "OFF"
    assert m["times_full_enabled"] == 2
    assert result.tables["drain"][0] == {
        "doze": "NonDoze",
        "interactive": True,
        "saver": "off",
        "minutes": 60,
        "mah": 300,
        "level_pct": 10,
        "mah_per_h": 300.0,
        "ref": "live/power.txt:8",
    }
    tiny = next(r for r in result.tables["drain"] if r["mah"] == 5)
    assert tiny["mah_per_h"] is None
    assert not any("unparsable" in note for note in result.notes)
    assert "before_charge_mah" not in m  # since-charge (240 min) > since-boot


PREVIOUS = dedent(
    """\
    9,0,i,vers,36,215,TEST.1,TEST.2
    9,0,l,bt,2,36000000,32400000,72000000,60000000,1768300000000,32400000,29160000,2400,2950000,3000000,0
    9,0,l,dc,80,82,20,60,2400,1800,0,0,0,1900
    9,0,l,m,3600000,0,100000,7200000,21600000,0,3600000,36000000,900,30000000,20,31000000,12,700,0,0,0,0,0,0,3000000
    9,0,l,pws,3000,2400,2400,2460
    9,0,l,pwi,cell,900,0,0,0
    9,0,l,pwi,scrn,300,1,0,0
    9,10101,l,pwi,uid,400,0,0,0
    9,0,l,kwl,"PowerManager.SuspendLockout",7200000,1,-1,-1
    9,0,l,kwl,"example_ws",60000,30,-1,-1
    9,0,l,wr,"Abort: Pending Wakeup Sources: example_ws",5000,20
    9,0,l,wst,0,0,0,20000000,16000000,0,0,0
    """,
)


def test_previous_cycle_summary_and_findings(context_factory):
    ctx = context_factory(
        live={
            "batterystats_checkin_previous": PREVIOUS,
            "batterystats_charged": charged(),
        },
        packages="package:com.example.vpn uid:10101\n",
        windows=Windows(utc_offset="+0000", since_charge_start=RESET_LOCAL),
    )
    ctx.results["discharge_accounting"] = bh.discharge_accounting(ctx)
    result = bh.previous_cycle(ctx)
    m = result.metrics
    assert m["on_battery_s"] == pytest.approx(36000.0)
    assert m["screen_off_mah_per_h"] == pytest.approx(200.0)
    assert m["screen_off_awake_share_pct"] == pytest.approx(90.0)
    assert m["screen_off_rate_vs_current"] == pytest.approx(2.5)
    assert m["mobile_radio_share_pct"] == pytest.approx(60.0)
    assert m["min_learned_mah"] == pytest.approx(2950.0)
    assert m["wifi_on_disconnected_s"] == pytest.approx(20000.0)
    assert m["period_start_estimate"] == "2026-01-14 12:00:00"
    assert result.tables["power_uids"][0]["name"] == "com.example.vpn"
    assert result.tables["kernel_wakelocks"][0]["name"] == "PowerManager.SuspendLockout"
    ids = {f.id: f for f in result.findings}
    assert set(ids) == {
        "previous_cycle.heavier_period",
        "previous_cycle.mobile_radio_busy",
        "previous_cycle.suspend_blocked",
    }
    assert ids["previous_cycle.suspend_blocked"].severity == "high"
    assert ids["previous_cycle.suspend_blocked"].related == [
        "wakelocks.suspend_lockout_since_boot",
    ]
    assert any("inconsistent" in note for note in result.notes)


# ---------------------------------------------------------------------------
# Missing inputs


@pytest.mark.parametrize(
    "func",
    [
        bh.battery_history,
        bh.standby_wake,
        bh.wake_periodicity,
        bh.discharge_accounting,
        bh.battery_capacity,
        bh.gauge_quantization,
        bh.daily_steps,
        bh.low_battery_shutdowns,
        bh.battery_saver_drain,
        bh.previous_cycle,
    ],
)
def test_missing_inputs_skip(ctx_for, func):
    ctx = ctx_for(live={"battery": "  level: 50\n"})
    with pytest.raises(SkipError):
        func(ctx)


def test_unrelated_text_skips(ctx_for):
    ctx = ctx_for(
        live={
            "batterystats": "Per-PID Stats:\n",
            "power": "Wake Locks: size=0\n",
            "batterystats_checkin": "9,0,i,vers,36,215,TEST.1,TEST.2\n",
        },
    )
    for func in (bh.battery_history, bh.daily_steps, bh.battery_saver_drain):
        with pytest.raises(SkipError):
            func(ctx)
