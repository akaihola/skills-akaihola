"""Tests for the CPU analyzers, on invented dumps."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from textwrap import dedent

import pytest
from androiddiag import cpu
from androiddiag.model import Finding, Result, SkipError, Windows

DUMP = datetime(2026, 1, 15, 12, 0, 0)
WINDOWS = Windows(
    dump_time=DUMP,
    boot_time=DUMP - timedelta(hours=20),
    since_charge_start=DUMP - timedelta(hours=5, minutes=5),
    on_battery_at_capture=False,
    on_battery_s=18_000.0,
    screen_off_on_battery_s=14_400.0,
    plugged_at=datetime(2026, 1, 15, 11, 10, 0, 500_000),
)

PS = dedent(
    """\
      PID  PPID USER            RSS     VSZ     TIME S NAME
        1     0 root           3210  9876540 00:00:29 S init
       40     2 root              0        0 00:00:50 S [migration/3]
       41     2 root              0        0 00:00:40 S [migration/4]
       90     2 root              0        0 00:05:12 S [kswapd0]
      510     1 root           2100  9812340 00:14:00 S ueventd
      650     1 system         2050  9900120 00:27:10 S android.system.suspend-service
     1210     1 system        21000 10500300 00:15:15 S surfaceflinger
     1300   880 system       120000 18000400 00:48:20 S system_server
     1500     1 system         3000  9700200 00:15:06 S cnss_diag
     8400   880 u0_a101       90000   900000 00:11:22 S com.example.app
    """,
)

BATTERYSTATS = dedent(
    """\
    Discharge step durations:
      #0: +4m50s100ms to 81 (power-save-on, device-idle-off)

    Statistics since last charge:
      Time on battery: 5h 0m 0s 0ms (99,1%) realtime, 3h 0m 0s 0ms (60,0%) uptime
      Estimated power use (mAh):
        Capacity: 3000, Computed drain: 500, actual drain: 500-520
        UID 0: 30,5 ( cpu=24,0 wakelock=0,2 )
        UID 1000: 40,2 fg: 0,1 ( cpu=36,0 cpu:fg=1,0 )
        UID u0a101: 5,1 ( cpu=2,5 )

      All wakeup reasons:
      Wakeup reason Abort: Pending Wakeup Sources: example_ws: 1h 0m 0s 0ms (6000 times) realtime
      Wakeup reason 41 WLAN_IRQ: 30m 0s 0ms (4000 times) realtime

      CPU scaling:  policy0: 300000 1000000 policy4: 500000 2000000
      0:
        Total cpu time: u=13m 0s 0ms s=17m 0s 0ms
        Total cpu time per freq: 100000 200000 300000 400000
        Total screen-off cpu time per freq: 90000 180000 270000 360000
        Proc kworker/u16:1-events_unbound:
          CPU: 0ms usr + 1m 0s 0ms krn ; 0ms fg
        Proc kworker/u16:2-events_unbound:
          CPU: 0ms usr + 30s 0ms krn ; 0ms fg
        Proc migration/0:
          CPU: 0ms usr + 5s 0ms krn ; 0ms fg
        Proc ueventd:
          CPU: 12m 0s 0ms usr + 1m 0s 0ms krn ; 0ms fg
      1000:
        Total cpu time: u=20m 0s 0ms s=40m 0s 0ms
        Total cpu time per freq: 1000000 1000000 1000000 600000
        Total screen-off cpu time per freq: 900000 900000 900000 500000
        Proc android.system.suspend-service:
          CPU: 6s 0ms usr + 26m 0s 0ms krn ; 0ms fg
        Proc cnss_diag:
          CPU: 7m 0s 0ms usr + 1m 0s 0ms krn ; 0ms fg
        Proc system:
          CPU: 6m 0s 0ms usr + 3m 0s 0ms krn ; 0ms fg
        Proc quiet_daemon:
          CPU: 10s 0ms usr + 5s 0ms krn ; 0ms fg
      u0a101:
        Wi-Fi network: 4,52MB received, 1,00MB sent (packets 4000 received, 900 sent)
        Total cpu time: u=1m 0s 0ms s=30s 0ms
        Total cpu time per freq: 20000 20000 20000 40000
        Total screen-off cpu time per freq: 50000 50000 30000 20000
        Proc com.example.app:
          CPU: 1m 0s 0ms usr + 30s 0ms krn ; 10s 0ms fg
          6 starts, 1 crashes
          * Killed for cpu use: +6s100ms over +5m0s200ms (2%)
          * Killed for cpu use: +7s800ms over +5m0s300ms (2%)
          * Killed for cpu use: +9s700ms over +5m0s100ms (3%)
        Apk com.example.app:
          Wakeup alarm *walarm*:example: 0 times
      u0a102:
        Total cpu time: u=1s 0ms s=1s 0ms
        Total cpu time per freq: 1000 1000 0 0
        Total screen-off cpu time per freq: 0 0 0 0
        Proc com.example.other:
          CPU: 1s 0ms usr + 1s 0ms krn ; 0ms fg
          * Killed for cpu use: +6s0ms over +5m0s0ms (2%)

    Per process state tracking available: true
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

PACKAGES = "package:com.example.app uid:10101\npackage:com.example.other uid:10102\n"


def _ctx(context_factory, windows=WINDOWS, **live):
    return context_factory(live=live, packages=PACKAGES, windows=windows)


def _finding(result, suffix):
    found = [f for f in result.findings if f.id.endswith(suffix)]
    return found[0] if found else None


@pytest.mark.parametrize(
    ("name", "group"),
    [
        ("kworker/u16:3-events_unbound", "kworker:events_unbound"),
        ("[kworker/0:6H-cpuboost_wq]", "kworker:cpuboost_wq"),
        ("kworker/1:2", "kworker:(none)"),
        ("[migration/3]", "migration/*"),
        ("[kswapd-1:0]", "kswapd-1:0"),
        ("ueventd", "ueventd"),
    ],
)
def test_kernel_group(name, group):
    assert cpu.kernel_group(name) == group


@pytest.mark.parametrize(
    ("start", "end", "state"),
    [
        ("11:00:00", None, "on_battery"),
        ("11:10:00.400", None, "on_battery"),
        ("11:10:00.600", None, "charging"),
        ("11:09:30", "11:10:30", "mixed"),
        ("06:50:00", None, "unknown"),  # before the last full charge
        ("06:50:00", "07:00:00", "mixed"),
    ],
)
def test_power_state(start, end, state):
    def at(clock):
        return datetime.fromisoformat(f"2026-01-15 {clock}") if clock else None

    assert cpu.power_state(WINDOWS, at(start), at(end)) == state


def test_power_state_unknown_plug_state():
    windows = replace(WINDOWS, on_battery_at_capture=None)
    assert cpu.power_state(windows, datetime(2026, 1, 15, 11, 0)) == "unknown"
    on_battery = replace(WINDOWS, on_battery_at_capture=True, plugged_at=None)
    assert cpu.power_state(on_battery, datetime(2026, 1, 15, 11, 30)) == "on_battery"
    # A plug-in time after the capture comes from a broken history clock.
    future = replace(WINDOWS, plugged_at=DUMP + timedelta(days=200))
    assert cpu.power_state(future, datetime(2026, 1, 15, 11, 30)) == "unknown"


def test_process_cpu_since_boot_ranks_and_flags_busy_daemons(context_factory):
    result = cpu.process_cpu_since_boot(_ctx(context_factory, ps=PS))
    assert result.metrics["processes"] == 10
    assert result.metrics["core_daemons_restarted"] == 0
    top = result.tables["processes"][0]
    assert (top["process"], top["cpu_s"]) == ("system_server", 2900.0)
    groups = {g["group"]: g for g in result.tables["kernel_thread_groups"]}
    assert groups["migration/*"]["threads"] == 2
    assert groups["migration/*"]["cpu_s"] == pytest.approx(90.0)
    busy = _finding(result, "busy-daemons")
    assert busy is not None
    assert set(busy.metrics) == {
        "android.system.suspend-service",
        "ueventd",
        "cnss_diag",
    }
    assert busy.window == "since_boot"
    assert _finding(result, "core-daemon-restarted") is None
    assert all("adb shell" not in f for f in busy.followups)


def test_process_cpu_since_boot_leaves_reported_daemons_to_churn(context_factory):
    stats = BATTERYSTATS.replace("Proc cnss_diag:", "Proc other_logger:")
    ctx = _ctx(context_factory, ps=PS, batterystats_charged=stats)
    ctx.results["system_process_cpu_churn"] = cpu.system_process_cpu_churn(ctx)
    result = cpu.process_cpu_since_boot(ctx)
    assert result.metrics["busy_daemons"] == 3
    busy = _finding(result, "busy-daemons")
    assert set(busy.metrics) == {"cnss_diag"}
    assert busy.related == [
        "system_process_cpu_churn.android-system-suspend-service",
        "system_process_cpu_churn.ueventd",
    ]
    assert "2 more are reported" in busy.summary


def test_process_cpu_since_boot_detects_restarted_daemon(context_factory):
    ps = PS.replace("1210     1 system", "23456     1 system")
    result = cpu.process_cpu_since_boot(_ctx(context_factory, ps=ps))
    finding = _finding(result, "core-daemon-restarted")
    assert finding is not None
    assert finding.metrics["restarted"] == ["surfaceflinger"]
    assert finding.severity == "high"
    assert finding.evidence[0].ref.startswith("live/ps.txt:")


def test_process_cpu_since_boot_skips_without_time_column(context_factory):
    ps = "  PID USER NAME\n    1 root init\n"
    with pytest.raises(SkipError):
        cpu.process_cpu_since_boot(_ctx(context_factory, ps=ps))


def test_battery_proc_cpu_groups_kernel_threads_and_models_mah(context_factory):
    result = cpu.battery_proc_cpu(
        _ctx(context_factory, batterystats_charged=BATTERYSTATS),
    )
    rows = {r["process"]: r for r in result.tables["processes"]}
    suspend = rows["android.system.suspend-service"]
    assert suspend["usr_s"] == pytest.approx(6.0)
    assert suspend["krn_s"] == pytest.approx(1560.0)
    assert suspend["core_pct_on_battery"] == pytest.approx(8.7)
    # UID 1000: 36.0 mAh (decimal comma) over 3600 s of CPU = 0.01 mAh/s.
    assert result.metrics["uid_1000_mah_per_cpu_s"] == pytest.approx(0.01)
    assert suspend["modelled_cpu_mah"] == pytest.approx(15.66)
    assert rows["kworker:events_unbound"]["entries"] == 2
    assert rows["kworker:events_unbound"]["cpu_s"] == pytest.approx(90.0)
    assert result.metrics["uid_0_cpu_s"] == pytest.approx(1800.0)
    assert rows["com.example.app"]["uid_name"] == "com.example.app"
    assert result.tables["uids"][0]["name"] == "system"


def test_battery_proc_cpu_tables_kills_without_a_finding(context_factory):
    # exit_info_audit owns the finding about kills for excessive CPU.
    result = cpu.battery_proc_cpu(
        _ctx(context_factory, batterystats_charged=BATTERYSTATS),
    )
    assert _finding(result, "killed-for-cpu-use") is None
    killed = result.tables["killed_for_cpu"]
    assert result.metrics["killed_for_cpu_events"] == len(killed) == 4
    assert killed[0]["process"] == "com.example.app"
    assert killed[0]["used_s"] == pytest.approx(6.1)
    assert killed[0]["pct"] == 2


def test_battery_proc_cpu_reads_past_three_space_uid_lines(context_factory):
    # Android 10-11 indent this line by three spaces inside a UID block.
    stats = BATTERYSTATS.replace(
        "    Proc android.system.suspend-service:",
        "   Screen-off cpu times per freq at state Cached: 1 2 3 4\n"
        "    Proc android.system.suspend-service:",
    )
    result = cpu.battery_proc_cpu(_ctx(context_factory, batterystats_charged=stats))
    processes = {r["process"] for r in result.tables["processes"]}
    assert {"android.system.suspend-service", "cnss_diag"} <= processes
    assert result.metrics["killed_for_cpu_events"] == 4


def test_battery_proc_cpu_falls_back_to_full_dump(context_factory):
    full = "Daily stats:\n  Current start time: x\n" + BATTERYSTATS
    result = cpu.battery_proc_cpu(_ctx(context_factory, batterystats=full))
    assert result.metrics["uid_1000_cpu_s"] == pytest.approx(3600.0)


def test_battery_proc_cpu_skips_without_batterystats(context_factory):
    with pytest.raises(SkipError):
        cpu.battery_proc_cpu(_ctx(context_factory, ps=PS))


def test_screen_off_cpu_by_uid_core_share(context_factory):
    ctx = _ctx(context_factory, batterystats_charged=BATTERYSTATS)
    ctx.packages = replace(ctx.packages, third_party=frozenset({10101}))
    result = cpu.screen_off_cpu_by_uid(ctx)
    m = result.metrics
    assert m["core_screen_off_cpu_s"] == pytest.approx(4100.0)
    assert m["apps_screen_off_cpu_s"] == pytest.approx(150.0)
    assert m["core_share_pct"] == pytest.approx(96.5, abs=0.1)
    assert m["cpu_policies"] == "policy0:2x1000000kHz policy4:2x2000000kHz"
    rows = {r["uid"]: r for r in result.tables["uids"]}
    assert rows["u0a101"]["class"] == "third_party"
    assert rows["u0a102"]["class"] == "preinstalled_app"
    assert rows["u0a101"]["top_step_share_pct"] == pytest.approx(40.0)
    assert [r["uid"] for r in result.tables["top_step_heavy"]] == ["u0a101"]
    core = _finding(result, "core-dominated")
    assert core is not None
    assert core.severity == "medium"  # 4260 s in 4 h is far above idle
    busy = _finding(result, "busy-background-apps")
    assert busy is not None
    assert busy.metrics == {"u0a101": 37.5}


def test_screen_off_cpu_by_uid_no_findings_when_apps_dominate(context_factory):
    quiet = BATTERYSTATS.replace(
        "Total screen-off cpu time per freq: 90000 180000 270000 360000",
        "Total screen-off cpu time per freq: 1000 0 0 0",
    ).replace(
        "Total screen-off cpu time per freq: 900000 900000 900000 500000",
        "Total screen-off cpu time per freq: 1000 0 0 0",
    )
    ctx = _ctx(context_factory, batterystats_charged=quiet)
    result = cpu.screen_off_cpu_by_uid(ctx)
    assert result.metrics["core_share_pct"] < cpu.CORE_SHARE_HIGH_PCT
    assert _finding(result, "core-dominated") is None


def test_short_windows_give_no_rates(context_factory):
    """Seconds on battery or screen-off give no shares of a core or hourly rates."""
    short = replace(WINDOWS, on_battery_s=600.0, screen_off_on_battery_s=300.0)
    ctx = _ctx(context_factory, windows=short, batterystats_charged=BATTERYSTATS)
    with pytest.raises(SkipError, match="under 15 min"):
        cpu.system_process_cpu_churn(ctx)
    procs = cpu.battery_proc_cpu(ctx).tables["processes"]
    assert all(r["core_pct_on_battery"] is None for r in procs)
    screen = cpu.screen_off_cpu_by_uid(ctx)
    assert screen.metrics["screen_off_cpu_s_per_h"] is None
    assert _finding(screen, "busy-background-apps") is None
    assert _finding(screen, "core-dominated").severity == "info"


TOP = dedent(
    """\
    Tasks: 512 total,   2 running, 510 sleeping,   0 stopped,   0 zombie
      Mem:  5999999K total,  4000000K used,  1999999K free,     1000K buffers
     Swap:  2000000K total,   500000K used,  1500000K free,  1000000K cached
    800%cpu  60%user   0%nice  70%sys 340%idle 100%iow   5%irq   5%sirq   0%host
      PID USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS
     8400 u0_a101      20   0  12G 210M  99M S 53,5   2.8  10:05.00 com.example.app
     8200 shell        20   0   9G 4.1M 3.0M R 25.0   0.0   0:00.06 top -b -n 3
     1500 system       20   0   9G 2.9M 1.5M S  7.1   0.0  15:06.77 cnss_diag -q

    Tasks: 512 total,   1 running, 511 sleeping,   0 stopped,   0 zombie
      Mem:  5999999K total,  4000100K used,  1999899K free,     1000K buffers
     Swap:  2000000K total,   500000K used,  1500000K free,  1000000K cached
    800%cpu  40%user   1%nice  40%sys 300%idle  90%iow   5%irq   2%sirq   0%host
      PID USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS
     8400 u0_a101      20   0  12G 210M  99M S 40.2   2.8  10:06.44 com.example.app
     8200 shell        20   0   9G 4.1M 3.0M R 30.0   0.0   0:00.10 top -b -n 3
    """,
)


def test_top_samples_flags_hog_saturation_and_iowait(context_factory):
    result = cpu.top_samples(_ctx(context_factory, top=TOP))
    assert result.metrics["samples"] == 2
    assert result.metrics["idle_share_pct_min"] == pytest.approx(37.5)
    ids = {f.id for f in result.findings}
    assert "top_samples.hog-com-example-app" in ids
    assert "top_samples.cpu-saturated" in ids
    assert "top_samples.io-wait" in ids
    assert not any("top-b" in i or i.endswith("hog-top") for i in ids)
    deltas = {r["pid"]: r["cpu_s"] for r in result.tables["cpu_between_first_and_last"]}
    assert deltas[8400] == pytest.approx(1.44)
    assert "charging" in result.findings[-1].summary


def test_top_samples_skips_rows_cut_before_the_name(context_factory):
    """A row cut after TIME+ has no name; it is skipped instead of crashing."""
    header = dedent(
        """\
        Tasks: 512 total,   2 running, 510 sleeping,   0 stopped,   0 zombie
        800%cpu  60%user   0%nice  70%sys 600%idle  0%iow   5%irq   5%sirq   0%host
          PID USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS
        """,
    )
    row = " 8400 u0_a101      20   0  12G 210M  99M S 50.0   2.8  10:05.00"
    top = header + row + "\n" + 2 * (header + row + " com.example.app\n")
    result = cpu.top_samples(_ctx(context_factory, top=top))
    assert result.metrics["samples"] == 3
    assert result.metrics["hogs"] == 0
    assert "Skipped 1 unparsable top rows." in result.notes


def test_top_samples_quiet_and_bugreport_thread_format(context_factory):
    body = dedent(
        """\
        Threads: 3000 total,   5 running, 2995 sleeping,   0 stopped,   0 zombie
        800%cpu 200%user   2%nice 250%sys 300%idle  30%iow  10%irq   8%sirq   0%host
          PID   TID USER         PR  NI[%CPU]S VIRT  RES PCY CMD             NAME
         1300  7400 system        0 -20 60.0 R  18G  70M  fg binder:1300_1C  system_server
         1300  1450 system       29   9  3.6 S  18G  70M  fg Jit thread pool system_server
         1050  7500 system       RT  -4  1.8 S   9G 2.5M     51_see          sensors-service
        """,  # ruff: ignore[line-too-long] - dump lines are long
    )
    result = cpu.top_samples(context_factory(sections={"CPU INFO (top -H)": body}))
    busiest = {r["process"]: r for r in result.tables["busiest"]}
    assert busiest["system_server"]["threads"] == 2
    assert busiest["system_server"]["cpu_pct"] == pytest.approx(63.6)
    assert busiest["sensors-service"]["cpu_pct"] == pytest.approx(1.8)
    # The bugreport's own sample is inflated by dumpstate: no saturation finding.
    assert not result.findings


CPUINFO = dedent(
    """\
    Load: 0.5 / 0,25 / 0.20
    CPU usage from 190000ms to 160000ms ago (2026-01-15 11:56:10.000 to 2026-01-15 11:56:58.000) with 62% awake:
      20% 650/android.system.suspend-service: 0.2% user + 19% kernel
      10% 22100/com.example.app: 6,5% user + 3,5% kernel / faults: 15000 minor 2000 major
      10% 510/ueventd: 9.0% user + 1.0% kernel
      3.5% 1300/system_server: 2.0% user + 1.5% kernel / faults: 2500 minor 90 major
      +0% 30000/com.example.new: 0% user + 0% kernel
    12% TOTAL: 3.5% user + 7.0% kernel + 0.4% iowait + 0.6% irq + 0.5% softirq
    """,  # ruff: ignore[line-too-long] - dump lines are long
)


def test_cpuinfo_window_parses_window_faults_and_daemons(context_factory):
    result = cpu.cpuinfo_window(_ctx(context_factory, cpuinfo=CPUINFO, ps=PS))
    m = result.metrics
    assert (m["load_1m"], m["load_5m"], m["load_15m"]) == (0.5, 0.25, 0.2)
    assert m["window_wall_s"] == pytest.approx(48.0)
    assert m["window_uptime_s"] == pytest.approx(30.0)
    assert m["awake_pct"] == pytest.approx(62.0)
    assert m["window_on_battery"] is False  # after the plug-in at 11:10
    assert m["total_pct"] == pytest.approx(12.0)
    assert m["total_iowait_pct"] == pytest.approx(0.4)
    faults = _finding(result, "major-fault-thrash")
    assert faults is not None
    assert faults.metrics == {"com.example.app": pytest.approx(41.7)}
    daemons = _finding(result, "busy-daemons")
    assert daemons is not None
    assert set(daemons.metrics) == {"android.system.suspend-service", "ueventd"}
    assert _finding(result, "cpu-not-saturated") is not None


def test_cpuinfo_window_leaves_reported_daemons_to_churn(context_factory):
    ctx = _ctx(context_factory, cpuinfo=CPUINFO, ps=PS)
    churn = Result("system_process_cpu_churn")
    churn.tables["processes"] = [
        {"process": "android.system.suspend-service"},
        {"process": "ueventd"},
    ]
    churn.findings = [
        Finding(
            id=f"system_process_cpu_churn.{name}",
            title="",
            symptom="battery",
            severity="high",
            basis="measured",
            window="on_battery",
            summary="",
        )
        for name in ("android-system-suspend-service", "ueventd")
    ]
    ctx.results["system_process_cpu_churn"] = churn
    result = cpu.cpuinfo_window(ctx)
    assert _finding(result, "busy-daemons") is None


def _emitted(fid: str) -> Result:
    finding = Finding(fid, "t", "both", "medium", "measured", "since_boot", "s.")
    return Result(fid.split(".", maxsplit=1)[0], findings=[finding])


def test_cpu_findings_link_the_wider_views_of_their_fact(context_factory):
    """Since-boot thrashing owns the window's faults (one-way: equal strength)."""
    ctx = _ctx(
        context_factory, cpuinfo=CPUINFO, ps=PS, batterystats_charged=BATTERYSTATS
    )
    ctx.results["vmstat_reclaim_io"] = vmstat = _emitted(
        "vmstat_reclaim_io.page_cache_thrashing"
    )
    ctx.results["power_model"] = model = _emitted("power_model.system_uids_dominate")
    faults = _finding(cpu.cpuinfo_window(ctx), "major-fault-thrash")
    assert vmstat.findings[0].related == [faults.id]
    assert faults.related == []
    core = _finding(cpu.screen_off_cpu_by_uid(ctx), "core-dominated")
    assert core.related == [model.findings[0].id]
    assert model.findings[0].related == [core.id]


def test_cpuinfo_window_clock_change_uses_the_uptime_span(context_factory):
    jumped = CPUINFO.replace(
        "from 190000ms to 160000ms ago (2026-01-15 11:56:10.000",
        "from 30000ms to 24500ms ago (1970-01-02 03:04:05.000",
    ).replace(" with 62% awake", "")
    result = cpu.cpuinfo_window(_ctx(context_factory, cpuinfo=jumped, ps=PS))
    m = result.metrics
    assert m["window_wall_s"] == pytest.approx(5.5)
    assert m["window_on_battery"] is None
    assert any("clock changed" in note for note in result.notes)
    daemons = _finding(result, "busy-daemons")
    assert daemons.summary.startswith("In the last CPU window (6 s): ")


def test_cpuinfo_window_below_thresholds(context_factory):
    quiet = CPUINFO.replace("2000 major", "20 major").replace("20% 650", "2% 650")
    quiet = quiet.replace("10% 510", "1% 510").replace("Load: 0.5", "Load: 3.5")
    result = cpu.cpuinfo_window(_ctx(context_factory, cpuinfo=quiet, ps=PS))
    assert not result.findings


def test_cpuinfo_window_skips_without_rows(context_factory):
    with pytest.raises(SkipError):
        cpu.cpuinfo_window(_ctx(context_factory, cpuinfo="Load: 0.0 / 0.0 / 0.0\n"))


def _am_cpu_log() -> str:
    """Six CPU-stat updates 90 s apart; suspend activity stops in two of them."""
    lines = ["--------- beginning of events"]
    start = datetime(2026, 1, 15, 11, 0, 0)
    lines.append(f"{start:%Y-%m-%d %H:%M:%S}.000  1000  1300  1300 I screen_toggled: 0")
    suspend_ms = [6000, 8000, 0, 0, 7000, 5000]
    for n, ms in enumerate(suspend_ms):
        ts = start + timedelta(seconds=90 * (n + 1))
        stamp = f"{ts:%Y-%m-%d %H:%M:%S}.100  1000  1300  1900 I am_cpu  :"
        rows = [
            "[1500,1000,cnss_diag,60000,1100,100]",
            f"[1300,1000,system_server,60000,{1000 + 100 * n},200]",
        ]
        if ms:
            rows += [
                f"[650,1000,suspend-service,60000,10,{ms}]",
                f"[510,0,ueventd,60000,{ms // 2},20]",
            ]
        lines += [f"{stamp} {row}" for row in rows]
    return "\n".join(lines) + "\n"


def test_am_cpu_intervals_couples_and_steady(context_factory):
    ctx = _ctx(context_factory, logcat_events=_am_cpu_log(), ps=PS)
    result = cpu.am_cpu_intervals(ctx)
    m = result.metrics
    assert m["batches"] == 6
    assert m["covered_uptime_s"] == pytest.approx(360.0)
    assert m["suspend_process"] == "android.system.suspend-service"
    assert m["batches_without_suspend"] == 2
    assert m["screen_off_batches"] == 6
    assert m["plugged_at"] == "2026-01-15 11:10:00"
    assert m["batches_while_charging"] == 0
    rows = {r["process"]: r for r in result.tables["processes"]}
    assert rows["cnss_diag"]["pct_without_suspend"] == pytest.approx(2.0)
    assert rows["ueventd"]["pct_without_suspend"] == pytest.approx(0.0)
    pair = result.tables["coupled_pairs"][0]
    assert {pair["a"], pair["b"]} == {"android.system.suspend-service", "ueventd"}
    assert pair["r"] > cpu.COUPLED_MIN_R
    assert all(b["on_battery"] for b in result.tables["batches"])


def test_am_cpu_intervals_label_batches_after_the_plug_in(context_factory):
    windows = replace(WINDOWS, plugged_at=datetime(2026, 1, 15, 11, 5, 0))
    ctx = _ctx(context_factory, windows=windows, logcat_events=_am_cpu_log())
    result = cpu.am_cpu_intervals(ctx)
    states = [b["on_battery"] for b in result.tables["batches"]]
    # Updates at 11:01:30-11:04:30 on battery, 11:06 after the plug-in at 11:05
    # (its interval started 11:04:30, so it is mixed), then charging.
    assert states == [True, True, True, None, False, False]
    assert result.metrics["batches_while_charging"] == 2


def test_am_cpu_intervals_skips_without_rows(context_factory):
    log = "2026-01-15 11:00:00.000  1000  1300  1300 I screen_toggled: 0\n"
    with pytest.raises(SkipError):
        cpu.am_cpu_intervals(_ctx(context_factory, logcat_events=log))


THREADS = dedent(
    """\
    LABEL                          USER           PID   TID  PPID        VSZ    RSS WCHAN            ADDR S PRI  NI RTPRIO SCH PCY     TIME CMD
    u:r:init:s0                    root             1     1     0    9876540   3210 0                   0 S  19   0      -   0  fg 00:00:25 init
    u:r:system_suspend:s0          system         650   650     1    9900120   2050 0                   0 S  19   0      -   0  fg 00:00:01 android.system.
    u:r:system_suspend:s0          system         650  9700     1    9900120   2050 0                   0 S  19   0      -   0  fg 00:26:49 binder:650_3
    u:r:system_suspend:s0          system         650  9701     1    9900120   2050 0                   0 S  19   0      -   0  fg 00:00:20 binder:650_4
    u:r:system_server:s0           system        1300  2500   880   18000400 120000 0                   0 S  19   0      -   0  fg 00:02:41 ConnectivitySer
    u:r:system_server:s0           system        1300  2600   880   18000400 120000 0                   0 S  19   0      -   0  fg 00:02:09 UsbService host
    u:r:system_server:s0           system        1300  1300   880   18000400 120000 0                   0 S  19   0      -   0  fg 00:02:00 system_server
    garbage line
    """,  # ruff: ignore[line-too-long] - dump lines are long
)


def test_thread_cpu_finds_dominant_thread(context_factory):
    ctx = context_factory(
        live={"ps": PS},
        sections={"PROCESSES AND THREADS (ps -A -T -Z)": THREADS},
    )
    result = cpu.thread_cpu(ctx)
    rows = {r["pid"]: r for r in result.tables["processes"]}
    assert rows[650]["process"] == "android.system.suspend-service"
    assert rows[650]["top_thread"] == "binder:650_3"
    assert rows[650]["dominant"] is True
    assert rows[1300]["dominant"] is False
    threads = {r["thread"] for r in result.tables["hot_threads"]}
    assert "UsbService host" in threads
    assert result.notes[0] == "Skipped 1 unparsable thread lines."


def test_system_process_cpu_churn_findings(context_factory):
    ctx = context_factory(
        live={
            "ps": PS,
            "batterystats_charged": BATTERYSTATS,
            "logcat_events": _am_cpu_log(),
        },
        packages=PACKAGES,
        windows=WINDOWS,
        sections={"PROCESSES AND THREADS (ps -A -T -Z)": THREADS},
    )
    for name in ("thread_cpu", "am_cpu_intervals"):
        ctx.results[name] = getattr(cpu, name)(ctx)
    result = cpu.system_process_cpu_churn(ctx)
    findings = {f.id.rsplit(".", 1)[1]: f for f in result.findings}
    assert set(findings) == {
        "android-system-suspend-service",
        "ueventd",
        "cnss-diag",
    }
    suspend = findings["android-system-suspend-service"]
    assert suspend.severity == "high"  # 1566 s over 5 h is 8.7% of a core
    assert suspend.metrics["suspend_attempts"] == 10_000
    assert suspend.metrics["ms_per_suspend_attempt"] == pytest.approx(156.6)
    assert suspend.metrics["on_battery_share_pct"] == pytest.approx(96.1, abs=0.1)
    assert suspend.summary.startswith("android.system.suspend-service used 26m06s")
    assert "binder:650_3" in suspend.summary
    assert "kernel time" in suspend.summary
    ueventd = findings["ueventd"]
    assert ueventd.severity == "medium"
    assert "moves with android.system.suspend-service" in ueventd.summary
    cnss = findings["cnss-diag"]
    assert cnss.severity == "medium"
    assert "without suspend activity" in cnss.summary
    assert cnss.metrics["modelled_cpu_mah"] == pytest.approx(4.8)
    assert "Wi-Fi verbose logging" in cnss.recommendation
    assert "quiet_daemon" not in str(result.tables["processes"])
    assert all("adb_ro.py --save" in f.followups[0] for f in result.findings)


def test_system_process_cpu_churn_reads_the_thread_list_without_ps(context_factory):
    """A bugreport-only capture finds since-boot CPU in the per-thread list."""
    ctx = context_factory(
        live={"batterystats_charged": BATTERYSTATS},
        windows=WINDOWS,
        sections={"PROCESSES AND THREADS (ps -A -T -Z)": THREADS},
    )
    ctx.results["thread_cpu"] = cpu.thread_cpu(ctx)
    result = cpu.system_process_cpu_churn(ctx)
    rows = {r["process"]: r for r in result.tables["processes"]}
    suspend = rows["android.system.suspend-service"]
    assert suspend["since_boot_cpu_s"] == pytest.approx(1630.0)
    assert suspend["on_battery_share_pct"] == pytest.approx(96.1, abs=0.1)
    assert suspend["top_thread"] == "binder:650_3"
    assert suspend["ps_ref"].startswith("bugreport:PROCESSES AND THREADS:")


def test_system_process_cpu_churn_reboot_inside_window(context_factory):
    windows = replace(WINDOWS, boot_time=DUMP - timedelta(hours=1))
    ctx = context_factory(
        live={"ps": PS, "batterystats_charged": BATTERYSTATS},
        windows=windows,
    )
    result = cpu.system_process_cpu_churn(ctx)
    assert all(r["on_battery_share_pct"] is None for r in result.tables["processes"])
    assert "rebooted" in result.notes[0]


def test_system_process_cpu_churn_skips_without_battery_time(context_factory):
    ctx = context_factory(live={"batterystats_charged": BATTERYSTATS})
    with pytest.raises(SkipError):
        cpu.system_process_cpu_churn(ctx)
