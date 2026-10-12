"""Tests for the performance analyzers in androiddiag.perf.

All fixture text is invented: package names are com.example.*, and every
number is made up to hit or miss a threshold.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta
from itertools import starmap
from textwrap import dedent

import pytest
from androiddiag import perf
from androiddiag.model import SkipError, Windows
from androiddiag.source import Text

DUMP_TIME = datetime(2026, 1, 15, 12, 0)


def _windows(**kwargs):
    return Windows(dump_time=DUMP_TIME, **kwargs)


def _ids(result):
    return [f.id for f in result.findings]


# --------------------------------------------------------------------------
# frame_jank
# --------------------------------------------------------------------------


def _gfx_block(package, since_ms, frames, janky, *, p50=8):
    """Return one graphicsstats package block with a matching histogram."""
    hist = {p50: frames - janky, 40: janky}
    gpu = 9
    histogram = " ".join(f"{ms}ms={n}" for ms, n in sorted(hist.items()))
    pct = f"{100 * janky / frames:.2f}" if frames else "nan"
    return dedent(
        f"""\
        Package: {package}
        Version: 1
        Stats since: {since_ms}ns
        Stats end: {since_ms + 3_600_000}ns
        Total frames rendered: {frames}
        Janky frames: {janky} ({pct}%)
        50th percentile: {p50}ms
        90th percentile: 30ms
        95th percentile: 40ms
        99th percentile: 40ms
        Number Missed Vsync: 3
        Number High input latency: 5
        Number Slow UI thread: {janky}
        Number Slow bitmap uploads: 3
        Number Slow issue draw commands: 4
        Number Frame deadline missed: {janky}
        HISTOGRAM: {histogram}
        50th gpu percentile: 4ms
        90th gpu percentile: 7ms
        95th gpu percentile: {gpu}ms
        99th gpu percentile: 13ms
        GPU HISTOGRAM: 4ms=10 {gpu}ms=5
        """,
    )


DAY1 = 1_767_225_600_000  # 2026-01-01 00:00 UTC, in milliseconds
DAY2 = DAY1 + 86_400_000

GRAPHICSSTATS = "\n".join(
    [
        "Service host process PID: 1000",
        "",
        _gfx_block("com.example.launcher", DAY1, 400, 140),
        _gfx_block("com.example.launcher", DAY2, 300, 120),
        _gfx_block("com.example.calm", DAY2, 1000, 50),
        _gfx_block("com.example.render", DAY2, 500, 40, p50=25),
        _gfx_block("com.example.tiny", DAY2, 50, 40),
        _gfx_block("com.example.idle", DAY2, 0, 0),
        "Some unexpected line",
    ],
)


def test_graphicsstats_parse_counts_buckets_and_days():
    blocks, skipped = perf.parse_graphicsstats(Text("gfx", GRAPHICSSTATS))
    assert len(blocks) == 6
    assert skipped == 1
    first = blocks[0]
    assert first.package == "com.example.launcher"
    assert first.day_utc == "2026-01-01"
    assert first.frames == 400
    assert first.janky == 140
    assert first.percentiles[99] == 40
    assert first.gpu_percentiles[95] == 9
    assert first.counters["slow_ui_thread"] == 140
    assert sum(first.histogram.values()) == 400
    assert not blocks[-1].janky_pct  # "nan%" in the dump


def test_frame_jank_flags_janky_apps_and_slow_medians(context_factory):
    ctx = context_factory(
        live={
            "graphicsstats": GRAPHICSSTATS,
            "home_activity": "priority=0 isDefault=true\ncom.example.launcher/.Home\n",
        },
        windows=_windows(),
    )
    result = perf.frame_jank(ctx)
    rows = {r["package"]: r for r in result.tables["per_package"]}
    launcher = rows["com.example.launcher"]
    assert launcher["role"] == "home launcher"
    assert launcher["frames"] == 700
    assert launcher["janky_pct"] == pytest.approx(37.1)
    assert launcher["janky_pct_min_day"] == pytest.approx(35.0)
    assert launcher["janky_pct_max_day"] == pytest.approx(40.0)
    assert launcher["p99_ms"] == 40
    assert launcher["bottleneck"] == "ui_thread"
    assert result.metrics["janky_pct_com_example_launcher"] == pytest.approx(37.1)
    # One finding per fact: the janky apps, then the slow-median apps.
    assert _ids(result) == ["frame_jank.janky_apps", "frame_jank.slow_frames"]
    janky, slow = result.findings
    # Under 20% janky, or under the minimum frame count: not listed.
    assert janky.metrics["packages"] == ["com.example.launcher"]
    # A role app over 30% janky is high whatever its frame count.
    assert janky.severity == "high"
    assert janky.window == "daily"
    assert janky.basis == "measured"
    assert janky.evidence[0].ref.startswith("live/graphicsstats.txt:")
    assert slow.metrics["packages"] == ["com.example.render"]
    assert result.tables["daily_buckets"][0]["package"] == "com.example.launcher"


def _jank_ctx(context_factory, *blocks):
    gfx = "\n".join(starmap(_gfx_block, blocks))
    return context_factory(live={"graphicsstats": gfx}, windows=_windows())


def test_frame_jank_ranks_by_exposure_not_share(context_factory):
    """A short burst of janky frames is not high; many janky frames are."""
    call = ("com.example.call", DAY2, 1200, 860)  # 72% of few frames
    video = ("com.example.video", DAY2, 40000, 10000)  # 25% of many frames
    result = perf.frame_jank(_jank_ctx(context_factory, call, video))
    (finding,) = result.findings
    assert finding.id == "frame_jank.janky_apps"
    assert finding.metrics["packages"] == ["com.example.video", "com.example.call"]
    assert finding.severity == "medium"
    assert finding.summary.startswith(
        "Most janky frames: com.example.video 25.0% of 40,000 frames and "
        "com.example.call 71.7% of 1,200 frames."
    )
    assert result.tables["per_package"][0]["package"] == "com.example.video"
    chat = ("com.example.chat", DAY2, 24000, 12000)  # 50% of many frames
    result = perf.frame_jank(_jank_ctx(context_factory, call, video, chat))
    (finding,) = result.findings
    assert finding.severity == "high"
    assert finding.metrics["severity_from"] == "com.example.chat"
    assert "For com.example.chat, the slowest 5% / 1%" in finding.summary


def test_frame_jank_lists_every_janky_app(context_factory):
    apps = [(f"com.example.app{n}", DAY2, 1000, 300 + n) for n in range(7)]
    (finding,) = perf.frame_jank(_jank_ctx(context_factory, *apps)).findings
    assert len(finding.metrics["packages"]) == 7
    assert finding.summary.startswith("Most janky frames: com.example.app6 30.6%")
    assert "Also over 20%: com.example.app3 30.3% of 1,000, " in finding.summary
    assert "com.example.app0 30.0% of 1,000." in finding.summary


def test_frame_jank_slow_frames_are_not_called_late(context_factory):
    """A long median with few janky frames means pipelined, on-time frames."""
    render = ("com.example.render", DAY2, 4000, 60)
    result = perf.frame_jank(
        context_factory(live={"graphicsstats": _gfx_block(*render, p50=27)})
    )
    (finding,) = result.findings
    assert finding.id == "frame_jank.slow_frames"
    assert "com.example.render 27 ms over 4,000 frames (1.5% janky)" in finding.summary
    assert "shown on time" in finding.summary
    assert "consistently slower" not in finding.summary


def test_frame_jank_gpu_overflow_bucket_is_not_a_frame_time(context_factory):
    """graphicsstats files every GPU frame over 25 ms under 4950ms."""
    block = _gfx_block("com.example.game", DAY2, 1000, 400)
    block = block.replace(
        "GPU HISTOGRAM: 4ms=10 9ms=5", "GPU HISTOGRAM: 4ms=10 4950ms=5"
    )
    ctx = context_factory(live={"graphicsstats": block})
    (finding,) = perf.frame_jank(ctx).findings
    assert "GPU p95 is over 25 ms; the GPU itself is slow" in finding.summary


HISTOGRAMS = [
    # (histogram, printed 50th/90th/95th/99th percentiles)
    ({5: 50, 10: 40, 20: 10}, (10, 20, 20, 20)),
    ({6: 1, 8: 3, 12: 4, 17: 2}, (12, 17, 17, 17)),
    ({4: 97, 150: 2, 4950: 1}, (4, 4, 4, 4950)),
]


@pytest.mark.parametrize(("histogram", "printed"), HISTOGRAMS)
def test_hist_percentile_matches_graphicsstats(histogram, printed):
    """The percentiles graphicsstats prints come back from its own histogram."""
    buckets = " ".join(f"{ms}ms={n}" for ms, n in histogram.items())
    lines = "\n".join(
        f"{p}th percentile: {v}ms"
        for p, v in zip((50, 90, 95, 99), printed, strict=True)
    )
    text = f"Package: com.example.app\n{lines}\nHISTOGRAM: {buckets}\n"
    (block,), _ = perf.parse_graphicsstats(Text("gfx", text))
    for p in (50, 90, 95, 99):
        assert perf.hist_percentile(block.histogram, p) == block.percentiles[p]


def test_frame_jank_decimal_comma_percentage_is_ignored(context_factory):
    text = GRAPHICSSTATS.replace("(35.00%)", "(35,00%)")
    ctx = context_factory(live={"graphicsstats": text})
    rows = {r["package"]: r for r in perf.frame_jank(ctx).tables["per_package"]}
    assert rows["com.example.launcher"]["janky_pct_max_day"] == pytest.approx(40.0)


def test_frame_jank_notes_animations_off(context_factory):
    settings = "animator_duration_scale=0.0\nwindow_animation_scale=0.0\n"
    ctx = context_factory(live={"graphicsstats": GRAPHICSSTATS, "settings": settings})
    result = perf.frame_jank(ctx)
    assert any("Animation scales are set to 0" in n for n in result.notes)


def test_frame_jank_skips_without_input(context_factory):
    with pytest.raises(SkipError):
        perf.frame_jank(context_factory(live={"battery": "level: 50"}))
    with pytest.raises(SkipError):
        perf.frame_jank(context_factory(live={"graphicsstats": "nothing here"}))


# --------------------------------------------------------------------------
# app_launch_times
# --------------------------------------------------------------------------

EVENTS_LOG = dedent(
    """\
    --------- beginning of events
    2026-01-15 11:00:00.000  1000  1000  1100 I am_proc_start: [0,4000,10101,com.example.cold,next-top-activity,{com.example.cold/.Main}]
    2026-01-15 11:00:06.500  1000  1000  1200 I wm_activity_launch_time: [0,12345,com.example.cold/.Main,6400]
    2026-01-15 11:10:00.000  1000  1000  1200 I wm_activity_launch_time: [0,12346,com.example.warm/.Main,900]
    2026-01-15 11:20:00.000  1000  1000  2548 I thermal_changed: [skin,3,41.500000,3,0]
    2026-01-15 11:21:00.000  1000  1000  1843 I battery_saver_mode: [1,0,0,0,1,,7]
    2026-01-15 11:22:00.000  1000  1000  1843 I battery_saver_mode: [0,0,1,0,0,abc,2]
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

SYSTEM_LOG = dedent(
    """\
    2026-01-15 11:00:06.600  1000  1000  1200 I ActivityTaskManager: Displayed com.example.cold/.Main for user 0: +6s400ms
    2026-01-15 11:15:00.000  1000  1000  1200 I ActivityTaskManager: Displayed com.example.other/.Main: +350ms
    2026-01-15 11:30:00.000  1000  1000  1858 W ActivityManager: Slow operation: 120ms so far, now at startProcess: returned from zygote!
    2026-01-15 11:30:00.001  1000  1000  1858 W ActivityManager: Slow operation: 250ms so far, now at startProcess: done updating pids map
    2026-01-15 11:30:00.002  1000  1000  1858 W ActivityManager: Slow operation: 90ms so far, now at startProcess: asking zygote to start proc
    2026-01-15 11:35:00.000  1000  1000  1858 W ActivityManager: Slow operation: 95ms so far, now at startProcess: returned from zygote!
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

START_INFO = dedent(
    """\
    ACTIVITY MANAGER LRU PROCESSES (dumpsys activity start-info)
    Last Timestamp of Persistence Into Persistent Storage: 15.1.2026 11.00
      package: com.example.slow
        Historical Process Start for userId=0
            ApplicationStartInfo #0:
     pid=0 realUid=10101 packageUid=10101 definingUid=10101 user=0
     package=null process=com.example.slow startupState=2 reason=START ACTIVITY startType=WARM launchMode=0 wasForceStopped=false
     intent=Intent { act=android.intent.action.MAIN cmp=com.example.slow/.Main }
     timestamps: 0=1000000000000 1=1000050000000 4=1002500000000
            ApplicationStartInfo #1:
     pid=0 realUid=10101 packageUid=10101 definingUid=10101 user=0
     package=null process=com.example.slow startupState=0 reason=CONTENT PROVIDER startType=COLD launchMode=0 wasForceStopped=false
     timestamps: 0=5000
      package: com.example.quick
        Historical Process Start for userId=0
            ApplicationStartInfo #0:
     package=null process=com.example.quick startupState=2 reason=LAUNCHER startType=HOT launchMode=0 wasForceStopped=false
     timestamps: 0=2000000000000 4=2000100000000
    """,  # ruff: ignore[line-too-long] - dump lines are long
)


def test_app_launch_times_from_logs(context_factory):
    ctx = context_factory(
        live={"logcat_events": EVENTS_LOG, "logcat_system": SYSTEM_LOG},
        windows=_windows(),
    )
    result = perf.app_launch_times(ctx)
    launches = {r["component"]: r for r in result.tables["launches"]}
    # The Displayed line for com.example.cold repeats the event-log launch.
    assert len(launches) == 3
    assert launches["com.example.cold/.Main"]["start_type"] == "cold"
    assert launches["com.example.cold/.Main"]["ms"] == 6400
    assert launches["com.example.warm/.Main"]["start_type"] == "warm_or_hot"
    assert launches["com.example.other/.Main"]["source"] == "displayed"
    assert result.metrics["cold_launches"] == 1
    assert result.metrics["slow_operation_lines"] == 4
    assert result.metrics["slow_process_starts"] == 3
    assert result.metrics["slow_process_start_max_ms"] == 250
    assert result.metrics["events_log_minutes"] == pytest.approx(22.0)
    ids = _ids(result)
    assert ids == [
        "app_launch_times.slow_launches",
        "app_launch_times.slow_process_starts",
    ]
    slow = result.findings[0]
    assert slow.metrics["slow_launches"] == 1
    assert slow.window == "log_coverage"
    assert slow.evidence[0].ref == "live/logcat_events.txt:3"


def test_app_launch_times_quiet_logs_have_no_findings(context_factory):
    quiet = EVENTS_LOG.replace(",6400]", ",1200]")
    ctx = context_factory(live={"logcat_events": quiet}, windows=_windows())
    result = perf.app_launch_times(ctx)
    assert result.findings == []
    assert result.metrics["launch_ms_max"] == 1200


def test_start_info_reasons_with_spaces_and_first_frame_times():
    info = perf.parse_start_info(Text("si", START_INFO))
    assert info.records == 3
    assert info.histogram == {
        "START_ACTIVITY/WARM": 1,
        "CONTENT_PROVIDER/COLD": 1,
        "LAUNCHER/HOT": 1,
    }
    assert [(x["package"], x["start_type"], x["ms"]) for x in info.launches] == [
        ("com.example.slow", "WARM", 2500),
        ("com.example.quick", "HOT", 100),
    ]


def test_app_launch_times_start_info_finding(context_factory):
    ctx = context_factory(live={"start_info": START_INFO}, windows=_windows())
    result = perf.app_launch_times(ctx)
    assert result.metrics["start_info_warm_max_ms"] == 2500
    assert _ids(result) == ["app_launch_times.start_info_slow"]
    assert result.findings[0].severity == "medium"  # 1 of 2 launches is slow


def test_app_launch_times_skips_without_input(context_factory):
    with pytest.raises(SkipError):
        perf.app_launch_times(context_factory(live={"battery": "level: 50"}))


# --------------------------------------------------------------------------
# battery_saver_state
# --------------------------------------------------------------------------

POWER = dedent(
    """\
    Battery saving stats:
      Battery Saver is currently: OFF
        Last ON time: 2026-01-15 07:00:00.000 -5h0m0s0ms
        Last OFF time: 2026-01-15 11:59:00.000 -1m0s0ms
        Times full enabled: 2
        Times adaptive enabled: 0

      Drain stats:
                         Battery saver OFF                          ON
      NonDoze NonIntr:      0m      0mAh(  0%)      0,0mAh/h         20m     50mAh(  5%)    150,5mAh/h
                 Intr:      0m      0mAh(  0%)      0,0mAh/h         40m    200mAh( 10%)    300,0mAh/h
      Deep    NonIntr:     10m      5mAh(  1%)     30,0mAh/h        300m    400mAh( 20%)     80,0mAh/h
                 Intr:      0m      0mAh(  0%)      0,0mAh/h          0m     20mAh(  0%)   9000,0mAh/h

    Battery saver policy (*NOTE* they only apply when battery saver is ON):
      Policy 'current full'
        disable_launch_boost=true
        force_all_apps_standby=true
        enable_quick_doze=true
        location_mode=3

    Battery saver state machine:
      mSettingBatterySaverEnabledSticky=true
      mSettingBatterySaverStickyAutoDisableEnabled=false
      mLastChangedStrReason=Plugged in
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

SAVER_SETTINGS = dedent(
    """\
    low_power=0
    low_power_sticky=1
    low_power_sticky_auto_disable_enabled=0
    ===SECURE
    low_power_manual_activation_count=12
    ===SYSTEM
    screen_off_timeout=60000
    """,
)


def _charged(pct):
    return dedent(
        f"""\
        Statistics since last charge:
          Time on battery: 5h 0m 0s 0ms (99,0%) realtime
          Power save mode enabled: 4h 30m 0s 0ms ({pct}%)
        """,
    )


def test_power_saver_parse_with_decimal_commas():
    dump = perf.parse_power_saver(Text("power", POWER))
    assert dump.state == "OFF"
    assert dump.last_on == datetime(2026, 1, 15, 7, 0)
    assert dump.times_enabled == {"full": 2, "adaptive": 0}
    assert dump.policies["current full"]["disable_launch_boost"] == "true"
    assert dump.fields["mSettingBatterySaverEnabledSticky"] == "true"
    rows = dump.drain
    assert [r["doze"] for r in rows] == ["NonDoze", "NonDoze", "Deep", "Deep"]
    assert rows[0]["saver_on_mah_per_h"] == pytest.approx(150.5)
    assert rows[2]["saver_off_mah_per_h"] == pytest.approx(30.0)
    # Rates of rows shorter than a few minutes are noise and dropped.
    assert rows[3]["saver_on_mah_per_h"] is None


def test_power_saver_parse_with_decimal_points():
    dump = perf.parse_power_saver(Text("power", POWER.replace(",0mAh/h", ".0mAh/h")))
    assert dump.drain[1]["saver_on_mah_per_h"] == pytest.approx(300.0)


@pytest.mark.parametrize("pct", ["90,0", "90.0"])
def test_battery_saver_mostly_on_fires(context_factory, pct):
    ctx = context_factory(
        live={
            "power": POWER,
            "settings": SAVER_SETTINGS,
            "batterystats_charged": _charged(pct),
            "logcat_events": EVENTS_LOG,
        },
        windows=_windows(on_battery_at_capture=False),
    )
    result = perf.battery_saver_state(ctx)
    assert result.metrics["saver_on_battery_pct"] == pytest.approx(90.0)
    assert result.metrics["setting_low_power_manual_activation_count"] == "12"
    assert result.metrics["policy_disable_launch_boost"] == "true"
    assert result.metrics["drain_saver_on_share_pct_since_boot"] == pytest.approx(
        97.3,
    )
    assert result.metrics["log_saver_turned_off"] == 1
    assert result.metrics["log_saver_turned_on"] == 1
    assert result.metrics["log_saver_events_plugged_in"] == 1
    assert result.metrics["log_saver_events_manual_on"] == 1
    assert _ids(result) == ["battery_saver_state.mostly_on"]
    finding = result.findings[0]
    assert finding.basis == "measured"
    assert finding.window == "on_battery"
    assert "switched on by hand 12 times" in finding.summary
    assert finding.evidence[0].ref == "live/batterystats_charged.txt:3"
    # The capture state is noted, but the finding is about the battery period.
    assert "external power" not in finding.summary
    assert any("external power" in n for n in result.notes)


def test_battery_saver_rarely_on_has_no_finding(context_factory):
    ctx = context_factory(
        live={"power": POWER, "batterystats_charged": _charged("12,5")},
    )
    result = perf.battery_saver_state(ctx)
    assert result.metrics["saver_on_battery_pct"] == pytest.approx(12.5)
    assert result.findings == []


def test_battery_saver_coverage_inferred_without_batterystats(context_factory):
    ctx = context_factory(
        live={"power": POWER},
        windows=_windows(
            since_charge_start=datetime(2026, 1, 15, 7, 0, 30),
            plugged_at=datetime(2026, 1, 15, 11, 59, 30),
        ),
    )
    result = perf.battery_saver_state(ctx)
    assert result.metrics["saver_on_battery_pct"] == 100
    assert result.findings[0].basis == "inferred"


def test_battery_saver_skips_without_input(context_factory):
    with pytest.raises(SkipError):
        perf.battery_saver_state(context_factory(live={"battery": "level: 50"}))


# --------------------------------------------------------------------------
# settings_audit
# --------------------------------------------------------------------------

AUDIT_SETTINGS = dedent(
    """\
    always_finish_activities=1
    animator_duration_scale=1.5
    ble_scan_always_enabled=1
    transition_animation_scale=1.0
    wifi_scan_always_enabled=1
    window_animation_scale=1.0
    ===SECURE
    enabled_input_methods=com.example.ime/.Svc:com.example.ime2/.Svc;123
    selected_search_engine={
      "name": "Example"
    }
    ===SYSTEM
    screen_off_timeout=1800000
    """,
)


def test_settings_audit_flags(context_factory):
    result = perf.settings_audit(context_factory(live={"settings": AUDIT_SETTINGS}))
    ids = _ids(result)
    assert ids == [
        "settings_audit.animation",
        "settings_audit.always_finish_activities",
        "settings_audit.scanning",
        "settings_audit.screen_timeout",
    ]
    by_id = {f.id: f for f in result.findings}
    assert by_id["settings_audit.always_finish_activities"].severity == "high"
    assert by_id["settings_audit.scanning"].basis == "inferred"
    assert set(by_id["settings_audit.scanning"].metrics) == {
        "wifi_scan_always_enabled",
        "ble_scan_always_enabled",
    }
    assert result.metrics["enabled_input_methods_count"] == 2
    assert result.tables["settings"][0]["verdict"].startswith("flag")


def test_settings_audit_animations_off_is_not_a_problem(context_factory):
    text = "animator_duration_scale=0,0\nwindow_animation_scale=0.0\n"
    result = perf.settings_audit(context_factory(live={"settings": text}))
    assert result.findings == []
    assert any("not a slowness cause" in n for n in result.notes)
    assert any("not marked" in n for n in result.notes)


DUMPSYS_SETTINGS = dedent(
    """\
    CONFIG SETTINGS (user 0)
    _id:1 name:example/flag pkg:com.example value:true
    GLOBAL SETTINGS (user 0)
    _id:10 name:ble_scan_always_enabled pkg:com.example.gms value:1 default:0
    _id:11 name:debug_app pkg:android value:{null}
    _id:12 name:low_power_sticky pkg:android value:1 default:1 defaultSystemSet:true
    _id:13 name:low_power_sticky_auto_disable_enabled pkg:android value:0
    _id:14 name:app_standby_enabled pkg:com.example.gms value:0 isValuePreservedInRestore:true
    SECURE SETTINGS (user 0)
    _id:20 name:low_power_manual_activation_count pkg:android value:12
    _id:21 name:default_input_method pkg:com.example.ime value:com.example.ime/.Ime
    SYSTEM SETTINGS (user 0)
    _id:30 name:screen_off_timeout pkg:android value:60000
    """,  # ruff: ignore[line-too-long] - dump lines are long
)


def test_settings_from_a_bugreport_only_workdir(context_factory):
    """Without live/settings.txt, dumpsys settings in the bugreport is used."""
    ctx = context_factory(
        live={"batterystats_charged": _charged("90,0")},
        services={"settings": DUMPSYS_SETTINGS, "power": POWER},
    )
    audit = perf.settings_audit(ctx)
    assert _ids(audit) == ["settings_audit.standby", "settings_audit.scanning"]
    refs = [e.ref for f in audit.findings for e in f.evidence]
    assert all(r.startswith("bugreport:dumpsys settings:") for r in refs)
    # Samsung restore flags and AOSP's {null} are not part of the value.
    assert audit.metrics["app_standby_enabled"] == "0"
    assert audit.metrics["debug_app"] is None
    assert perf.key_packages(ctx)["com.example.ime"] == "keyboard"
    saver = perf.battery_saver_state(ctx)
    summary = saver.findings[0].summary
    assert "with auto-disable off" in summary
    assert "switched on by hand 12 times" in summary


def test_settings_audit_skips_without_settings(context_factory):
    with pytest.raises(SkipError):
        perf.settings_audit(context_factory(live={"battery": "level: 50"}))


# --------------------------------------------------------------------------
# thermal_status
# --------------------------------------------------------------------------

THERMAL = dedent(
    """\
    IsStatusOverride: false
    Thermal Status: 3
    Cached temperatures:
        Temperature{mValue=41.5, mType=3, mName=skin, mStatus=3}
        Temperature{mValue=60.0, mType=0, mName=CPU0, mStatus=0}
        Temperature{mValue=3.9, mType=6, mName=vbat, mStatus=0}
    HAL Ready: true
    Current temperatures from HAL:
        Temperature{mValue=38.0, mType=3, mName=skin, mStatus=3}
        Temperature{mValue=45.0, mType=0, mName=CPU0, mStatus=0}
    Current cooling devices from HAL:
        CoolingDevice{mValue=0, mType=2, mName=example-cpu-cooling-a}
        CoolingDevice{mValue=0, mType=2, mName=example-cpu-cooling-b}
    Temperature static thresholds from HAL:
        TemperatureThreshold{mType=3, mName=skin, mHotThrottlingThresholds=[NaN, NaN, NaN, 39.5, NaN, NaN, 91.0], mColdThrottlingThresholds=[NaN, NaN, NaN, NaN, NaN, NaN, NaN]}
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

JOBSCHEDULER = dedent(
    """\
    Thermal status: 3
      JOB #1000/2: 1a2b3c android/com.android.server.art.BackgroundDexoptJobService
        Last successful run: 2026-01-10 00:30:00
        Last failed run: 2026-01-12 00:30:00
        Restricted due to: thermal.
      JOB #1000/3: 4d5e6f com.example.app/.SyncJob
        Last successful run: 2026-01-15 11:00:00
        Restricted due to: thermal.
      JOB #1000/4: 7a8b9c com.example.app/.OtherJob
        Restricted due to: none.
    """,
)

ZONES = dedent(
    """\
    cpu-0-0-usr 45000
    skin-therm 38500
    pm-bcl-lvl0 -274000
    soc 84
    modem-mmw0-usr -273000
    broken
    """,
)


def test_parse_thermalservice():
    dump = perf.parse_thermalservice(Text("thermal", THERMAL))
    assert dump.status == 3
    skin = [s for s in dump.sensors if s["name"] == "skin"]
    assert [(s["source"], s["value"], s["status"]) for s in skin] == [
        ("cached", 41.5, 3),
        ("current", 38.0, 3),
    ]
    vbat = next(s for s in dump.sensors if s["name"] == "vbat")
    assert vbat["is_temperature"] is False
    assert dump.thresholds["skin"] == {"SEVERE": 39.5, "SHUTDOWN": 91.0}
    assert len(dump.cooling) == 2


@pytest.mark.parametrize(
    ("on_battery", "severity"),
    [(None, "medium"), (False, "low")],
)
def test_thermal_status_severe(context_factory, on_battery, severity):
    ctx = context_factory(
        live={
            "thermalservice": THERMAL,
            "jobscheduler": JOBSCHEDULER,
            "thermal_zones": ZONES,
            "logcat_events": EVENTS_LOG,
        },
        windows=_windows(on_battery_at_capture=on_battery),
    )
    result = perf.thermal_status(ctx)
    assert result.metrics["thermal_status_name"] == "SEVERE"
    assert result.metrics["jobs_restricted_thermal"] == 2
    assert result.tables["job_restrictions"] == [
        {"reason": "thermal", "jobs": 2},
        {"reason": "none", "jobs": 1},
    ]
    assert result.metrics["thermal_log_events"] == 1
    assert result.metrics["current_skin_max_c"] == pytest.approx(38.0)
    assert result.metrics["hottest_zone"] == "cpu-0-0-usr"
    assert [z["zone"] for z in result.tables["thermal_zones"]] == [
        "cpu-0-0-usr",
        "skin-therm",
    ]
    assert _ids(result) == ["thermal_status.elevated"]
    finding = result.findings[0]
    assert finding.severity == severity
    assert "hysteresis" in finding.summary
    assert "trip 39.5" in finding.summary
    refs = [e.ref for e in finding.evidence]
    assert "live/thermalservice.txt:2" in refs
    assert "live/logcat_events.txt:5" in refs


def test_thermal_status_normal_and_cpu_cap(context_factory):
    calm = THERMAL.replace("Thermal Status: 3", "Thermal Status: 0").replace(
        "mStatus=3",
        "mStatus=0",
    )
    cpufreq = dedent(
        """\
        /sys/devices/system/cpu/cpu0/cpufreq 1000000 300000 1800000 1800000
        /sys/devices/system/cpu/cpu6/cpufreq 1200000 300000 1200000 2200000
        """,
    )
    ctx = context_factory(live={"thermalservice": calm, "cpufreq": cpufreq})
    result = perf.thermal_status(ctx)
    assert result.metrics["cpus_capped"] == 1
    assert _ids(result) == ["thermal_status.cpu_frequency_capped"]


def test_thermal_status_log_only_event(context_factory):
    calm = THERMAL.replace("Thermal Status: 3", "Thermal Status: 0")
    ctx = context_factory(
        live={"thermalservice": calm, "logcat_events": EVENTS_LOG},
        windows=_windows(),
    )
    assert _ids(perf.thermal_status(ctx)) == ["thermal_status.log_events"]


def test_thermal_status_skips_without_input(context_factory):
    with pytest.raises(SkipError):
        perf.thermal_status(context_factory(live={"battery": "level: 50"}))


# --------------------------------------------------------------------------
# storage_io_per_uid
# --------------------------------------------------------------------------

GIB = 1024**3
STORAGED = dedent(
    f"""\
    name/uid fg_rchar fg_wchar fg_rbytes fg_wbytes bg_rchar bg_wchar bg_rbytes bg_wbytes fg_fsync bg_fsync
    com.example.churn 0 0 0 0 {GIB} 0 {8 * GIB} {GIB // 10} 0 30000
    com.example.fine 0 0 0 0 {10 * GIB} 0 {GIB} 0 0 10
    shared:android.uid.system {4 * GIB} 0 {6 * GIB} 0 0 0 0 0 50000 0
    1010 100 0 4096 0 0 0 0 0 0 0
    something unexpected
    I/O perf history (KB/s) :  most_recent  <---------  least_recent
    last 24 hours : 100 200 300
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

DISKSTATS = dedent(
    """\
    Latency: 120ms [512B Data Write]
    Recent Disk Write Speed (kB/s) = 1000
    Data-Free: 1000000K / 64000000K total = 1% free
    Package Names: ["com.example.a","com.example.b"]
    App Sizes: [100,200]
    App Data Sizes: [1000,2000000000]
    Cache Sizes: [10,20]
    """,
)


def test_storage_io_per_uid_since_boot(context_factory):
    ctx = context_factory(
        sections={"STORAGED IO INFO (storaged -u -p)": STORAGED},
        packages="package:com.example.wifi uid:1010\n",
        windows=_windows(boot_time=DUMP_TIME - timedelta(hours=1)),
    )
    result = perf.storage_io_per_uid(ctx)
    assert result.metrics["total_uids"] == 4
    assert result.metrics["total_read_gib"] == pytest.approx(15.0)
    assert result.metrics["total_read_call_gib"] == pytest.approx(15.0)
    assert result.metrics["total_read_ratio"] == pytest.approx(1.0)
    rows = {r["name"]: r for r in result.tables["per_uid"]}
    assert rows["com.example.churn"]["read_ratio"] == pytest.approx(8.0)
    assert rows["com.example.churn"]["fsync_per_day"] == 720_000
    assert "wifi" in rows  # system UIDs keep their well-known name
    # Flash reads since boot are vmstat_reclaim_io's finding; only metrics here.
    assert _ids(result) == [
        "storage_io_per_uid.app_page_cache_churn",
        "storage_io_per_uid.fsync_heavy",
    ]
    by_id = {f.id: f for f in result.findings}
    assert by_id["storage_io_per_uid.app_page_cache_churn"].metrics["apps"] == [
        "com.example.churn",
    ]
    # The platform UID is not an app, so it is not blamed for fsync calls.
    assert by_id["storage_io_per_uid.fsync_heavy"].metrics["apps"] == [
        "com.example.churn",
    ]
    assert by_id["storage_io_per_uid.fsync_heavy"].window == "since_boot"
    assert any("1 unrecognised lines" in n for n in result.notes)


def test_storage_io_per_uid_right_after_boot(context_factory):
    """Minutes after boot, boot reads are not churn: no rates, no findings."""
    ctx = context_factory(
        sections={"STORAGED IO INFO (storaged -u -p)": STORAGED},
        windows=_windows(boot_time=DUMP_TIME - timedelta(minutes=10)),
    )
    result = perf.storage_io_per_uid(ctx)
    assert result.findings == []
    assert result.metrics["total_read_gib"] == pytest.approx(15.0)
    assert result.metrics["total_read_mib_s"] is None
    assert "read_gib_per_day" not in result.tables["per_uid"][0]
    assert any("Captured 10 min after boot" in n for n in result.notes)


def test_storage_io_per_uid_quiet_day(context_factory):
    ctx = context_factory(
        sections={"STORAGED IO INFO (storaged -u -p)": STORAGED},
        windows=_windows(boot_time=DUMP_TIME - timedelta(days=30)),
    )
    result = perf.storage_io_per_uid(ctx)
    assert result.findings == []


def test_storage_io_per_uid_diskstats_and_intervals(context_factory):
    intervals = dedent(
        """\
        1768442400,1768446000
        com.example.a 0 0 100 0 0 0 0 0
        """,
    )
    ctx = context_factory(
        live={"diskstats": DISKSTATS},
        services={"storaged": intervals},
        windows=_windows(
            boot_time=datetime(2026, 1, 15, 4, 0),
            utc_offset="+0200",
        ),
    )
    result = perf.storage_io_per_uid(ctx)
    assert result.metrics["data_free_pct"] == 1
    assert result.metrics["write_latency_ms"] == 120
    assert result.metrics["storaged_intervals"] == 1
    # The interval ends at 03:00 UTC; boot was 04:00 local = 02:00 UTC.
    assert result.metrics["storaged_intervals_cover_this_boot"] is True
    assert result.tables["app_storage"][0]["package"] == "com.example.b"
    assert _ids(result) == [
        "storage_io_per_uid.low_free_space",
        "storage_io_per_uid.slow_writes",
    ]


def test_storage_io_per_uid_skips_without_input(context_factory):
    with pytest.raises(SkipError):
        perf.storage_io_per_uid(context_factory(live={"battery": "level: 50"}))


# --------------------------------------------------------------------------
# dexopt_status
# --------------------------------------------------------------------------

PACKAGE_DUMP = dedent(
    """\
    Packages:
      Package [com.example.app] (1a2b3c):
        userId=10101

    Dexopt state:
      [com.android.systemui]
        path: /system_ext/priv-app/SystemUI/SystemUI.apk
          arm64: [status=verify] [reason=install] [primary-abi]
      [com.example.launcher]
        path: /data/app/~~abc==/com.example.launcher-xyz==/base.apk
          arm64: [status=speed-profile] [reason=bg-dexopt] [primary-abi]
            [location is /data/app/~~abc==/com.example.launcher-xyz==/oat/arm64/base.odex]
        path: /data/app/~~abc==/com.example.launcher-xyz==/split.apk
          arm64: [status=verify] [reason=bg-dexopt] [primary-abi]
      [com.example.rare]
        path: /data/app/~~def==/com.example.rare-uvw==/base.apk
          arm64: [status=run-from-apk] [reason=unknown] [primary-abi]
      [com.example.resources]

    Compiler stats:
      [com.example.app]
    """,  # ruff: ignore[line-too-long] - dump lines are long
)


def test_parse_dexopt_primary_status_only():
    rows, timed_out = perf.parse_dexopt(Text("package", PACKAGE_DUMP))
    assert not timed_out
    assert [(r["package"], r["status"]) for r in rows] == [
        ("com.android.systemui", "verify"),
        ("com.example.launcher", "speed-profile"),
        ("com.example.rare", "run-from-apk"),
    ]


def test_dexopt_status_findings(context_factory):
    ctx = context_factory(
        live={
            "jobscheduler": JOBSCHEDULER,
            "home_activity": "com.example.launcher/.Home\n",
            "ps": "PID PPID USER RSS VSZ TIME S NAME\n42 1 root 1 1 0 S dex2oat64\n",
        },
        services={"package": PACKAGE_DUMP},
        windows=_windows(),
    )
    result = perf.dexopt_status(ctx)
    assert result.tables["compiler_filters"] == [
        {"location": "system", "filter": "verify", "packages": 1},
        {"location": "data", "filter": "speed-profile", "packages": 1},
        {"location": "data", "filter": "run-from-apk", "packages": 1},
    ]
    assert result.metrics["data_apps_uncompiled"] == 1
    assert result.metrics["bg_dexopt_last_success"] == "2026-01-10 00:30:00"
    assert result.metrics["bg_dexopt_days_since_success"] == pytest.approx(5.5)
    assert result.metrics["dex2oat_processes_at_capture"] == 1
    assert _ids(result) == [
        "dexopt_status.key_apps_uncompiled",
        "dexopt_status.background_dexopt_stale",
    ]
    uncompiled = result.findings[0]
    assert uncompiled.metrics["packages"] == ["com.android.systemui"]
    assert uncompiled.evidence[0].ref.startswith("bugreport:dumpsys package:")


def test_dexopt_status_recent_job_and_compiled_apps(context_factory):
    jobs = JOBSCHEDULER.replace("2026-01-10 00:30:00", "2026-01-14 23:00:00")
    dump = PACKAGE_DUMP.replace("[status=verify] [reason=install]", "[status=speed]")
    ctx = context_factory(
        live={"jobscheduler": jobs, "package_dexopt": dump},
        windows=_windows(),
    )
    result = perf.dexopt_status(ctx)
    assert result.findings == []


def test_parse_dexopt_live_dump_with_header_first():
    live = PACKAGE_DUMP[PACKAGE_DUMP.index("Dexopt state:") :]
    live += "*** SERVICE 'package' DUMP TIMEOUT (10000ms) EXPIRED ***\n"
    rows, timed_out = perf.parse_dexopt(Text("live", live))
    assert len(rows) == 3
    assert timed_out


def test_dexopt_status_skips_without_input(context_factory):
    with pytest.raises(SkipError):
        perf.dexopt_status(context_factory(live={"battery": "level: 50"}))


# --------------------------------------------------------------------------
# build_identity
# --------------------------------------------------------------------------

GETPROP = dedent(
    """\
    [persist.sys.boot.reason.history]: [reboot,userrequested,1768392000
    shutdown,battery,1768305600]
    [ro.build.display.id]: [TEST.1.0]
    [ro.build.fingerprint]: [Example/product/device:16/TEST.1.0/1:user/release-keys]
    [ro.build.version.release]: [16]
    [ro.build.version.sdk]: [36]
    [ro.build.version.security_patch]: [2025-12-05]
    [ro.kernel.version]: [5.10]
    [ro.serialno]: [0123456789ab]
    [ro.vendor.api_level]: [31]
    [ro.vendor.build.version.release]: [12]
    """,
)

ROLLBACK = dedent(
    """\
    333:
      -state: available
      -stateDescription:
      -timestamp: 2026-01-05T08:00:00.123Z
    Historical rollbacks:
      111:
        -state: deleted
        -stateDescription: Fingerprint changed
        -timestamp: 2025-12-20T10:00:00.123456Z
      222:
        -state: deleted
        -stateDescription: Fingerprint changed
        -timestamp: 2079-05-04T01:02:03.000004Z
      444:
        -state: deleted
        -stateDescription: Fingerprint changed
        -timestamp: 2025-11-01T10:00:00Z
    """,
)


def test_parse_getprop_multiline_values():
    props = perf.parse_getprop(Text("getprop", GETPROP))
    history = props["persist.sys.boot.reason.history"][0]
    assert history.splitlines() == [
        "reboot,userrequested,1768392000",
        "shutdown,battery,1768305600",
    ]
    assert props["ro.build.version.sdk"] == ("36", 5)


def test_build_identity(context_factory):
    ctx = context_factory(
        live={"getprop": GETPROP},
        services={"rollback": ROLLBACK},
        members={
            "FS/data/misc/update_engine_log/update_engine.20260101-120000": (
                "[0101/120000.000000] [INFO:update_attempter_android.cc(224)] "
                "OTAResult::OTA_SUCCESSFUL\n"
            ),
        },
        windows=_windows(),
    )
    result = perf.build_identity(ctx)
    m = result.metrics
    assert m["android_release"] == "16"
    assert m["vendor_api_level"] == "31"
    assert m["security_patch_age_days"] == 41
    # The 2079 stamp comes from an unset clock and is ignored.
    assert m["ota_after_utc"] == "2025-12-20T10:00:00.123456Z"
    assert m["ota_before_utc"] == "2026-01-05T08:00:00.123Z"
    assert m["ota_success_log"] == "20260101-120000"
    # Boot reasons are low_battery_shutdowns' table, not repeated here.
    assert "boot_reasons" not in result.tables
    assert _ids(result) == ["build_identity.build", "build_identity.old_vendor_image"]
    assert result.findings[0].severity == "info"
    assert result.findings[1].basis == "inferred"
    # Serial numbers never reach the output.
    assert "0123456789ab" not in json.dumps(result.to_dict(), default=str)


def test_build_identity_without_vendor_gap(context_factory):
    text = GETPROP.replace("[ro.vendor.api_level]: [31]", "[ro.vendor.api_level]: [35]")
    result = perf.build_identity(context_factory(live={"getprop": text}))
    assert _ids(result) == ["build_identity.build"]


def test_build_identity_skips_without_input(context_factory):
    with pytest.raises(SkipError):
        perf.build_identity(context_factory(live={"battery": "level: 50"}))


def test_followups_never_run_raw_adb():
    """Follow-ups go through adb_ro.py, which refuses state-changing commands."""
    source = inspect.getsource(perf)
    assert "adb shell" not in source
    assert "adb logcat" not in source
