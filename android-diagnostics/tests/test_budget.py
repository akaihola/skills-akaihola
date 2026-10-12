"""Tests for the drain budget and the bottom line (androiddiag.budget).

Every number is invented. The budget analyzers read only other analyzers'
results, so the tests fill ``ctx.results`` by hand.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from androiddiag import budget
from androiddiag.model import (
    REGISTRY,
    Evidence,
    Finding,
    Result,
    SkipError,
    Windows,
    run_order,
)

WINDOWS = Windows(
    dump_time=datetime(2026, 1, 15, 12, 0),
    since_charge_start=datetime(2026, 1, 15, 8, 0),
    on_battery_at_capture=True,
    on_battery_s=4 * 3600.0,
    screen_off_on_battery_s=3 * 3600.0,
    utc_offset="+0200",
)


def finding(fid, **overrides):
    fields = {
        "symptom": "battery",
        "severity": "high",
        "basis": "measured",
        "window": "on_battery",
        "summary": (
            "The first sentence has 1.5 numbers. The second sentence adds detail."
        ),
        "recommendation": "Do the generic thing.",
    }
    fields.update(overrides)
    return Finding(
        id=fid,
        title=f"Title of {fid}",
        evidence=[Evidence(f"live/{fid.split('.')[0]}.txt:7", "an excerpt")],
        followups=[f"Check {fid} again."],
        **fields,
    )


def result(name, window="on_battery", metrics=None, tables=None, findings=()):
    return Result(
        name,
        window=window,
        metrics=dict(metrics or {}),
        tables=dict(tables or {}),
        findings=list(findings),
    )


def standard_results():
    """A phone with a Wi-Fi wake storm, aborted suspends and a worn battery."""
    return {
        "windows": result("windows", "snapshot"),
        "discharge_accounting": result(
            "discharge_accounting",
            metrics={
                "on_battery_s": 14400.0,
                "screen_off_s": 10800.0,
                "screen_on_s": 3600.0,
                "discharge_mah": 300.0,
                "screen_on_mah": 120.0,
                "screen_off_mah": 180.0,
                "deep_doze_mah": 150.0,
                "light_doze_mah": 0.0,
                "device_full_idling_s": 9000.0,
                "gauge_step_mah": 25.0,
            },
            findings=[
                finding(
                    "discharge_accounting.standby_drain",
                    window="screen_off_on_battery",
                ),
            ],
        ),
        "power_model": result(
            "power_model",
            metrics={
                "discharge_mah": 300,
                "modelled_mah": 150.0,
                "attributed_mah": 140.0,
                "unmodelled_mah": 150.0,
                "unmodelled_pct": 50.0,
                "unmodelled_ma_per_awake_h": 40.0,
            },
            tables={"components": [{"component": "cpu", "mah": 90.0}]},
            findings=[
                finding(
                    "power_model.unmodelled_drain",
                    severity="medium",
                    basis="modelled",
                ),
            ],
        ),
        "standby_wake": result(
            "standby_wake",
            "screen_off_on_battery",
            metrics={
                "awake_share_pct": 55.0,
                "resumes": 2700,
                "resumes_per_h": 900.0,
                "awake_per_resume_median_s": 1.2,
                "awake_without_wakelock_share_pct": 80.0,
                "deep_idle_share_pct": 90.0,
                "suspend_aborts_per_resume": 1.6,
            },
            tables={
                "wake_reasons": [
                    {"reason": "7 WLAN_RX", "resumes": 2565, "share_pct": 95.0},
                    {"reason": "3 rtc_alarm", "resumes": 108, "share_pct": 4.0},
                    {"reason": "9 other", "resumes": 27, "share_pct": 0.5},
                ],
            },
            findings=[
                finding("standby_wake.awake_share", window="screen_off_on_battery"),
            ],
        ),
        "wakeup_reasons": result(
            "wakeup_reasons",
            metrics={
                "resumes": 3000,
                "resumes_per_h": 750.0,
                "abort_to_resume_ratio": 1.5,
                "awake_after_aborts_pct_of_uptime": 50.0,
            },
            findings=[finding("wakeup_reasons.suspend_aborts")],
        ),
        "wake_periodicity": result(
            "wake_periodicity",
            "screen_off_on_battery",
            metrics={"period_s": 5.0, "grid_excess_pp": 30.0},
            findings=[
                finding(
                    "wake_periodicity.periodic_sender",
                    severity="medium",
                    basis="inferred",
                ),
            ],
        ),
        "wifi_multicast": result(
            "wifi_multicast",
            metrics={
                "multicast_pct_of_battery": 80.0,
                "top_package": "com.example.sync",
                "fw_multicast_broadcast_pct": 12.0,
            },
        ),
        "system_process_cpu_churn": result(
            "system_process_cpu_churn",
            tables={
                "processes": [
                    {
                        "process": "example_daemon",
                        "cpu_s": 600.0,
                        "core_pct_on_battery": 4.2,
                    },
                ],
            },
        ),
        "battery_capacity": result(
            "battery_capacity",
            "snapshot",
            metrics={"learned_capacity_mah": 2500.0, "design_capacity_mah": 3500.0},
            findings=[
                finding("battery_capacity.worn", severity="medium", window="snapshot"),
            ],
        ),
    }


@pytest.fixture
def ctx(context_factory):
    context = context_factory(windows=WINDOWS)
    context.results.update(standard_results())
    return context


def test_measured_split_and_reference(ctx):
    res = budget.drain_budget(ctx)
    m = res.metrics
    assert m["discharge_mah_per_h"] == pytest.approx(75.0)
    assert m["screen_on_mah_per_h"] == pytest.approx(120.0)
    assert m["screen_off_mah_per_h"] == pytest.approx(60.0)
    assert m["screen_off_mah_per_h_low"] == pytest.approx(51.7)
    assert m["screen_off_mah_per_h_high"] == pytest.approx(68.3)
    assert m["deep_doze_mah_per_h"] == pytest.approx(60.0)
    assert m["modelled_pct"] == pytest.approx(50.0)
    assert m["unmodelled_pct"] == pytest.approx(50.0)
    assert m["screen_off_vs_reference_high_x"] == pytest.approx(3.0)
    parts = [row["part"] for row in res.tables["discharge"]]
    assert parts[:4] == [
        "all time on battery",
        "screen on",
        "screen off",
        "screen off: deep Doze",
    ]
    assert "screen off: light Doze" not in parts  # zero light Doze is left out
    where = next(f for f in res.findings if f.id == "drain_budget.where_it_went")
    assert where.severity == "info"
    assert where.basis == "measured"
    assert "general knowledge, not measured on this phone" in where.summary
    assert "3.0x the upper figure" in where.summary
    assert any("general knowledge" in note for note in res.notes)


def test_wake_chain_is_layered_and_has_no_mah(ctx):
    res = budget.drain_budget(ctx)
    rows = res.tables["wake_chain"]
    layers = [row["layer"] for row in rows]
    assert layers == sorted(layers, key=budget.LAYER_ORDER.index)
    assert {"trigger", "enabler", "multiplier", "consequence"} <= set(layers)
    for row in rows:
        assert "mah" not in row["unit"].lower()
    reasons = [row["item"] for row in rows if row["item"].startswith("wake reason")]
    assert reasons == [
        "wake reason '7 WLAN_RX' (name suggests Wi-Fi)",
        "wake reason '3 rtc_alarm' (name suggests an alarm timer)",
    ]  # the 0.5 % reason is below MIN_REASON_SHARE_PCT
    periodic = next(row for row in rows if row["source"] == "wake_periodicity")
    assert periodic["basis"] == "inferred"
    chain = next(f for f in res.findings if f.id == "drain_budget.wake_chain")
    assert "must not be added up" in chain.summary
    assert "awake 55.0%" in chain.summary
    assert res.metrics["top_wake_reason_hint"] == "Wi-Fi"
    assert res.metrics["aborts_per_resume"] == pytest.approx(1.5)


def test_periodic_row_needs_the_periodicity_finding(ctx):
    ctx.results["wake_periodicity"].findings = []
    res = budget.drain_budget(ctx)
    assert all(row["source"] != "wake_periodicity" for row in res.tables["wake_chain"])
    assert "periodic_period_s" not in res.metrics


def test_capacity_effect(ctx):
    res = budget.drain_budget(ctx)
    m = res.metrics
    assert m["state_of_health_pct"] == pytest.approx(71.4)
    assert m["new_pack_runtime_factor"] == pytest.approx(1.4)
    assert m["runtime_h_at_average_rate"] == pytest.approx(33.3)
    assert m["runtime_h_at_average_rate_new_pack"] == pytest.approx(46.7)
    assert m["standby_runtime_h"] == pytest.approx(41.7)
    cap = next(f for f in res.findings if f.id == "drain_budget.capacity_effect")
    assert "does not raise the drain" in cap.title
    assert cap.evidence[0].ref == "live/battery_capacity.txt:7"


def test_decimal_comma_metric_strings(ctx):
    sw = ctx.results["standby_wake"].metrics
    sw["awake_share_pct"] = "48,5"
    sw["resumes_per_h"] = "1.234,5"
    res = budget.drain_budget(ctx)
    assert res.metrics["screen_off_awake_share_pct"] == pytest.approx(48.5)
    assert res.metrics["resumes_per_h"] == pytest.approx(1234.5)


def test_unparsable_metric_is_ignored(ctx):
    ctx.results["standby_wake"].metrics["awake_share_pct"] = "n/a"
    res = budget.drain_budget(ctx)
    assert "screen_off_awake_share_pct" not in res.metrics
    assert res.metrics["resumes_per_h"] == pytest.approx(900.0)


def test_resume_rate_falls_back_to_wakeup_reasons(ctx):
    del ctx.results["standby_wake"]
    res = budget.drain_budget(ctx)
    assert res.metrics["resumes_per_h"] == pytest.approx(750.0)
    assert res.metrics["resumes_window"] == "on_battery"


def test_without_power_model_or_capacity(ctx):
    for name in ("power_model", "battery_capacity"):
        del ctx.results[name]
    res = budget.drain_budget(ctx)
    assert "modelled_mah" not in res.metrics
    assert {f.id for f in res.findings} == {
        "drain_budget.where_it_went",
        "drain_budget.wake_chain",
    }


def test_skipped_and_failed_results_are_ignored(ctx):
    ctx.results["discharge_accounting"].status = "error"
    ctx.results["power_model"].status = "skipped"
    res = budget.drain_budget(ctx)
    assert "discharge_mah" not in res.metrics
    assert "No counter-based discharge on battery was found." in res.notes


def test_drain_budget_skips_without_inputs(context_factory):
    ctx = context_factory(windows=Windows())
    ctx.results["windows"] = result("windows", "snapshot")
    with pytest.raises(SkipError, match="no discharge"):
        budget.drain_budget(ctx)


def test_bottom_line_one_finding_per_theme(ctx):
    ctx.results["drain_budget"] = budget.drain_budget(ctx)
    res = budget.bottom_line(ctx)
    ids = [row["id"] for row in res.tables["top_battery"]]
    assert ids == [
        "discharge_accounting.standby_drain",
        "standby_wake.awake_share",
        "wakeup_reasons.suspend_aborts",
        "battery_capacity.worn",
        "power_model.unmodelled_drain",
    ]
    battery = next(f for f in res.findings if f.id == "bottom_line.battery")
    assert battery.severity == "info"
    assert battery.summary.splitlines()[1].startswith("1. Title of discharge_acc")
    assert "[screen off on battery; measured]" in battery.summary
    assert "general knowledge, not measured on this phone" in battery.summary
    assert "75.0 mAh/h" in battery.summary
    assert battery.metrics["finding_ids"] == ids


def test_bottom_line_names_the_radio_behind_the_previous_period(ctx):
    """The mechanism is a share of the same period, not mAh added to the item."""
    heavier = finding("previous_cycle.heavier_period", window="previous_charge")
    radio = finding("previous_cycle.mobile_radio_busy", window="previous_charge")
    radio.metrics = {"mobile_radio_share_pct": 74.8}
    ctx.results["previous_cycle"] = result("previous_cycle", findings=[heavier, radio])
    res = budget.bottom_line(ctx)
    battery = next(f for f in res.findings if f.id == "bottom_line.battery")
    [line] = [x for x in battery.summary.splitlines() if heavier.title in x]
    assert "mobile radio was active 74.8% of that period's time on battery" in line
    assert radio.id not in battery.metrics["finding_ids"]


def test_bottom_line_low_items_fill_only_short_lists(ctx):
    ctx.results["memory_x"] = result(
        "memory_x",
        findings=[
            finding("exit_info_audit.low_memory_kills", symptom="slowness"),
            finding("frame_jank.janky_apps", symptom="slowness", severity="low"),
            finding("thermal_status.elevated", symptom="slowness", severity="low"),
        ],
    )
    res = budget.bottom_line(ctx)
    slow = [row["id"] for row in res.tables["top_slowness"]]
    assert slow == [
        "exit_info_audit.low_memory_kills",
        "frame_jank.janky_apps",
        "thermal_status.elevated",
    ]
    ctx.results["memory_x"].findings += [
        finding(
            "vmstat_reclaim_io.page_cache_thrashing",
            symptom="both",
            severity="medium",
        ),
        finding(
            "battery_saver_state.mostly_on",
            symptom="slowness",
            severity="medium",
        ),
    ]
    res = budget.bottom_line(ctx)
    slow = [row["id"] for row in res.tables["top_slowness"]]
    assert slow == [
        "exit_info_audit.low_memory_kills",
        "vmstat_reclaim_io.page_cache_thrashing",
        "battery_saver_state.mostly_on",
    ]


def test_bottom_line_without_slowness_findings(ctx):
    res = budget.bottom_line(ctx)
    slow = next(f for f in res.findings if f.id == "bottom_line.slowness")
    assert slow.title == "Slowness: nothing found"
    assert "No slowness problem was found" in slow.summary


def test_not_determined_lists_gaps_and_caveats(ctx):
    ctx.windows.on_battery_at_capture = False
    ctx.windows.utc_offset = None
    ctx.results["frame_jank"] = Result(
        "frame_jank",
        status="skipped",
        reason="missing inputs: graphicsstats",
    )
    ctx.results["broken"] = Result("broken", status="error", reason="ValueError()")
    res = budget.bottom_line(ctx)
    gaps = next(f for f in res.findings if f.id == "bottom_line.not_determined")
    lines = gaps.summary.splitlines()
    assert lines[0] == "Analyzer frame_jank skipped: missing inputs: graphicsstats."
    assert "Analyzer broken failed: ValueError()." in lines
    assert any(line.startswith("Missing input power_profile") for line in lines)
    assert any("external power at capture" in line for line in lines)
    assert any("UTC offset" in line for line in lines)
    assert any("50.0% of the measured drain" in line for line in lines)
    assert "power_profile" in gaps.metrics["missing_inputs"]
    assert (
        "Collect power_profile with `adb_ro.py --save power_profile --workdir "
        "WORKDIR -- dumpsys batterystats --power-profile`, then run analyze.py again."
    ) in gaps.followups
    assert res.metrics["analyzers_skipped"] == 1
    assert res.metrics["analyzers_failed"] == 1


def test_unmodelled_caveat_threshold(ctx):
    ctx.results["power_model"].metrics["unmodelled_pct"] = 20.0
    res = budget.bottom_line(ctx)
    gaps = next(f for f in res.findings if f.id == "bottom_line.not_determined")
    assert "power-model component" not in gaps.summary


def test_present_inputs_are_not_reported_missing(context_factory):
    ctx = context_factory(
        live={"power_profile": "battery.capacity=3000\n", "clock": "x\n"},
        windows=WINDOWS,
    )
    ctx.results.update(standard_results())
    res = budget.bottom_line(ctx)
    missing = res.findings[-1].metrics["missing_inputs"]
    assert "power_profile" not in missing
    assert "clock" not in missing


def test_bottom_line_skips_without_results(context_factory):
    ctx = context_factory(windows=Windows())
    ctx.results["windows"] = result("windows", "snapshot")
    with pytest.raises(SkipError, match="no analyzer results"):
        budget.bottom_line(ctx)


def test_run_order_puts_the_budget_last():
    regs = {name: REGISTRY[name] for name in ("bottom_line", "drain_budget")}
    assert "drain_budget" in regs["bottom_line"].after
    assert "standby_wake" in regs["bottom_line"].after
    order = [r.name for r in run_order(regs)]
    assert order == ["drain_budget", "bottom_line"]


@pytest.mark.parametrize(
    ("fid", "theme"),
    [
        ("standby_wake.awake_share", "wakeups"),
        ("wakeup_reasons.suspend_aborts", "suspend failures"),
        ("previous_cycle.suspend_blocked", "suspend failures"),
        ("wakelocks.suspend_lockout_screen_off", "suspend failures"),
        ("system_process_cpu_churn.android-system-suspend-service", "suspend failures"),
        ("system_process_cpu_churn.ueventd", "background CPU"),
        ("previous_cycle.heavier_period", "previous charge period"),
        ("exit_info_audit.excessive_cpu_kills", "apps"),
        ("exit_info_audit.low_memory_kills", "memory"),
        ("daily_steps.low_level_collapse", "battery wear"),
        ("daily_steps.idle_drain", "standby drain"),
        ("unknown_analyzer.thing", "unknown_analyzer"),
    ],
)
def test_theme_of(fid, theme):
    assert budget.theme_of(fid)[0] == theme


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Drain was 3.14 %/h. Then more.", "Drain was 3.14 %/h."),
        ("No full stop here", "No full stop here"),
        ("One (48.5%) and 1,234/h. 'Quoted' next.", "One (48.5%) and 1,234/h."),
    ],
)
def test_first_sentence(text, expected):
    assert budget.first_sentence(text) == expected


def test_first_sentence_is_cut_at_a_word():
    text = "word " * 100
    assert budget.first_sentence(text, limit=20) == "word word word word ..."


@pytest.mark.parametrize(
    ("reason", "hint"),
    [
        ("37 WLAN_CE_4", "Wi-Fi"),
        ("55 ipa", "mobile data"),
        ("208 pon_kpdpwr_status", "a button"),
        ("371 typec-cc-state-change", "the charger or USB"),
        ("12 ipcc_3", ""),
    ],
)
def test_irq_hint(reason, hint):
    assert budget.irq_hint(reason) == hint


def test_formatting_helpers():
    assert budget.fmt_span(18245.0) == "5h04m"
    assert budget.fmt_span(2575.0) == "42m"
    assert budget.fmt_span(27.4) == "27s"
    assert budget.fmt_span(None) == "?"
    assert budget.fmt_num(1234.5, 0) == "1,234"
    assert budget.fmt_num(None) == "?"


def test_zero_counter_falls_back_to_the_battery_level(ctx):
    """'Discharge: 0 mAh' means the gauge counted nothing (ROB-1, F2)."""
    da = ctx.results["discharge_accounting"].metrics
    da.update(discharge_mah=0.0, screen_on_mah=0.0, screen_off_mah=0.0)
    ctx.results["power_model"].metrics.update(
        discharge_mah=0.0,
        actual_drain_min_mah=48.0,
        actual_drain_max_mah=96.0,
        modelled_mah=30.0,
    )
    res = budget.drain_budget(ctx)
    m = res.metrics
    assert m["discharge_mah"] == pytest.approx(72.0)  # midpoint of 48-96
    assert (m["discharge_mah_low"], m["discharge_mah_high"]) == (48.0, 96.0)
    assert m["discharge_source"] == budget.LEVEL_SOURCE
    assert "screen_off_mah" not in m  # the zero parts come from the dead counter
    assert m["unmodelled_mah"] == pytest.approx(42.0)  # against this total
    where = next(f for f in res.findings if f.id == "drain_budget.where_it_went")
    assert "counted by the fuel gauge" not in where.summary
    assert "48-96 mAh from the battery level" in where.summary
    assert where.title.startswith("Where the charge went: about 72 mAh")
    assert any("level-based" in note for note in res.notes)
    ctx.results["drain_budget"] = res
    line = next(
        f for f in budget.bottom_line(ctx).findings if f.id == "bottom_line.battery"
    )
    assert line.summary.startswith(
        "On battery since the last full charge the phone used about 72 mAh "
        "(48-96 mAh by the battery level) in 4h00m (about 18.0 mAh/h).",
    )


def test_zero_counter_without_a_level_range_gives_no_budget(ctx):
    ctx.results["discharge_accounting"].metrics["discharge_mah"] = 0.0
    del ctx.results["power_model"]
    res = budget.drain_budget(ctx)  # no ZeroDivisionError
    assert "discharge_mah" not in res.metrics
    assert "No counter-based discharge on battery was found." in res.notes


def test_model_above_the_measured_drain_is_not_negative(ctx):
    """A model that bills more than was measured leaves nothing unexplained (ROB-7)."""
    ctx.results["power_model"].metrics.update(
        modelled_mah=420.0,
        unmodelled_mah=-120.0,
        unmodelled_pct=-40.0,
        unmodelled_ma_per_awake_h=-60.0,
    )
    res = budget.drain_budget(ctx)
    m = res.metrics
    assert m["model_excess_mah"] == pytest.approx(120.0)
    for key in ("unmodelled_mah", "unmodelled_pct", "unmodelled_ma_per_awake_h"):
        assert key not in m
    rows = {row["part"]: row for row in res.tables["discharge"]}
    assert "in no model component" not in rows
    excess = rows["power model above the measured drain"]
    assert excess["mah"] == pytest.approx(120.0)
    assert all(
        row["pct_of_discharge"] is None
        for row in rows.values()
        if row["basis"] == "modelled"
    )
    where = next(f for f in res.findings if f.id == "drain_budget.where_it_went")
    assert "120 mAh more than the 300 mAh measured" in where.summary
    assert "is in no component" not in where.summary
    ctx.results["drain_budget"] = res
    gaps = budget.bottom_line(ctx).findings[-1]
    assert "bills 120 mAh more than the measured drain" in gaps.summary


def test_short_windows_get_no_hourly_rate(ctx):
    """One gauge step over seconds is not a rate (ROB-5, drain_budget part)."""
    da = ctx.results["discharge_accounting"].metrics
    da.update(screen_on_s=30.0, screen_off_s=14370.0, screen_on_mah=25.0)
    res = budget.drain_budget(ctx)
    assert "screen_on_mah_per_h" not in res.metrics
    where = next(f for f in res.findings if f.id == "drain_budget.where_it_went")
    assert "Screen on: 25 mAh in 30s (too short for a rate)." in where.summary
    assert any("No mAh/h for screen on" in note for note in res.notes)


def test_gauge_step_range_does_not_go_negative(ctx):
    ctx.results["discharge_accounting"].metrics["gauge_step_mah"] = 250.0
    res = budget.drain_budget(ctx)
    assert res.metrics["screen_off_mah_per_h_low"] == pytest.approx(0.0)


def test_deep_doze_rate_uses_idle_mode_full_time(ctx):
    ctx.results["discharge_accounting"].metrics["idle_mode_full_s"] = 7200.0
    res = budget.drain_budget(ctx)
    assert res.metrics["deep_doze_s"] == pytest.approx(7200.0)
    assert res.metrics["deep_doze_mah_per_h"] == pytest.approx(75.0)


def test_followups_save_device_output_with_adb_ro(ctx):
    ctx.results["drain_budget"] = res = budget.drain_budget(ctx)
    followups = [text for f in res.findings for text in f.followups]
    followups += budget.bottom_line(ctx).findings[-1].followups
    assert any(
        "adb_ro.py --save batterystats_retest --workdir WORKDIR" in t for t in followups
    )
    for text in followups:
        assert "adb shell" not in text
        assert "adb logcat" not in text
    # cpufreq is a shell loop that adb_ro.py refuses, so collect.py runs it.
    assert budget.collect_followup("cpufreq").startswith(
        "Collect cpufreq with `collect.py --only cpufreq`",
    )


@pytest.mark.parametrize(
    ("links", "expected"),
    [
        # The stronger finding owns the weaker, whichever lists the other.
        ([("a.x", (0, 0, 0), ["b.y"]), ("b.y", (1, 0, 0), [])], {"b.y": "a.x"}),
        ([("a.x", (0, 0, 0), []), ("b.y", (1, 0, 0), ["a.x"])], {"b.y": "a.x"}),
        # On a tie the finding that lists the other owns it.
        ([("a.x", (1, 0, 0), []), ("b.y", (1, 0, 0), ["a.x"])], {"a.x": "b.y"}),
        # Ids that were not emitted are ignored; chains end at the root.
        (
            [
                ("a.x", (0, 0, 0), ["b.y", "gone.z"]),
                ("b.y", (1, 0, 0), ["c.z"]),
                ("c.z", (2, 0, 0), []),
            ],
            {"b.y": "a.x", "c.z": "a.x"},
        ),
        # Two findings that list each other: the lower id owns on a tie.
        ([("b.y", (1, 0, 0), ["a.x"]), ("a.x", (1, 0, 0), ["b.y"])], {"b.y": "a.x"}),
    ],
)
def test_owner_map(links, expected):
    assert budget.owner_map(links) == expected


def test_bottom_line_skips_findings_folded_into_another(ctx):
    """A finding linked to a stronger one through related is not a new item."""
    churn = "system_process_cpu_churn.android-system-suspend-service"
    daemons = finding("process_cpu_since_boot.busy-daemons", severity="medium")
    ctx.results["system_process_cpu_churn"].findings = [finding(churn)]
    ctx.results["process_cpu_since_boot"] = result(
        "process_cpu_since_boot",
        findings=[daemons],
    )
    del ctx.results["wakeup_reasons"]  # leaves the suspend theme to the churn

    def picked():
        findings = [f for r in ctx.results.values() for f in r.findings]
        return [f.id for f in budget.pick_top(findings, "battery")]

    assert daemons.id in picked()  # its own theme: background CPU
    daemons.related = [churn]  # the daemon list points at the stronger owner
    ids = picked()
    assert churn in ids
    assert daemons.id not in ids
