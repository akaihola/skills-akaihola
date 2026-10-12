"""Tests for the memory analyzers, on invented dumps only."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from textwrap import dedent

import pytest
from androiddiag import memory
from androiddiag.common import PackageMap
from androiddiag.model import Result, SkipError, Windows

WINDOWS = Windows(
    dump_time=datetime(2026, 1, 15, 12, 0),
    boot_time=datetime(2026, 1, 15, 0, 0),
    since_charge_start=datetime(2026, 1, 15, 8, 0),
    on_battery_at_capture=False,
    on_battery_s=3 * 3600,
    plugged_at=datetime(2026, 1, 15, 11, 0),
    plugged_at_source="since-charge start + time on battery (estimate)",
)
PACKAGES = "package:com.example.heavy uid:10101\npackage:com.example.voice uid:10102\n"


def by_id(result: Result) -> dict:
    return {f.id: f for f in result.findings}


def third_party_packages() -> PackageMap:
    """Return a package map in which every listed package is user-installed."""
    packages = PackageMap.from_pm_list(PACKAGES)
    packages.third_party = frozenset(packages.by_app_id)
    return packages


# --- exit-info fixtures ------------------------------------------------------


def record(time, process, **kw):
    """Return the three lines of one ApplicationExitInfo record."""
    reason = kw.get("reason", "3 (LOW_MEMORY)")
    sub = kw.get("sub", "0 (UNKNOWN)")
    uid = kw.get("uid", 10101)
    day = kw.get("day", "2026-01-15")
    return [
        (
            f"          timestamp={day} {time} pid={kw.get('pid', 4321)} "
            f"realUid={uid} packageUid={uid} definingUid={uid} user=0"
        ),
        f"          process={process} reason={reason} subreason={sub} status=0",
        (
            f"          importance={kw.get('importance', 400)} "
            f"pss={kw.get('pss', '0,00')} rss={kw.get('rss', '0,00')} "
            f"description={kw.get('description', 'null')} "
            f"state={kw.get('state', 'empty')} trace=null"
        ),
    ]


def exit_info(sections):
    """Build ``dumpsys activity exit-info`` from ``{(package, uid): [records]}``."""
    lines = [
        "ACTIVITY MANAGER PROCESS EXIT INFO (dumpsys activity exit-info)",
        "Last Timestamp of Persistence Into Persistent Storage: 2026-01-15 11:59:00",
    ]
    for (package, uid), records in sections.items():
        lines += [f"  package: {package}", f"    Historical Process Exit for uid={uid}"]
        for i, rec in enumerate(records):
            lines.append(f"        ApplicationExitInfo #{i}:")
            lines += rec
    return "\n".join(lines) + "\n"


def kills_at(package, times, **kw):
    return [record(t, package, **kw) for t in times]


def busy_exit_info(on_battery_kills=10):
    """Several packages killed on battery, one with a full 16-record history."""
    times = [f"09:{m:02d}:{s:02d}.000" for m in range(10) for s in (5, 25, 45)]
    sections = {
        ("com.example.full", 10120): kills_at(
            "com.example.full", times[:16], uid=10120
        ),
    }
    for n in range(4):
        package = f"com.example.app{n}"
        sections[package, 10130 + n] = kills_at(
            package,
            [f"10:{n:02d}:{s:02d}.000" for s in range(on_battery_kills)],
            uid=10130 + n,
        )
    sections["com.example.old", 10140] = kills_at(
        "com.example.old",
        ["23:00:00.000"],
        uid=10140,
        day="2026-01-14",
    )
    sections["com.example.cpu", 10150] = [
        record(
            t,
            "com.example.cpu",
            uid=10150,
            reason="9 (EXCESSIVE RESOURCE USAGE)",
            sub="7 (EXCESSIVE CPU USAGE)",
            importance=400,
            pss="63MB",
            rss="12,5MB",
            description="excessive cpu 9000 during 300000 dur=50000000 limit=2",
            state="44 bytes",
        )
        for t in ("10:30:00.000", "10:40:00.000")
    ]
    sections["com.example.crash", 10160] = [
        record(
            "07:00:00.000",
            "com.example.crash",
            uid=10160,
            reason="4 (APP CRASH(EXCEPTION))",
            description="crash",
        ),
        record("07:10:00.000", "com.example.crash", uid=10160, importance=200),
        record("11:00:30.000", "com.example.crash", uid=10160),
    ]
    return exit_info(sections)


def test_exit_info_counts_windows_and_lower_bounds(context_factory):
    ctx = context_factory(live={"exit_info": busy_exit_info()}, windows=WINDOWS)
    result = memory.exit_info_audit(ctx)
    m = result.metrics
    # 16 + 4 * 10 on battery, one visible kill at 07:10, one after the plug-in
    assert m["low_memory_kills_since_boot"] == 58
    assert m["low_memory_kills_on_battery"] == 56
    assert m["low_memory_kills_60s_after_plug_in"] == 1
    assert m["sections_filled_since_boot"] == 1
    assert m["exit_history_per_section"] == 16
    assert m["excessive_cpu_kills_on_battery"] == 2
    assert m["low_memory_kills_visible_since_boot"] == 1
    assert m["on_battery_end_source"].startswith("since-charge start")
    reasons = {row["reason"] for row in result.tables["reasons"]}
    assert "4 APP CRASH(EXCEPTION)" in reasons
    found = by_id(result)
    rate = found["exit_info_audit.low_memory_kills"]
    assert rate.severity == "medium"
    assert rate.window == "since_boot"
    assert rate.evidence[0].ref.startswith("live/exit_info.txt:")
    assert found["exit_info_audit.excessive_cpu_kills"].severity == "medium"
    assert found["exit_info_audit.visible_low_memory_kills"].severity == "low"
    assert any("lower bounds" in note for note in result.notes)


def test_exit_info_decimal_comma_and_spaced_state(context_factory):
    ctx = context_factory(live={"exit_info": busy_exit_info()}, windows=WINDOWS)
    text = ctx.sources.get("exit_info")
    info = memory._parse_exit_info(text)  # ruff: ignore[private-member-access] - parser detail under test
    cpu = [r for r in info.records if r.is_excessive_cpu]
    assert len(cpu) == 2
    assert cpu[0].rss_kib == round(12.5 * 1024)
    assert info.skipped == 0


def test_exit_info_high_rate_and_quiet_phone(context_factory):
    ctx = context_factory(
        live={"exit_info": busy_exit_info(on_battery_kills=30)},
        windows=WINDOWS,
    )
    found = by_id(memory.exit_info_audit(ctx))
    assert found["exit_info_audit.low_memory_kills"].severity == "high"

    quiet = exit_info(
        {("com.example.app", 10101): kills_at("com.example.app", ["09:00:00.000"])},
    )
    ctx = context_factory(live={"exit_info": quiet}, windows=WINDOWS)
    result = memory.exit_info_audit(ctx)
    assert "exit_info_audit.low_memory_kills" not in by_id(result)


AM_LMK = dedent(
    """\
    ACTIVITY MANAGER LMK KILLS (dumpsys activity lmk)
      Total number of kills: 120
        kills at or below oom_adj 999: 120
        kills at or below oom_adj 900: 7
        kills at or below oom_adj 200: 0
    """,
)


def test_exit_info_compared_with_activity_manager_counter(context_factory):
    ctx = context_factory(
        live={"exit_info": busy_exit_info(), "activity_lmk": AM_LMK},
        windows=WINDOWS,
    )
    result = memory.exit_info_audit(ctx)
    m = result.metrics
    assert m["lmkd_kills_am_counter"] == 120
    assert m["lmkd_kills_am_counter_adj_900_or_less"] == 7
    assert m["exit_info_share_of_am_counter_pct"] == pytest.approx(48.3)
    finding = by_id(result)["exit_info_audit.low_memory_kills"]
    assert "counted 120 lmkd kills" in finding.summary
    assert finding.evidence[-1].ref == "live/activity_lmk.txt:2"


def test_exit_info_from_bugreport_activity_dump(context_factory):
    activity = "\n".join(
        [
            "ACTIVITY MANAGER SETTINGS (dumpsys activity settings)",
            "  max_cached_processes=60",
            busy_exit_info().rstrip(),
            AM_LMK.rstrip(),
            "ACTIVITY MANAGER RUNNING PROCESSES (dumpsys activity processes)",
        ],
    )
    ctx = context_factory(services={"activity": activity}, windows=WINDOWS)
    result = memory.exit_info_audit(ctx)
    assert result.metrics["low_memory_kills_since_boot"] == 58
    assert result.metrics["lmkd_kills_am_counter"] == 120
    ref = by_id(result)["exit_info_audit.low_memory_kills"].evidence[0].ref
    assert ref.startswith("bugreport:dumpsys activity:")


def test_exit_info_full_history_ties_have_a_stable_order(context_factory):
    times = [f"09:00:{s:02d}.000" for s in range(16)]
    sections = {
        (package, uid): kills_at(package, times, uid=uid)
        for package, uid in (("com.example.zeta", 10171), ("com.example.alpha", 10170))
    }
    ctx = context_factory(live={"exit_info": exit_info(sections)}, windows=WINDOWS)
    rows = memory.exit_info_audit(ctx).tables["sections_with_full_history"]
    assert [row["package"] for row in rows] == ["com.example.alpha", "com.example.zeta"]


def test_visible_kill_contradicted_by_activity_manager_counter(context_factory):
    ctx = context_factory(
        live={"exit_info": busy_exit_info(), "activity_lmk": AM_LMK},
        windows=WINDOWS,
    )
    result = memory.exit_info_audit(ctx)
    # The counter says no lmkd kill at adj 200 or lower since boot.
    assert result.metrics["low_memory_kills_visible_since_boot"] == 1
    assert result.metrics["low_memory_kills_visible_contradicted_by_lmkd"] == 1
    assert "exit_info_audit.visible_low_memory_kills" not in by_id(result)
    assert any("raised them after lmkd's choice" in n for n in result.notes)


@pytest.mark.parametrize(("adj", "visible"), [(925, False), (100, True)])
def test_visible_kill_checked_against_lmkd_adj(context_factory, adj, visible):
    # The visible record (07:10) is pid 4321; lmkd logged its kill just before.
    payload = killinfo(4321, adj=adj)
    events = log("07:09:59.900", "killinfo", payload, "lmkd", 600)
    ctx = context_factory(
        live={"exit_info": busy_exit_info(), "logcat_events": events},
        windows=WINDOWS,
    )
    result = memory.exit_info_audit(ctx)
    assert result.tables["visible_low_memory_kills"][0]["lmkd_adj"] == adj
    found = by_id(result)
    assert ("exit_info_audit.visible_low_memory_kills" in found) is visible


def test_exit_info_rates_need_an_hour(context_factory):
    short = replace(WINDOWS, boot_time=datetime(2026, 1, 15, 11, 40))
    times = [f"11:4{m}:00.000" for m in range(5, 10)]
    kills = exit_info({("com.example.app", 10101): kills_at("com.example.app", times)})
    ctx = context_factory(live={"exit_info": kills}, windows=short)
    m = memory.exit_info_audit(ctx).metrics
    assert m["low_memory_kills_since_boot"] == len(times)
    assert m["window_h_since_boot"] == pytest.approx(0.33)
    assert m["low_memory_kills_per_h_since_boot"] is None


def test_exit_info_missing_is_skipped(context_factory):
    ctx = context_factory(live={"battery": "  level: 50"}, windows=WINDOWS)
    with pytest.raises(SkipError):
        memory.exit_info_audit(ctx)


# --- lmkd fixtures -----------------------------------------------------------


def log(time, tag, message, uid="1000", pid=1300):
    """Return one logcat line in ``-v threadtime -v year -v uid`` format."""
    return f"2026-01-15 {time}  {uid:>5} {pid:5} {pid:5} I {tag}: {message}"


SWAP_TOTAL_KB = 3_000_000


def killinfo(pid, *, mem_free=1_600_000, adj=905, aosp=False, cpu=12.0):
    """Return a killinfo payload; vendor builds omit the Unevictable field."""
    meminfo = [mem_free, 1_500_000, 40_000, 20_000, 16_000]
    meminfo += [16_000] if aosp else []
    meminfo += [SWAP_TOTAL_KB, 2_000_000, 1_500_000, 500_000, 400_000, 1_200_000]
    meminfo += [200_000, 300_000, 80_000, 150_000, 0, 0, 16_384]
    tail = [900, 100, 9, 0, 40_000, 0, 10, 20]
    fields = [pid, 10101, adj, 700, 32_000, 8, *meminfo, *tail]
    psi = [2.00, 0.80, 2.50, 0.70, cpu]
    return "[" + ",".join(map(str, fields + psi)) + "]"


def lmkd_events(count=4, mem_free=1_600_000, step=3, *, aosp=False):
    return "\n".join(
        log(
            f"10:00:{i * step:02d}.100",
            "killinfo",
            killinfo(5000 + i, mem_free=mem_free, aosp=aosp),
            "lmkd",
            600,
        )
        for i in range(count)
    )


KILL_LINE = (
    "Kill 'com.example.heavy' (5000), uid 10101, oom_score_adj 905 to free "
    "32000kB rss, 4000kB swap; reason: min watermark is breached"
)


def test_lmkd_kills_with_free_memory(context_factory):
    ctx = context_factory(
        live={
            "logcat_events": lmkd_events(),
            "logcat_system": log(
                "10:00:00.100", "lowmemorykiller", KILL_LINE, "lmkd", 600
            ),
            "proc_meminfo": f"MemTotal: 7000000 kB\nSwapTotal: {SWAP_TOTAL_KB} kB\n",
        },
        packages=PACKAGES,
        windows=WINDOWS,
    )
    result = memory.lmkd_kills(ctx)
    m = result.metrics
    assert m["lmkd_kills_logged"] == 4
    assert m["killinfo_layout"].startswith("vendor")
    assert m["kills_mem_free_over_1gib"] == 4
    assert m["lmkd_kills_on_battery"] == 4
    assert m["top_reason"] == "min watermark is breached"
    assert m["psi_cpu_some_avg10_at_kill_max_pct"] == pytest.approx(12.0)
    first = result.tables["kills"][0]
    assert first["cma_free_mib"] == pytest.approx(16.0)
    assert first["process"] == "com.example.heavy"
    finding = by_id(result)["lmkd_kills.kills_with_free_memory"]
    assert finding.basis == "measured"
    assert "not shown" in finding.summary


def test_lmkd_aosp_layout_low_free_memory_and_storm(context_factory):
    ctx = context_factory(
        live={
            "logcat_events": lmkd_events(count=12, mem_free=100_000, step=0, aosp=True)
        },
        windows=WINDOWS,
    )
    result = memory.lmkd_kills(ctx)
    assert result.metrics["killinfo_layout"].startswith("AOSP")
    assert result.tables["kills"][0]["reason"] == "low mem (watermark)"
    found = by_id(result)
    assert "lmkd_kills.kills_with_free_memory" not in found
    assert found["lmkd_kills.kill_storm"].metrics["kills_in_10s"] == 12


def test_lmkd_unvalidated_layout_reads_no_meminfo(context_factory):
    # A vendor layout with MemTotal first: SwapTotal is not at index 11 or 12.
    fields = [5000, 10101, 905, 700, 32_000, 3, 7_000_000, 17_000, 60_000]
    fields += [1_000 * n for n in range(1, 10)] + [SWAP_TOTAL_KB, 100_000]
    fields += [0] * 6
    events = "\n".join(
        log(
            f"10:00:0{i}.100",
            "killinfo",
            "[" + ",".join(map(str, [5000 + i, *fields[1:]])) + "]",
            "lmkd",
            600,
        )
        for i in range(4)
    )
    ctx = context_factory(
        live={
            "logcat_events": events,
            "proc_meminfo": f"MemTotal: 7000000 kB\nSwapTotal: {SWAP_TOTAL_KB} kB\n",
        },
        windows=WINDOWS,
    )
    result = memory.lmkd_kills(ctx)
    m = result.metrics
    assert m["killinfo_layout"] == "unvalidated"
    assert m["mem_free_at_kill_max_mib"] is None
    assert m["kills_mem_free_over_1gib"] == 0
    assert result.tables["kills"][0]["mem_free_mib"] is None
    assert "lmkd_kills.kills_with_free_memory" not in by_id(result)
    assert any("are not read" in note for note in result.notes)


def test_lmkd_storm_after_plug_in_is_left_to_process_churn(context_factory):
    plugged = replace(WINDOWS, plugged_at=datetime(2026, 1, 15, 10, 0))
    ctx = context_factory(
        live={
            "logcat_events": lmkd_events(count=12, mem_free=100_000, step=0, aosp=True)
        },
        windows=plugged,
    )
    result = memory.lmkd_kills(ctx)
    assert result.metrics["max_kills_in_10s"] == 12
    assert "lmkd_kills.kill_storm" not in by_id(result)
    assert any("process_churn.plug_in_flood" in note for note in result.notes)


def test_lmkd_missing_logs_is_skipped(context_factory):
    ctx = context_factory(live={"logcat_events": log("10:00:00.000", "am_pss", "[1]")})
    with pytest.raises(SkipError):
        memory.lmkd_kills(ctx)


# --- screen transitions ------------------------------------------------------

USAGESTATS = dedent(
    """\
    user=0
      Last 24 hour events (timeRange="15.1.2026 klo 0.00-15.1.2026 klo 12.00" )
        time="2026-01-15 08:30:00" type=SCREEN_INTERACTIVE package=android flags=0x0
        time="2026-01-15 08:35:00" type=SCREEN_NON_INTERACTIVE package=android flags=0x0
        time="2026-01-15 09:30:00" type=SCREEN_INTERACTIVE package=android flags=0x0
        time="2026-01-15 09:35:00" type=SCREEN_NON_INTERACTIVE package=android flags=0x0
        time="2026-01-15 10:30:00" type=SCREEN_INTERACTIVE package=android flags=0x0
        time="2026-01-15 10:31:00" type=SCREEN_NON_INTERACTIVE package=android flags=0x0
    """,
)


def screen_exit_info(*, after_screen_on=True):
    if after_screen_on:
        times = [
            f"{h}:30:{s:02d}.000" for h in ("08", "09", "10") for s in range(20, 50, 5)
        ]
    else:
        times = [f"09:{m:02d}:00.000" for m in range(5, 17)]
    return exit_info({("com.example.app", 10101): kills_at("com.example.app", times)})


def test_kills_cluster_after_screen_on(context_factory):
    ctx = context_factory(
        live={"exit_info": screen_exit_info(), "usagestats": USAGESTATS},
        windows=WINDOWS,
    )
    result = memory.kills_vs_screen_events(ctx)
    m = result.metrics
    assert m["on_battery_kills_0_3min_after_screen_on"] == 18
    assert m["on_battery_screen_ons"] == 3
    assert m["on_battery_kills_per_screen_on"] == pytest.approx(6.0)
    finding = by_id(result)["kills_vs_screen_events.kills_after_screen_on"]
    assert finding.severity == "medium"
    assert finding.window == "on_battery"
    assert "correlation" in finding.summary


def test_kills_during_screen_off_do_not_count_as_unlock_bursts(context_factory):
    ctx = context_factory(
        live={
            "exit_info": screen_exit_info(after_screen_on=False),
            "usagestats": USAGESTATS,
        },
        windows=WINDOWS,
    )
    result = memory.kills_vs_screen_events(ctx)
    found = by_id(result)
    assert "kills_vs_screen_events.kills_after_screen_on" not in found
    stretch = result.tables["long_screen_off"][0]
    assert stretch["kills"] == 12
    assert stretch["on_battery"] == "yes"
    assert found["kills_vs_screen_events.kills_while_screen_off"].symptom == "battery"


def test_screen_events_fall_back_to_event_log(context_factory):
    events = "\n".join(
        [
            log("08:30:00.000", "screen_toggled", "1"),
            log("08:35:00.000", "screen_toggled", "0"),
        ],
    )
    ctx = context_factory(
        live={"exit_info": screen_exit_info(), "logcat_events": events},
        windows=WINDOWS,
    )
    result = memory.kills_vs_screen_events(ctx)
    assert result.metrics["on_battery_screen_ons"] == 1
    assert "logcat_events" in result.notes[0]


def test_on_battery_evidence_comes_from_the_battery_window(context_factory):
    early = dedent(
        """\
            time="2026-01-15 07:00:00" type=SCREEN_INTERACTIVE package=android
            time="2026-01-15 07:05:00" type=SCREEN_NON_INTERACTIVE package=android
        """,
    )
    usage = USAGESTATS + early
    times = [f"07:00:{s:02d}.000" for s in range(20, 50, 2)]
    times += [
        f"{h}:30:{s:02d}.000" for h in ("08", "09", "10") for s in range(20, 50, 5)
    ]
    kills = exit_info(
        {("com.example.app", 10101): kills_at("com.example.app", times)},
    )
    ctx = context_factory(
        live={"exit_info": kills, "usagestats": usage}, windows=WINDOWS
    )
    finding = by_id(memory.kills_vs_screen_events(ctx))[
        "kills_vs_screen_events.kills_after_screen_on"
    ]
    assert finding.window == "on_battery"
    # The 07:00 screen-on had the most kills, but before the battery window.
    assert all("07:00:00" not in e.excerpt for e in finding.evidence)
    assert len(finding.evidence) == 3


def test_screen_on_after_reboot_is_not_collapsed(context_factory):
    usage = dedent(
        """\
        time="2026-01-14 23:50:00" type=SCREEN_INTERACTIVE package=android flags=0x0
        time="2026-01-15 00:10:00" type=SCREEN_INTERACTIVE package=android flags=0x0
        time="2026-01-15 00:20:00" type=SCREEN_NON_INTERACTIVE package=android flags=0x0
        """,
    )
    times = [f"00:10:{s:02d}.000" for s in range(20, 50, 5)]
    kills = exit_info(
        {("com.example.app", 10101): kills_at("com.example.app", times)},
    )
    ctx = context_factory(
        live={"exit_info": kills, "usagestats": usage}, windows=WINDOWS
    )
    m = memory.kills_vs_screen_events(ctx).metrics
    # Boot (00:00) ends the 23:50 screen-on; the 00:10 screen-on is real.
    assert m["since_boot_screen_ons"] == 1
    assert m["since_boot_kills_0_3min_after_screen_on"] == len(times)
    assert m["since_boot_kills_screen_on_later"] == 0


def test_screen_events_missing_is_skipped(context_factory):
    ctx = context_factory(live={"exit_info": screen_exit_info()}, windows=WINDOWS)
    with pytest.raises(SkipError, match="screen"):
        memory.kills_vs_screen_events(ctx)


# --- memory snapshot ---------------------------------------------------------

MEMINFO = dedent(
    """\
    Applications Memory Usage (in Kilobytes):
    Uptime: 43200000 Realtime: 43200000

    Total RSS by process:
        400,000K: com.example.heavy (pid 2001 / activities)
         70,000K: com.example.voice (pid 2002)

    Total PSS by process:
        350,000K: com.example.heavy (pid 2001 / activities)
        300,000K: system (pid 1000)
        200,000K: com.example.voice (pid 2002)
         30,000K: com.example.cached (pid 2003)
         20,000K: com.example.cached2 (pid 2004)

    Total PSS by OOM adjustment:
        300,000K: System
            300,000K: system (pid 1000)
        350,000K: Perceptible
            350,000K: com.example.heavy (pid 2001 / activities)
        200,000K: Visible
            200,000K: com.example.voice (pid 2002)
         50,000K: Cached
             30,000K: com.example.cached (pid 2003)
             20,000K: com.example.cached2 (pid 2004)

    Total PSS by category:
        500,000K: Dalvik

    Total RAM: 7,340,032K (status normal)
     Free RAM: 3,000,000K (  150,000K cached pss + 1,600,000K cached kernel)
     Used RAM: 4,000,000K (3,300,000K used pss +   700,000K kernel)
     Lost RAM:   400,000K
         ZRAM:   400,000K physical used for 1,200,000K in swap (3,000,000K total swap)
    """,
)
DETAIL = dedent(
    """\
    ** MEMINFO in pid 2001 [com.example.heavy] **
     App Summary
               TOTAL PSS:   340000   TOTAL RSS:   390000   TOTAL SWAP PSS:    40000
    ** MEMINFO in pid 2002 [com.example.voice] **
     App Summary
               TOTAL PSS:   190000   TOTAL RSS:    60000   TOTAL SWAP PSS:   185000
    """,
)


def test_memory_snapshot_tables_and_findings(context_factory):
    ctx = context_factory(live={"meminfo": MEMINFO}, windows=WINDOWS)
    ctx.packages = third_party_packages()
    ctx.results["am_memory_config"] = Result(
        "am_memory_config",
        metrics={"cur_max_cached_processes": 60},
    )
    result = memory.memory_snapshot(ctx)
    m = result.metrics
    assert m["processes"] == 5
    assert m["total_ram_mib"] == pytest.approx(7168.0)
    assert m["zram_compression_ratio"] == pytest.approx(3.0)
    assert m["cached_processes"] == 2
    groups = {row["group"]: row["processes"] for row in result.tables["oom_groups"]}
    assert groups["Cached"] == 2
    found = by_id(result)
    hogs = found["memory_snapshot.resident_third_party"]
    assert "com.example.heavy" in hogs.summary
    assert "com.example.voice" in hogs.summary
    cached = found["memory_snapshot.few_cached_processes"]
    assert "limit of 60" in cached.summary
    assert "memory_snapshot.memory_status" not in found


def test_memory_snapshot_resident_split_from_detail(context_factory):
    ctx = context_factory(
        live={"meminfo": MEMINFO},
        services={"meminfo": DETAIL},
        windows=WINDOWS,
    )
    ctx.packages = third_party_packages()
    result = memory.memory_snapshot(ctx)
    rows = {r["process"]: r for r in result.tables["top_pss"]}
    voice = rows["com.example.voice"]
    # PSS, swap and resident come from the same per-process dump.
    assert voice["pss_mib"] == pytest.approx(185.5)
    assert voice["resident_pss_mib"] == pytest.approx(4.9)
    assert voice["physical_estimate_mib"] < memory.RESIDENT_HOG_MIB
    heavy = rows["com.example.heavy"]
    # 340000 = 300000 resident + 40000 swapped (KiB)
    split = (heavy["pss_mib"], heavy["resident_pss_mib"], heavy["swap_pss_mib"])
    assert split == pytest.approx((332.0, 293.0, 39.1))
    assert heavy["rss_mib"] == pytest.approx(380.9)
    hogs = by_id(result)["memory_snapshot.resident_third_party"]
    assert "com.example.voice" not in hogs.summary
    assert "com.example.heavy 332 MiB PSS (293 resident + 39 swapped" in hogs.summary
    assert hogs.evidence[0].ref.startswith("bugreport:dumpsys meminfo:")
    assert hogs.evidence[0].excerpt.startswith("[com.example.heavy] TOTAL PSS")


def test_memory_snapshot_without_third_party_list(context_factory):
    ctx = context_factory(live={"meminfo": MEMINFO}, windows=WINDOWS)
    result = memory.memory_snapshot(ctx)
    assert not any(r["third_party"] for r in result.tables["top_pss"])
    assert "memory_snapshot.resident_third_party" not in by_id(result)


@pytest.mark.parametrize("separator", [".", "\u00a0", "\u202f"])
def test_meminfo_thousands_separators(context_factory, separator):
    text = MEMINFO.replace(",", separator).replace("(status normal)", "(status low)")
    ctx = context_factory(live={"meminfo": text}, windows=WINDOWS)
    result = memory.memory_snapshot(ctx)
    assert result.tables["top_pss"][0]["pss_mib"] == pytest.approx(341.8)
    assert by_id(result)["memory_snapshot.memory_status"].severity == "medium"


def test_memory_snapshot_missing_is_skipped(context_factory):
    ctx = context_factory(live={"meminfo": "nothing useful\n"})
    with pytest.raises(SkipError):
        memory.memory_snapshot(ctx)


# --- vmstat and PSI ----------------------------------------------------------

VMSTAT = dedent(
    """\
    nr_free_pages 328032
    workingset_refault_anon 20000000
    workingset_refault_file 30000000
    pgpgin 200000000
    pswpin 1000
    pswpout 2000000
    allocstall_normal 4000
    allocstall_movable 2000
    pgmajfault 3000000
    pgsteal_kswapd 1000000
    pgsteal_direct 10000
    compact_stall 500
    compact_fail 300
    compact_success 200
    """,
)
PS = dedent(
    """\
      PID  PPID USER            RSS     VSZ     TIME S NAME
       77     2 root              0       0 00:02:00 S [oom_reaper]
       99     2 root              0       0 00:07:00 S [kswapd0]
      101     2 root              0       0 1-00:00:10 S [kswapd-1:0]
      600     1 lmkd           9000 1000000 00:00:30 S lmkd
    """,
)


def test_vmstat_thrashing_and_reclaim(context_factory):
    ctx = context_factory(live={"proc_vmstat": VMSTAT, "ps": PS}, windows=WINDOWS)
    result = memory.vmstat_reclaim_io(ctx)
    m = result.metrics
    assert m["workingset_refault_pages"] == 50_000_000
    assert m["refault_pages_per_s"] == pytest.approx(1157.4)
    assert m["pgpgin_gib"] == pytest.approx(190.7)
    assert m["compact_fail_pct"] == pytest.approx(60.0)
    # kswapd0 plus kswapd-1:0, whose TIME has a day prefix
    assert m["kswapd_cpu_s_since_start"] == 420 + 86_410
    assert m["oom_reaper_cpu_s_since_start"] == 120
    assert m["lmkd_cpu_s_since_start"] == 30
    assert set(by_id(result)) == {
        "vmstat_reclaim_io.page_cache_thrashing",
        "vmstat_reclaim_io.direct_reclaim",
        "vmstat_reclaim_io.compaction_failures",
    }


def test_vmstat_minutes_after_boot_has_no_rates(context_factory):
    fresh = replace(WINDOWS, boot_time=datetime(2026, 1, 15, 11, 50))
    ctx = context_factory(live={"proc_vmstat": VMSTAT}, windows=fresh)
    result = memory.vmstat_reclaim_io(ctx)
    m = result.metrics
    assert m["uptime_h"] == pytest.approx(0.17)
    assert m["pgmajfault"] == 3_000_000
    assert m["refault_pages_per_s"] is None
    assert m["allocstall_per_day"] is None
    # Compaction is a ratio, not a rate; it is still judged.
    assert set(by_id(result)) == {"vmstat_reclaim_io.compaction_failures"}
    assert any("10 min after boot" in note for note in result.notes)


def test_memory_threads_from_the_bugreport_thread_list(context_factory):
    threads = dedent(
        """\
        LABEL         USER   PID   TID  PPID   VSZ  RSS WCHAN ADDR S PRI NI RTPRIO SCH PCY     TIME CMD
        u:r:kernel:s0 root    99    99     2     0    0 0        0 S  19  0      -   0  fg 00:05:00 kswapd0
        u:r:lmkd:s0   lmkd   600   600     1  1000  100 0        0 S  19  0      -   0  fg 00:00:20 lmkd
        u:r:lmkd:s0   lmkd   600   601     1  1000  100 0        0 S  19  0      -   0  fg 00:00:05 lmkd_worker
        """,  # ruff: ignore[line-too-long] - dump lines are long
    )
    ctx = context_factory(
        live={"proc_vmstat": VMSTAT},
        sections={"PROCESSES AND THREADS (ps -A -T -Z)": threads},
        windows=WINDOWS,
    )
    m = memory.vmstat_reclaim_io(ctx).metrics
    assert m["kswapd_cpu_s_since_start"] == 300
    assert m["lmkd_cpu_s_since_start"] == 25


def test_vmstat_quiet_and_missing(context_factory):
    quiet = "workingset_refault 1000\npgmajfault 100\nallocstall_normal 1\n"
    ctx = context_factory(live={"proc_vmstat": quiet}, windows=WINDOWS)
    assert memory.vmstat_reclaim_io(ctx).findings == []
    with pytest.raises(SkipError):
        memory.vmstat_reclaim_io(context_factory(live={"battery": "x"}))


PSI_SECTIONS = {
    "PSI cpu (/proc/pressure/cpu)": (
        "some avg10=4.00 avg60=6.00 avg300=7.00 total=1800000000"
    ),
    "PSI memory (/proc/pressure/memory)": (
        "some avg10=0.30 avg60=0.50 avg300=0.60 total=130000000\n"
        "full avg10=0.00 avg60=0.10 avg300=0.10 total=50000000"
    ),
    "PSI io (/proc/pressure/io)": (
        "some avg10=1.40 avg60=1.30 avg300=1.30 total=300000000\n"
        "full avg10=1.05 avg60=0.60 avg300=0.50 total=200000000"
    ),
}


def test_psi_from_bugreport_sections(context_factory):
    ctx = context_factory(sections=PSI_SECTIONS, windows=WINDOWS)
    result = memory.psi_pressure(ctx)
    m = result.metrics
    assert m["memory_some_total_s"] == pytest.approx(130.0)
    assert m["memory_some_share_of_uptime_pct"] == pytest.approx(0.3)
    assert m["io_full_avg10_pct"] == pytest.approx(1.05)
    assert result.findings == []


def test_psi_live_with_decimal_comma_fires(context_factory):
    live = dedent(
        """\
        == cpu
        some avg10=1,50 avg60=1,00 avg300=1,00 total=1000000
        == memory
        some avg10=12,5 avg60=3,0 avg300=1,0 total=900000000
        full avg10=0,5 avg60=0,1 avg300=0,1 total=1000000
        == io
        some avg10=0,1 avg60=0,1 avg300=0,1 total=1000000
        full avg10=0,0 avg60=0,0 avg300=0,0 total=1000000
        """,
    )
    ctx = context_factory(live={"proc_pressure": live}, windows=WINDOWS)
    result = memory.psi_pressure(ctx)
    assert result.metrics["cpu_some_avg10_pct"] == pytest.approx(1.5)
    finding = by_id(result)["psi_pressure.memory_stall"]
    assert finding.window == "since_boot"
    assert finding.evidence[0].ref.startswith("live/proc_pressure.txt:")


def test_psi_minutes_after_boot_is_not_chronic(context_factory):
    fresh = replace(WINDOWS, boot_time=datetime(2026, 1, 15, 11, 50))
    sections = {
        "PSI memory (/proc/pressure/memory)": (
            "some avg10=0.10 avg60=0.10 avg300=0.10 total=60000000\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=1000000"
        ),
    }
    result = memory.psi_pressure(context_factory(sections=sections, windows=fresh))
    # 60 s of a 10-minute uptime would be a 10 % share.
    assert result.metrics["memory_some_share_of_uptime_pct"] is None
    assert result.findings == []


def test_psi_missing_is_skipped(context_factory):
    with pytest.raises(SkipError):
        memory.psi_pressure(context_factory(live={"battery": "x"}, windows=WINDOWS))


# --- zones and hotplug -------------------------------------------------------

ZONEINFO = dedent(
    """\
    Node 0, zone   Normal
      per-node stats
          nr_inactive_anon 90000
      pages free     40000
            min      2000
            low      9000
            high     10000
            spanned  1500000
            present  1400000
            managed  1400000
            protection: (0, 16000)
          nr_free_pages 40000
          nr_free_cma  28000
      pagesets
        cpu: 0
                  count: 200
                  high:  300
    Node 0, zone  Movable
      pages free     300000
            min      600
            low      3600
            high     3800
            spanned  500000
            present  500000
            managed  500000
            protection: (0, 0)
          nr_free_cma  0
    """,
)
DMESG = dedent(
    """\
    <6>[50000.100000] Built 1 zonelists, mobility grouping on.  Total pages: 1900000
    <6>[50000.100100] mem-offline: Onlined memory block mem0000000000000000
    <6>[50000.200000] oom_reaper: reaped process 23456 (.example.app), now anon-rss:0kB
    """,
)


def test_zone_above_own_min_and_hotplug(context_factory):
    ctx = context_factory(
        live={
            "proc_zoneinfo": ZONEINFO,
            "proc_meminfo": "MemFree:         1300000 kB\nCmaFree:  112000 kB\n",
            "logcat_events": log(
                "11:00:01.300", "killinfo", killinfo(23456), "lmkd", 600
            ),
        },
        sections={"KERNEL LOG (dmesg)": DMESG},
        windows=WINDOWS,
    )
    result = memory.zone_watermarks_offline(ctx)
    normal = result.tables["zones"][0]
    assert normal["free_noncma_mib"] == pytest.approx(46.9)
    # 12000 free pages are above min (2000) for allocations that prefer
    # Normal; only Movable allocations falling back here would be refused.
    assert normal["below_min"] is False
    assert normal["below_min_plus_reserve"] is True
    m = result.metrics
    assert m["zones_below_min"] == 0
    # stock lmkd: (2000 + 16000) + (600 + 0) pages against MemFree - CmaFree
    assert m["lmkd_min_watermark_mib"] == pytest.approx(72.7)
    assert m["mem_free_noncma_mib"] == pytest.approx(1160.2)
    assert m["lmkd_min_watermark_breached"] is False
    assert m["movable_zone_share_pct"] == pytest.approx(26.3)
    assert m["mem_onlined_blocks"] == 1
    assert m["first_hotplug_wall_time"] == "2026-01-15 11:00:01"
    found = by_id(result)
    assert "zone_watermarks_offline.zone_below_watermark" not in found
    assert found["zone_watermarks_offline.memory_hotplug"].basis == "measured"


def test_zone_below_its_own_min(context_factory):
    low = ZONEINFO.replace("pages free     40000", "pages free     29000")
    ctx = context_factory(
        live={"proc_zoneinfo": low, "proc_meminfo": "MemFree: 1300000 kB\n"},
        windows=WINDOWS,
    )
    result = memory.zone_watermarks_offline(ctx)
    finding = by_id(result)["zone_watermarks_offline.zone_below_watermark"]
    assert finding.severity == "medium"
    assert finding.metrics["min_mib"] == pytest.approx(7.8)
    assert "reclaim or kill" not in finding.summary
    assert finding.evidence[0].ref == "live/proc_zoneinfo.txt:1"


def test_zone_with_room_has_no_findings(context_factory):
    roomy = ZONEINFO.split("Node 0, zone  Movable")[0].replace("40000", "940000")
    ctx = context_factory(live={"proc_zoneinfo": roomy}, windows=WINDOWS)
    result = memory.zone_watermarks_offline(ctx)
    assert result.findings == []
    assert "No kernel log" in result.notes[-1]
    with pytest.raises(SkipError):
        memory.zone_watermarks_offline(context_factory(live={"battery": "x"}))


# --- activity manager configuration ------------------------------------------

AM_SETTINGS = dedent(
    """\
    ACTIVITY MANAGER SETTINGS (dumpsys activity settings) activity_manager_constants:
      max_cached_processes=60
      power_check_max_cpu_4=2

      mCustomizedMaxCachedProcesses=32
      CUR_MAX_CACHED_PROCESSES=60
      CUR_MAX_EMPTY_PROCESSES=30
    CachedAppOptimizer settings
      use_compaction=false
      use_freezer=false
      freeze_binder_enabled=true
      Apps frozen: 0
    CacheOomRanker settings
      use_oom_re_ranking=false
    """,
)
GETPROP = "[ro.build.version.sdk]: [35]\n[ro.lmk.use_minfree_levels]: [false]\n"


def test_am_config_freezer_off(context_factory):
    ctx = context_factory(live={"activity_settings": AM_SETTINGS, "getprop": GETPROP})
    result = memory.am_memory_config(ctx)
    m = result.metrics
    assert m["cur_max_cached_processes"] == 60
    assert m["use_freezer"] is False
    assert m["apps_frozen"] == 0
    assert m["sdk"] == 35
    assert "ro.lmk.use_minfree_levels=false" in m["properties"]
    found = by_id(result)
    assert found["am_memory_config.freezer_off"].severity == "medium"
    assert found["am_memory_config.compaction_off"].severity == "info"


def test_am_config_freezer_on_and_device_config_only(context_factory):
    on = AM_SETTINGS.replace("use_freezer=false", "use_freezer=true").replace(
        "Apps frozen: 0",
        "Apps frozen: 12",
    )
    ctx = context_factory(live={"activity_settings": on, "getprop": GETPROP})
    assert "am_memory_config.freezer_off" not in by_id(memory.am_memory_config(ctx))

    device_config = dedent(
        """\
        use_compaction=false
        max_cached_processes=32
        === activity_manager_native_boot
        use_freezer=false
        """,
    )
    ctx = context_factory(live={"device_config_am": device_config})
    result = memory.am_memory_config(ctx)
    assert result.metrics["use_freezer"] is False
    assert "am_memory_config.freezer_off" in by_id(result)


def test_am_config_freezer_setting_from_bugreport_settings(context_factory):
    settings = dedent(
        """\
        GLOBAL SETTINGS (user 0)
        _id:1 name:cached_apps_freezer pkg:android value:disabled default:null
        """,
    )
    ctx = context_factory(
        live={"activity_settings": AM_SETTINGS}, services={"settings": settings}
    )
    result = memory.am_memory_config(ctx)
    assert result.metrics["cached_apps_freezer_setting"] == "disabled"


def test_am_config_missing_is_skipped(context_factory):
    with pytest.raises(SkipError):
        memory.am_memory_config(context_factory(live={"battery": "x"}))


# --- process churn -----------------------------------------------------------


def start(time, pid, process, hosting="service"):
    return log(time, "am_proc_start", f"[0,{pid},10101,{process},{hosting},{{x}}]")


def churn_events():
    lines = [
        log("10:00:00.000", "screen_toggled", "1"),
        log("10:00:01.000", "device_idle_off_start", "unlocked"),
    ]
    lines += [
        start(f"10:00:{5 + s:02d}.000", 100 + s, f"com.example.job{s}")
        for s in range(25)
    ]
    lines += [
        log(
            "10:10:00.000",
            "am_kill",
            "[0,300,com.example.loop,905,excessive cpu 9000,1]",
        ),
        start("10:10:30.000", 301, "com.example.loop", "broadcast"),
        log(
            "10:20:00.000",
            "am_kill",
            "[0,301,com.example.loop,905,excessive cpu 7000,1]",
        ),
        start("10:20:10.000", 302, "com.example.loop", "broadcast"),
    ]
    lines += [
        log(
            f"10:30:00.{n}00",
            "am_proc_start",
            f"[0,{400 + n},10101,com.example.pre{n},,]",
        )
        for n in range(5)
    ]
    lines += [
        log("10:59:59.000", "battery_status", "[2,2,1,0,Li-ion]"),
        log("11:00:00.500", "battery_status", "[2,2,1,2,Li-ion]"),
        log("11:00:00.600", "battery_saver_mode", "[1,0,0,0,1,,7]"),
    ]
    lines += [
        start(f"11:00:{1 + s:02d}.000", 500 + s, f"com.example.flood{s}")
        for s in range(22)
    ]
    return "\n".join(sorted(lines))


# The windows analyzer takes the plug-in from the event log's battery_status.
CHURN_WINDOWS = replace(
    WINDOWS,
    plugged_at=datetime(2026, 1, 15, 11, 0, 0, 500_000),
    plugged_at_source="event log battery_status",
)


def test_process_churn_bursts_loops_and_plug_in(context_factory):
    ctx = context_factory(live={"logcat_events": churn_events()}, windows=CHURN_WINDOWS)
    result = memory.process_churn(ctx)
    m = result.metrics
    assert m["process_starts"] == 25 + 2 + 5 + 22
    assert m["plug_in_time"] == "2026-01-15 11:00:00.500"
    assert m["starts_60s_after_plug_in"] == 22
    top = result.tables["starts_per_minute"][0]
    assert (top["starts"], top["after_plug_in"]) == (25, False)
    assert "unlock" in top["triggers"]
    found = by_id(result)
    assert found["process_churn.start_burst"].severity == "medium"
    assert found["process_churn.plug_in_flood"].severity == "info"
    loop = result.tables["restart_loops"][0]
    assert loop["process"] == "com.example.loop"
    assert loop["restarts_outside_plug_in_and_boot"] == 2
    assert found["process_churn.restart_loops"].severity == "medium"
    assert found["process_churn.prelaunch_burst"].basis == "inferred"


def test_process_churn_on_battery_takes_the_logged_plug_in(context_factory):
    on_battery = replace(WINDOWS, on_battery_at_capture=True, plugged_at=None)
    ctx = context_factory(live={"logcat_events": churn_events()}, windows=on_battery)
    result = memory.process_churn(ctx)
    assert result.metrics["plug_in_time"] == "2026-01-15 11:00:00.500"
    assert "plug-in" in result.tables["starts_per_minute"][1]["triggers"]


def test_process_churn_ignores_start_up_after_boot(context_factory):
    booted = replace(CHURN_WINDOWS, boot_time=datetime(2026, 1, 15, 10, 0, 3))
    ctx = context_factory(live={"logcat_events": churn_events()}, windows=booted)
    result = memory.process_churn(ctx)
    # The 25-start minute 10:00 is the boot minute.
    assert result.tables["starts_per_minute"][0]["starts"] == 25
    found = by_id(result)
    assert "process_churn.start_burst" not in found
    assert any("after boot" in note for note in result.notes)
    # The 10:10 kill-restart pair is start-up work, so one pair is left.
    assert found["process_churn.restart_loops"].severity == "low"


def test_process_churn_kill_flood_after_plug_in(context_factory):
    lines = [
        log("10:59:59.000", "battery_status", "[2,2,1,0,Li-ion]"),
        log("11:00:00.500", "battery_status", "[2,2,1,2,Li-ion]"),
        start("11:00:01.000", 700, "com.example.first"),
    ]
    lines += [
        log(
            f"11:00:{2 + n:02d}.000",
            "am_kill",
            f"[0,{800 + n},com.example.k{n},905,x,1]",
        )
        for n in range(12)
    ]
    ctx = context_factory(
        live={"logcat_events": "\n".join(lines)}, windows=CHURN_WINDOWS
    )
    found = by_id(memory.process_churn(ctx))
    flood = found["process_churn.plug_in_flood"]
    assert flood.metrics == {"starts": 1, "kills": 12, "low_memory_exits": None}


def test_process_churn_quiet_and_missing(context_factory):
    quiet = "\n".join(
        start(f"10:{m:02d}:00.000", 100 + m, f"com.example.app{m}") for m in range(5)
    )
    result = memory.process_churn(
        context_factory(live={"logcat_events": quiet}, windows=WINDOWS)
    )
    assert result.findings == []
    ctx = context_factory(live={"logcat_events": log("10:00:00.000", "am_pss", "[1]")})
    with pytest.raises(SkipError):
        memory.process_churn(ctx)


def test_analyzers_are_registered():
    from androiddiag.model import REGISTRY

    names = {
        "exit_info_audit",
        "lmkd_kills",
        "kills_vs_screen_events",
        "memory_snapshot",
        "vmstat_reclaim_io",
        "psi_pressure",
        "zone_watermarks_offline",
        "am_memory_config",
        "process_churn",
    }
    assert names <= set(REGISTRY)
    assert all(REGISTRY[n].module == "androiddiag.memory" for n in names)
