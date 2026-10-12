"""Tests for the since-charge batterystats analyzers in battery_summary.

The dumps in tests/fixtures/battery_summary/ are invented. They follow the
layout of Android 15 dumps with a decimal-comma locale: percentages use
commas, power-model mAh values use dots.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from textwrap import dedent

import pytest
from androiddiag.battery_summary import (
    alarms_jobs,
    power_model,
    power_profile,
    wakelocks,
    wakeup_reasons,
    wifi_multicast,
)
from androiddiag.model import Finding, Result, SkipError, Windows

FIXTURES = Path(__file__).parent / "fixtures" / "battery_summary"

BUSY = {
    "partial": "20m 0s 0ms",
    "mc_total": "4h 30m 0s 0ms",
    "mc_a": "4h 0m 0s 0ms",
    "mc_b": "30m 0s 0ms",
    "cpu": "100",
    "wakelock_mah": "0.200",
    "uid0": "40.0",
    "uid1000": "30.0",
    "bg_total": "30.0",
    "netlink": "60000",
    "lockout": "15m 0s 0ms",
    "partial_uid": "14m 0s 0ms",
    "actual_ms": "900000",
    "actual_dur": "15m 0s 0ms",
    "aborts": "5000",
    "resumes": "5000",
    "job_dur": "15m 0s 0ms",
    "job_runs": "20",
    "alarms": "60",
}

CALM = {
    **BUSY,
    "partial": "1h 0m 0s 0ms",
    "mc_total": "30m 0s 0ms",
    "mc_a": "20m 0s 0ms",
    "mc_b": "10m 0s 0ms",
    "cpu": "340",
    "wakelock_mah": "40.0",
    "uid0": "10.0",
    "uid1000": "5.0",
    "bg_total": "1.00",
    "netlink": "1000",
    "lockout": "2s 0ms",
    "partial_uid": "50s 0ms",
    "actual_ms": "60000",
    "actual_dur": "1m 0s 0ms",
    "aborts": "10",
    "resumes": "200",
    "job_dur": "10s 0ms",
    "job_runs": "3",
    "alarms": "5",
}

PACKAGES = dedent(
    """\
    package:com.example.viewer uid:10101
    package:com.example.sync uid:10102
    package:android uid:1000
    """,
)

WINDOWS = Windows(
    dump_time=datetime(2026, 1, 15, 12, 0),
    boot_time=datetime(2026, 1, 15, 2, 0),
    since_charge_start=datetime(2026, 1, 15, 7, 0),
    on_battery_at_capture=False,
)


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


def charged(values: dict[str, str]) -> str:
    return fixture("charged").format(**values)


def ids(result: Result) -> dict[str, str]:
    return {f.id: f.severity for f in result.findings}


def pick(metrics: dict, keys: dict) -> dict:
    return {k: metrics[k] for k in keys}


@pytest.fixture
def busy(context_factory):
    return context_factory(
        live={
            "batterystats_charged": charged(BUSY),
            "wifi": fixture("wifi"),
            "network_stack": fixture("network_stack"),
            "power": "  mUseAutoSuspend=true\n  mHalAutoSuspendModeEnabled=false\n",
            "alarm": fixture("alarm"),
            "jobscheduler": fixture("jobscheduler"),
            "power_profile": fixture("power_profile"),
        },
        packages=PACKAGES,
        windows=WINDOWS,
        services={"suspend_control_internal": fixture("suspend_control")},
    )


@pytest.fixture
def calm(context_factory):
    return context_factory(
        live={"batterystats_charged": charged(CALM), "wifi": fixture("wifi")},
        packages=PACKAGES,
        windows=WINDOWS,
    )


def test_wakeup_reasons_counts_resumes_and_aborts(busy):
    result = wakeup_reasons(busy)
    expected = {
        "resumes": 5080,
        "aborts": 5015,
        "reason_lines": 6,
        "reason_lines_without_counts": 1,
        "abort_to_resume_ratio": 0.99,
        "resumes_per_h": 1016.0,
        "on_battery_uptime_h": 3.0,
        "awake_after_aborts_s": 3960.0,
        "awake_after_aborts_pct_of_uptime": 36.7,
    }
    assert pick(result.metrics, expected) == pytest.approx(expected)
    assert result.metrics["top_resume_reason"] == "41 WLAN_EXAMPLE"
    sources = {r["source"]: r["aborts"] for r in result.tables["abort_sources"]}
    assert sources == {"NETLINK": 5000, "alarmtimer": 8, "Disabling non-boot cpus": 7}
    assert result.tables["abort_kinds"][0]["kind"] == "pending_wakeup_sources"
    assert result.tables["reasons"][0]["ref"].startswith(
        "live/batterystats_charged.txt:",
    )


def test_wakeup_reasons_findings_fire(busy):
    result = wakeup_reasons(busy)
    # The resume rate is a metric here; standby_wake.awake_share owns the finding.
    assert ids(result) == {"wakeup_reasons.suspend_aborts": "medium"}
    assert result.metrics["resumes_per_h"] == pytest.approx(1016.0)
    aborts = result.findings[0]
    assert "once per real resume" in aborts.summary
    assert (aborts.basis, aborts.window) == ("measured", "on_battery")
    assert aborts.evidence
    assert all(e.ref.startswith("live/") for e in aborts.evidence)
    # suspend_stats and kernel_suspend emit no finding of their own for this.
    assert aborts.related == []


def test_suspend_aborts_cite_other_windows(busy):
    busy.results["suspend_stats"] = Result(
        "suspend_stats",
        metrics={"fail_share_pct": 61.5},
    )
    busy.results["kernel_suspend"] = Result(
        "kernel_suspend",
        metrics={"aborts_per_deep_resume": 1.75},
    )
    result = wakeup_reasons(busy)
    assert result.metrics["since_boot_failed_suspend_pct"] == pytest.approx(61.5)
    assert result.metrics["log_sample_aborts_per_resume"] == pytest.approx(1.75)
    summary = result.findings[0].summary
    assert "61.5% of suspend attempts as failed" in summary
    assert "1.75 aborts per real resume" in summary


def test_wakeup_reasons_high_ratio(context_factory):
    ctx = context_factory(
        live={"batterystats_charged": charged({**BUSY, "aborts": "9000"})},
    )
    result = wakeup_reasons(ctx)
    assert ids(result)["wakeup_reasons.suspend_aborts"] == "high"
    assert "once per real resume" not in result.findings[0].summary


def test_wakeup_reasons_calm_has_no_findings(calm):
    result = wakeup_reasons(calm)
    assert result.metrics["resumes_per_h"] == pytest.approx(56.0)
    assert result.findings == []


def test_wakeup_reasons_checkin_cross_check(context_factory):
    checkin = dedent(
        """\
        9,0,l,wr,"41 WLAN_EXAMPLE",2400000,4990
        9,0,l,wr,"Abort: Pending Wakeup Sources: NETLINK NETLINK",3600000,5000
        9,0,l,kwl,"NETLINK",600000,60000,-1,-1
        """,
    )
    ctx = context_factory(
        live={"batterystats_charged": charged(BUSY)},
        sections={"CHECKIN BATTERYSTATS (dumpsys batterystats -c)": checkin},
    )
    result = wakeup_reasons(ctx)
    assert result.metrics["checkin_resumes"] == 4990
    assert result.metrics["checkin_aborts"] == 5000
    assert any("Checkin 'wr' rows" in note for note in result.notes)


def test_wakeup_reasons_uses_the_full_dump(context_factory):
    history = "Battery History (1% used):\n  0 (9) RESET:TIME: 2026-01-15-07-00-00\n\n"
    ctx = context_factory(live={"batterystats": history + charged(BUSY)})
    result = wakeup_reasons(ctx)
    assert result.metrics["resumes"] == 5080
    assert result.tables["reasons"][0]["ref"].startswith("live/batterystats.txt:")


def test_wakeup_reasons_skip(context_factory):
    with pytest.raises(SkipError):
        wakeup_reasons(context_factory(live={"battery": "  level: 50"}))
    no_reasons = "\n".join(
        line for line in charged(BUSY).splitlines() if "Wakeup reason" not in line
    )
    with pytest.raises(SkipError, match="wakeup reasons"):
        wakeup_reasons(context_factory(live={"batterystats_charged": no_reasons}))


def test_wakelocks_busy(busy):
    busy.results["wakeup_reasons"] = wakeup_reasons(busy)
    result = wakelocks(busy)
    expected = {
        "kernel_wakelocks": 4,
        "partial_wakelocks": 2,
        "partial_wakelock_total_s": 1200.0,
        "partial_pct_of_screen_off_awake": 16.7,
        "kernel_only_awake_screen_off_s": 6000.0,
        "screen_off_awake_pct": 50.0,
        "suspend_lockout_screen_off_s": 900.0,
        "suspend_lockout_since_boot_max_s": 7200.0,
    }
    assert pick(result.metrics, expected) == pytest.approx(expected)
    assert result.metrics["use_auto_suspend"] is True
    assert result.metrics["hal_auto_suspend_mode_enabled"] is False
    assert not any("could not be parsed" in note for note in result.notes)
    kernel = {r["wakeup_source"]: r for r in result.tables["kernel_wakelocks"]}
    assert kernel["NETLINK"]["per_resume"] == pytest.approx(11.8)
    assert "" in kernel  # a wakeup source with an empty name is still counted
    top = result.tables["uid_wake_totals"][0]
    assert top["package"] == "com.example.sync"
    assert top["actual_partial_s"] == pytest.approx(900.0)
    assert result.tables["partial_wakelocks"][0]["tag"] == "SyncWorker: Example"
    assert ids(result) == {
        "wakelocks.heavy_partial_wakelocks": "medium",
        "wakelocks.per_resume_churn": "low",
        "wakelocks.suspend_lockout_screen_off": "high",
        "wakelocks.suspend_lockout_since_boot": "low",
    }
    lockout = next(f for f in result.findings if "screen_off" in f.id)
    assert lockout.window == "screen_off_on_battery"


def test_wakelocks_per_resume_uses_screen_off_resumes(busy):
    busy.results["standby_wake"] = Result("standby_wake", metrics={"resumes": 4000})
    result = wakelocks(busy)
    assert result.metrics["screen_off_resumes"] == 4000
    kernel = {r["wakeup_source"]: r for r in result.tables["kernel_wakelocks"]}
    assert kernel["NETLINK"]["per_resume"] == pytest.approx(15.0)
    churn = next(f for f in result.findings if f.id.endswith("per_resume_churn"))
    assert "4,000 screen-off resumes" in churn.summary


def test_previous_period_lockout_is_not_reported_twice(busy):
    previous = Result("previous_cycle")
    previous.findings.append(
        Finding(
            id="previous_cycle.suspend_blocked",
            title="",
            symptom="battery",
            severity="high",
            basis="measured",
            window="previous_charge",
            summary="",
        ),
    )
    busy.results["previous_cycle"] = previous
    text = charged({**BUSY, "lockout": "2s 0ms"})
    busy.sources.workdir.live_dir.joinpath("batterystats_charged.txt").write_text(text)
    result = wakelocks(busy)
    assert "wakelocks.suspend_lockout_since_boot" not in ids(result)
    assert result.metrics["suspend_lockout_since_boot_max_s"] == pytest.approx(7200.0)
    assert any("previous_cycle.suspend_blocked" in note for note in result.notes)


def test_wakelocks_calm(calm):
    result = wakelocks(calm)
    assert result.metrics["partial_pct_of_screen_off_awake"] == pytest.approx(50.0)
    assert result.metrics["resumes"] == 280  # reparsed: no wakeup_reasons result
    assert result.findings == []


def test_wakelocks_skip(context_factory):
    with pytest.raises(SkipError):
        wakelocks(context_factory(live={"battery": "  level: 50"}))


def test_wifi_multicast_busy(busy):
    result = wifi_multicast(busy)
    expected = {
        "multicast_total_s": 16200.0,
        "multicast_pct_of_battery": 90.0,
        "top_uid_pct_of_battery": 80.0,
        "locks_held_at_capture": 1,
        "fw_multicast_broadcast_pct": 20.0,
        "apf_mcast_allow_in_doze": 1,
        "apf_mcast_allow_in_doze_since_charge": 1,
    }
    assert pick(result.metrics, expected) == pytest.approx(expected)
    assert result.metrics["top_package"] == "com.example.sync"
    assert result.metrics["apf_current_mcast"] == "ALLOW"
    dtim = {r["multiplier"]: r["count"] for r in result.tables["dtim_multiplier"]}
    assert dtim == {1: 1, 9: 1}
    assert result.tables["locks_held"][0]["tag"] == "ExampleMdnsLock"
    assert ids(result) == {"wifi_multicast.lock_held": "medium"}
    assert "mcast: ALLOW, doze: TRUE" in result.findings[0].summary


def test_wifi_multicast_calm(calm):
    result = wifi_multicast(calm)
    assert result.metrics["multicast_pct_of_battery"] == pytest.approx(10.0)
    assert result.findings == []


def test_wifi_multicast_without_batterystats(context_factory):
    result = wifi_multicast(context_factory(live={"wifi": fixture("wifi")}))
    assert result.metrics["locks_held_at_capture"] == 1
    assert result.findings == []
    with pytest.raises(SkipError):
        wifi_multicast(context_factory(live={"battery": "  level: 50"}))


def test_power_model_busy(busy):
    result = power_model(busy)
    expected = {
        "modelled_mah": 205.5,
        "attributed_mah": 190.0,
        "unmodelled_mah": 294.5,
        "unmodelled_pct": 58.9,
        "unmodelled_ma_per_awake_h": 98.2,
        "awake_idle_model_ma": 0.1,
        "uid0_wakelock_s": 6600.0,
    }
    assert pick(result.metrics, expected) == pytest.approx(expected)
    assert result.metrics["computed_equals_discharge"] is True
    top = result.tables["uids"][0]
    assert top["package"] == "com.example.viewer"
    assert (top["screen_mah"], top["bg_mah"]) == pytest.approx((80.0, 1.0))
    assert any("'Computed drain' equals" in note for note in result.notes)
    assert ids(result) == {
        "power_model.unmodelled_drain": "medium",
        "power_model.system_uids_dominate": "low",
        "power_model.app_background_power": "medium",
    }
    unmodelled = result.findings[0]
    assert unmodelled.basis == "modelled"
    # power_profile.standby_unpriced owns the 0 mA awake pricing.
    assert "0.1 mA" not in unmodelled.summary
    assert unmodelled.related == ["power_profile.standby_unpriced"]


def test_power_model_calm(calm):
    result = power_model(calm)
    assert result.metrics["unmodelled_pct"] == pytest.approx(2.9)
    assert result.findings == []


def test_power_model_decimal_comma(context_factory):
    text = (
        charged(BUSY)
        .replace("cpu: 100 apps: 100", "cpu: 100,5 apps: 100,5")
        .replace("UID u0a101: 90.0 fg: 4.00", "UID u0a101: 90,5 fg: 4,25")
        .replace("cpu=10.0 cpu:fg", "cpu=10,5 cpu:fg")
    )
    result = power_model(context_factory(live={"batterystats_charged": text}))
    assert result.metrics["modelled_mah"] == pytest.approx(206.0)
    row = next(r for r in result.tables["uids"] if r["uid"] == "u0a101")
    got = (row["total_mah"], row["fg_mah"], row["cpu_mah"])
    assert got == pytest.approx((90.5, 4.25, 10.5))


def test_power_model_legacy_format(context_factory):
    legacy = dedent(
        """\
        Statistics since last charge:
          Time on battery: 2h 0m 0s 0ms (99.0%) realtime, 1h 0m 0s 0ms (50.0%) uptime
          Discharge: 100 mAh

          Estimated power use (mAh):
            Capacity: 3000, Computed drain: 70.0, actual drain: 100-110
            Uid u0a101: 40.0 ( cpu=30.0 wake=10.0 ) Including smearing: 45.0
            Screen: 30.0 Excluded from smearing
            Over-counted: 0 ( ) Excluded from smearing
            Unaccounted: 30.0 ( ) Excluded from smearing

        """,
    )
    result = power_model(context_factory(live={"batterystats_charged": legacy}))
    expected = {"modelled_mah": 70.0, "unmodelled_pct": 30.0}
    assert pick(result.metrics, expected) == pytest.approx(expected)
    assert {r["component"] for r in result.tables["components"]} == {
        "Screen",
        "Over-counted",
        "Unaccounted",
    }
    assert "power_model.unmodelled_drain" in ids(result)


# Samsung prints Rated and Typical capacities in the power model header.
CAPACITY_LINE = (
    "Capacity: 5000, Rated: 4900, Typical: 5000, Computed drain: 90.0, "
    "actual drain: 50.0-100"
)
POWER_STATES = dedent(
    """\
    Statistics since last charge:
      Time on battery: 2h 0m 0s 0ms (50,0%) realtime, 1h 0m 0s 0ms (25,0%) uptime
      Discharge: 84.7 mAh

      Estimated power use (mAh):
        {capacity}
        Global
        screen: 30.0 apps: 30.0 duration: 30m 0s 0ms
        cpu: 60.0 apps: 60.0 duration: 2h 0m 0s 0ms
          (on battery, screen on)
          screen: 10.0 apps: 10.0
          cpu: 5.00 apps: 5.00 duration: 10m 0s 0ms
          (on battery, screen off/doze)
          cpu: 40.0 apps: 40.0 duration: 1h 30m 0s 0ms
          (not on battery, screen on)
          screen: 20.0 apps: 20.0
          cpu: 10.0 apps: 10.0 duration: 20m 0s 0ms
          (not on battery, screen off/doze)
          cpu: 5.00 apps: 5.00
      UID u0a101: 70.0 bg: 70.0
          screen=30.0 cpu=40.0 cpu:bg=40.0
          (on battery, screen on) screen=10.0 cpu=4.00
          (on battery, screen off/doze) cpu=30.0
          (not on battery, screen on) screen=20.0 cpu=5.00
          (not on battery, screen off/doze) cpu=1.00
      UID 1000: 20.0
          cpu=20.0
          (on battery, screen off/doze) cpu=11.0
          (not on battery, screen on) cpu=9.00

    """,
).format(capacity=CAPACITY_LINE)


def test_power_model_per_state_blocks_count_only_on_battery(context_factory):
    """Android 15+ state sub-blocks: Global lines include time on the charger."""
    ctx = context_factory(
        live={"batterystats_charged": POWER_STATES},
        packages=PACKAGES,
    )
    result = power_model(ctx)
    expected = {
        "discharge_mah": 84.7,  # decimal mAh below 100
        "capacity_mah": 5000.0,  # Samsung-style header with Rated and Typical
        "computed_drain_mah": 90.0,
        "modelled_mah": 55.0,
        "attributed_mah": 55.0,
        "unmodelled_pct": 35.1,
    }
    assert pick(result.metrics, expected) == pytest.approx(expected)
    components = {r["component"]: r for r in result.tables["components"]}
    assert components["cpu"]["mah"] == pytest.approx(45.0)
    assert components["cpu"]["duration_s"] == pytest.approx(6000.0)
    top = result.tables["uids"][0]
    assert (top["total_mah"], top["cpu_mah"]) == pytest.approx((44.0, 34.0))
    assert result.metrics["uid_count"] == 2
    assert not any("could not be parsed" in note for note in result.notes)
    background = next(f for f in result.findings if f.id.endswith("background_power"))
    assert "44.0 mAh" in background.summary


def test_power_model_uid_states_follow_the_global_split(context_factory):
    """A component the Global model does not split keeps its all-states value."""
    text = "\n".join(
        line
        for line in POWER_STATES.splitlines()
        if not line.strip().startswith(("cpu: 5.00", "cpu: 40.0", "cpu: 10.0"))
    )
    result = power_model(context_factory(live={"batterystats_charged": text}))
    top = result.tables["uids"][0]
    # screen is split (10.0 on battery); cpu is not (40.0 over all states).
    assert (top["total_mah"], top["cpu_mah"]) == pytest.approx((50.0, 40.0))


def test_power_model_skip(context_factory):
    no_model = charged(BUSY).replace("Estimated power use (mAh):", "Other:")
    with pytest.raises(SkipError):
        power_model(context_factory(live={"batterystats_charged": no_model}))


def test_power_profile_busy(busy):
    result = power_profile(busy)
    expected = {
        "profile_cpu_suspend": 0.0,
        "profile_zero_standby_items": 4,
        "profile_cluster_mismatches": 1,
        "cpu_min_on_battery": 5.0,
        "cpu_min_screen_off": 1.0,
        "cpu_core_mah_on_battery": 1.5,
        "cpu_core_mah_screen_off": 0.3,
        "zero_priced_steps": 2,
        "zero_priced_cpu_min": 1.0,
    }
    assert pick(result.metrics, expected) == pytest.approx(expected)
    assert result.metrics["energy_consumers_supported"] is False
    keys = {r["key"] for r in result.tables["profile_zero_standby"]}
    assert keys == {"cpu.suspend", "cpu.idle", "wifi.on", "drain:SLEEP,RAT:DEFAULT"}
    assert ids(result) == {
        "power_profile.standby_unpriced": "medium",
        "power_profile.cpu_steps_unpriced": "low",
        "power_profile.no_energy_metering": "info",
    }
    standby = result.findings[0]
    assert all("brackets" not in e.excerpt for e in standby.evidence)


def test_power_profile_without_profile(calm):
    result = power_profile(calm)
    assert "profile_cpu_suspend" not in result.metrics
    assert any("No power profile" in note for note in result.notes)
    assert "power_profile.standby_unpriced" not in ids(result)


def test_power_profile_model_only_flags_unpriced_awake_time(context_factory):
    ctx = context_factory(live={"batterystats_charged": charged(BUSY)})
    result = power_profile(ctx)
    standby = next(f for f in result.findings if f.id.endswith("standby_unpriced"))
    assert "0.1 mA" in standby.summary


def test_power_profile_decimal_comma_brackets(context_factory):
    text = charged(CALM).replace("0/300(10.0), 0/600(20.0)", "0/300(10,0), 0/600(20,0)")
    result = power_profile(context_factory(live={"batterystats_charged": text}))
    assert result.metrics["cpu_core_mah_on_battery"] == pytest.approx(1.5)


def test_power_profile_skip(context_factory):
    with pytest.raises(SkipError):
        power_profile(context_factory(live={"battery": "  level: 50"}))


def test_alarms_jobs_busy(busy):
    busy.results["wakeup_reasons"] = wakeup_reasons(busy)
    result = alarms_jobs(busy)
    expected = {
        "wakeup_alarms_screen_off": 77,
        "wakeup_alarms_per_screen_off_h": 19.2,
        "wakeup_alarm_uids": 2,
        "job_runs_on_battery": 33,
        "alarms_jobs_pct_of_resumes": 2.2,
        "alarm_wakeups_since_boot": 120,
        "alarm_wakeups_per_h_since_boot": 12.0,
        "job_history_starts": 2,
        "job_history_span_s": 300.0,
    }
    assert pick(result.metrics, expected) == pytest.approx(expected)
    stats = result.tables["alarm_stats_since_boot"]
    assert (stats[0]["package"], stats[0]["top_tag"]) == (
        "com.example.sync",
        "*walarm*:com.example.sync.POLL",
    )
    assert stats[1]["top_tag"] == "*walarm*:DeviceIdleController.deep"
    alarm = result.tables["wakeup_alarms"][0]
    assert alarm["package"] == "com.example.sync"
    # Wakeup alarm counters run only with the screen off: 60 in 4 h, not 5 h.
    assert alarm["per_screen_off_h"] == pytest.approx(15.0)
    # The alarm-rate finding carries the share of resumes: no second finding.
    assert ids(result) == {
        "alarms_jobs.frequent_wakeup_alarms": "low",
        "alarms_jobs.heavy_jobs": "low",
    }
    frequent = result.findings[0]
    assert "equal 2.2% of the" in frequent.summary
    assert "not what keeps waking the phone" in frequent.summary


def test_alarms_jobs_calm_share_of_few_wakeups(calm):
    result = alarms_jobs(calm)
    assert result.metrics["alarms_jobs_pct_of_resumes"] == pytest.approx(13.6)
    assert ids(result) == {"alarms_jobs.drive_wakeups": "medium"}


def test_alarms_compare_with_screen_off_resumes(calm):
    calm.results["standby_wake"] = Result("standby_wake", metrics={"resumes": 220})
    result = alarms_jobs(calm)
    assert result.metrics["alarms_pct_of_screen_off_resumes"] == pytest.approx(10.0)
    assert result.metrics["jobs_pct_of_resumes"] == pytest.approx(5.7)
    # The combined share divides both by the real resumes on battery, so it is
    # not the sum of the two shares above.
    assert result.metrics["alarms_jobs_pct_of_resumes"] == pytest.approx(13.6)


def test_alarms_jobs_reads_earlier_resumes(calm):
    calm.results["wakeup_reasons"] = Result("wakeup_reasons", metrics={"resumes": 3400})
    result = alarms_jobs(calm)
    assert result.metrics["alarms_jobs_pct_of_resumes"] == pytest.approx(1.1)
    assert ids(result) == {"alarms_jobs.not_the_driver": "info"}


def test_uid_block_survives_a_three_space_line(context_factory):
    """Some Samsung builds indent one per-UID line by three spaces."""
    text = charged(BUSY).replace(
        "    Job com.example.sync/.SyncJob:",
        "   Screen-off cpu times per freq at state Cached: 1 2 3\n"
        "    Job com.example.sync/.SyncJob:",
    )
    result = alarms_jobs(context_factory(live={"batterystats_charged": text}))
    assert result.metrics["wakeup_alarms_screen_off"] == 77
    assert result.metrics["job_runs_on_battery"] == 33


def test_alarms_jobs_skip(context_factory):
    with pytest.raises(SkipError):
        alarms_jobs(context_factory(live={"battery": "  level: 50"}))


def test_unparsable_lines_are_counted_not_fatal(context_factory):
    text = (
        charged(BUSY)
        .replace(
            "  All kernel wake locks:\n",
            "  All kernel wake locks:\n  Kernel Wake lock broken line\n",
        )
        .replace(
            "  All wakeup reasons:\n", "  All wakeup reasons:\n  Wakeup reason ?\n"
        )
    )
    ctx = context_factory(live={"batterystats_charged": text})
    assert "1 wakeup-reason lines could not be parsed." in wakeup_reasons(ctx).notes
    notes = wakelocks(ctx).notes
    assert "1 lines in 'All kernel wake locks' could not be parsed." in notes


def test_tables_are_capped_with_a_note(context_factory):
    extra = "".join(
        f"  Kernel Wake lock example_{i}: {i}s 0ms (1 times) realtime\n"
        for i in range(1, 31)
    )
    text = charged(BUSY).replace(
        "  All kernel wake locks:\n",
        "  All kernel wake locks:\n" + extra,
    )
    result = wakelocks(context_factory(live={"batterystats_charged": text}))
    assert len(result.tables["kernel_wakelocks"]) == 25
    assert "kernel_wakelocks: showing 25 of 34 rows" in result.notes
