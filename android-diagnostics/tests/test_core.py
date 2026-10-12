"""Tests for the shared parsing helpers, the source layer and the registry."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from textwrap import dedent

import pytest
from androiddiag import catalog
from androiddiag.common import (
    PackageMap,
    fmt_duration,
    format_uid,
    infer_year,
    iter_logcat,
    load_event_log,
    load_ps,
    load_settings,
    log_span,
    parse_clock_s,
    parse_decimal,
    parse_duration_ms,
    parse_ps,
    parse_settings,
    parse_size_bytes,
    parse_uid,
    parse_utc_offset,
    pct,
    per_hour,
    ps_cpu_by_name,
    uid_class,
)
from androiddiag.model import (
    SEVERITY_RANK,
    TABLE_CAP,
    Finding,
    Registration,
    Result,
    run_order,
)
from androiddiag.source import EXCERPT_CHARS, Bugreport, Sources, Text, Workdir
from conftest import SCRIPTS, bugreport_text, make_bugreport


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1d 2h 48m 39s 700ms", 96_519_700),
        ("+1h05m05s381ms", 3_905_381),
        ("+38s482ms", 38_482),
        ("26m 40s 610ms", 1_600_610),
        ("0ms", 0),
        ("-1s", -1000),
    ],
)
def test_parse_duration_ms(text, expected):
    assert parse_duration_ms(text) == expected


def test_parse_duration_rejects_garbage():
    with pytest.raises(ValueError, match="no duration"):
        parse_duration_ms("never")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("99,1", 99.1), ("(87,4%)", 87.4), ("91.9", 91.9), ("1,234.5", 1234.5)],
)
def test_parse_decimal(text, expected):
    assert parse_decimal(text) == pytest.approx(expected)


def test_sizes():
    assert parse_size_bytes("4,52MB") == round(4.52 * 1024**2)
    assert parse_size_bytes("380KB") == 380 * 1024
    assert parse_size_bytes("12B") == 12


@pytest.mark.parametrize(
    ("text", "uid"),
    [("u0a169", 10169), ("u10a5", 1_010_005), ("u0i3", 99003), ("1000", 1000)],
)
def test_uid_round_trip(text, uid):
    assert parse_uid(text) == uid
    assert format_uid(uid) == text


def test_package_map_from_pm_list_with_paths_and_multi_user():
    text = dedent(
        """\
        package:/data/app/~~a==/com.example.one-b==/base.apk=com.example.one uid:10101
        package:com.example.two uid:10102,1010102
        package:com.example.shared uid:1000
        package:android uid:1000
        """,
    )
    packages = PackageMap.from_pm_list(text)
    assert packages.name(10101) == "com.example.one"
    assert packages.name(1_010_102) == "com.example.two"
    assert packages.name(1000) == "system"
    assert packages.packages(1000) == ["com.example.shared", "android"]
    assert packages.name(1066) == "statsd"
    assert packages.name(10999) == "u0a999"


def test_package_map_from_package_dump():
    text = dedent(
        """\
          Package [com.example.app] (1a2b3c):
            userId=10123
          Package [com.example.other] (4d5e6f):
            appId=10124
        """,
    )
    packages = PackageMap.from_package_dump(text)
    assert packages.packages(10123) == ["com.example.app"]
    assert packages.packages(10124) == ["com.example.other"]


def test_infer_year_handles_stale_boot_stamps():
    reference = datetime(2026, 1, 15, 12, 0)
    assert infer_year(1, 15, reference) == 2026
    assert infer_year(11, 18, reference) == 2025


def test_iter_logcat_with_and_without_uid_and_year():
    text = dedent(
        """\
        --------- beginning of main
        01-15 11:59:58.123  1000   611   612 I ActivityManager: Start proc 123:x
        2026-01-15 11:59:59.000  u0_a12  4321  4321 W Some Tag: wrapped: value
        not a log line
        """,
    )
    lines = list(iter_logcat(text, datetime(2026, 1, 15, 12, 0)))
    assert [(x.uid, x.pid, x.tag, x.lineno) for x in lines] == [
        ("1000", 611, "ActivityManager", 2),
        ("u0_a12", 4321, "Some Tag", 3),
    ]
    assert lines[1].message == "wrapped: value"


def test_bugreport_sections_services_members(tmp_path):
    path = make_bugreport(
        tmp_path / "br.zip",
        sections={
            "KERNEL LOG (dmesg)": "[  1.0] hello\n[  2.0] world",
            "SYSTEM LOG (logcat -d)": "short",
        },
        services={"battery": "  level: 50", "power": "mWakefulness=Asleep"},
        members={"lshal-debug/android.hardware.health@2.1.txt": "cycle 12"},
    )
    br = Bugreport(path)
    dmesg = br.section("KERNEL LOG")
    assert dmesg is not None
    assert dmesg.lines == ["[  1.0] hello", "[  2.0] world"]
    assert dmesg.origin == "bugreport:KERNEL LOG"
    assert br.lines[dmesg.first_line - 1] == "[  1.0] hello"
    battery = br.service("battery")
    assert battery is not None
    assert battery.text == "  level: 50"
    assert br.header["build"] == "TEST.1.0"
    assert br.member_names("lshal-debug/*") == [
        "lshal-debug/android.hardware.health@2.1.txt",
    ]


def test_sources_prefers_live_then_bugreport(workdir_factory):
    root = workdir_factory(
        live={"battery": "live battery"},
        services={"battery": "bugreport battery", "power": "bugreport power"},
        members={"lshal-debug/android.hardware.health@2.1.txt": "health"},
    )
    sources = Sources(Workdir(root))
    battery = sources.get("battery")
    power = sources.get("power")
    health = sources.get("health_hal")
    assert battery is not None
    assert battery.text == "live battery"
    assert power is not None
    assert power.origin == "bugreport:dumpsys power"
    assert health is not None
    assert health.text == "health"
    assert sources.get("dmesg") is None
    with pytest.raises(KeyError):
        sources.get("no-such-key")


def test_live_commands_are_read_only():
    for command in catalog.LIVE_COMMANDS:
        for fragment in catalog.FORBIDDEN_FRAGMENTS:
            assert fragment not in f" {command.shell} ", (command.key, fragment)
    keys = [c.key for c in catalog.LIVE_COMMANDS]
    assert len(keys) == len(set(keys))


def test_every_live_command_has_a_source_key():
    live_keys = {
        loc.key
        for locators in catalog.SOURCES.values()
        for loc in locators
        if isinstance(loc, catalog.Live)
    }
    assert {c.key for c in catalog.LIVE_COMMANDS} <= live_keys


def test_run_order_respects_dependencies():
    def noop(_ctx):
        return Result("x")

    regs = {
        name: Registration(name, noop, (), after, "m")
        for name, after in {
            "windows": (),
            "budget": ("a", "b"),
            "a": ("windows",),
            "b": ("windows", "a"),
        }.items()
    }
    assert [r.name for r in run_order(regs)] == ["windows", "a", "b", "budget"]


def test_analyze_cli_runs_on_empty_workdir(workdir_factory):
    root = workdir_factory(live={"battery": "  level: 50"})
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "analyze.py"), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode in {0, 3}, proc.stderr
    doc = json.loads(Path(root / "analysis.json").read_text(encoding="utf-8"))
    assert doc["schema"] == 1
    assert doc["sources"]["battery"] == "live/battery.txt"


def run_analyze(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "analyze.py"), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


# --- Formatting and small parsers ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("12:34", 754),
        ("1:02:03", 3723),
        ("125:00:01", 450_001),
        ("2-01:00:00", 176_400),
        ("00:01.50", 1.5),
        ("00:01,25", 1.25),
    ],
)
def test_parse_clock_s(text, seconds):
    assert parse_clock_s(text) == pytest.approx(seconds)


def test_parse_clock_s_rejects_garbage():
    with pytest.raises(ValueError, match="no clock time"):
        parse_clock_s("1h02m")


def test_parse_utc_offset():
    assert parse_utc_offset("+0300") == timedelta(hours=3)
    assert parse_utc_offset("-05:30") == -timedelta(hours=5, minutes=30)
    assert parse_utc_offset(None) is None
    assert parse_utc_offset("EET") is None


@pytest.mark.parametrize(
    ("seconds", "resolution", "text"),
    [
        (18_160.9, "s", "5h02m40s"),
        (18_160.9, "m", "5h02m"),
        (754, "s", "12m34s"),
        (754, "m", "12m"),
        (9.9, "s", "9s"),
        (-61, "s", "-1m01s"),
        (None, "s", "?"),
    ],
)
def test_fmt_duration(seconds, resolution, text):
    assert fmt_duration(seconds, resolution=resolution) == text


def test_pct_and_per_hour():
    assert pct(1, 3) == pytest.approx(33.3)
    assert pct(1, 3, digits=3) == pytest.approx(33.333)
    assert pct(None, 3) is None
    assert pct(1, 0) is None
    assert per_hour(30, 1800) == pytest.approx(60.0)
    assert per_hour(1, 7200, digits=2) == pytest.approx(0.5)
    assert per_hour(5, 0) is None
    assert per_hour(None, 60) is None


@pytest.mark.parametrize(
    ("uid", "third_party", "kind"),
    [
        (1000, frozenset({101}), "core"),
        (-4, frozenset({101}), "core"),
        (99_005, frozenset({101}), "isolated"),
        (10_101, frozenset({10_101}), "third_party"),
        (1_010_101, frozenset({10_101}), "third_party"),
        (10_102, frozenset({10_101}), "preinstalled_app"),
        (10_102, frozenset(), "app"),
    ],
)
def test_uid_class(uid, third_party, kind):
    assert uid_class(uid, third_party) == kind


def test_severity_rank_and_table_cap():
    assert sorted(SEVERITY_RANK, key=SEVERITY_RANK.__getitem__) == [
        "high",
        "medium",
        "low",
        "info",
    ]
    result = Result("x")
    result.add_table("rows", [{"n": i} for i in range(TABLE_CAP + 5)])
    assert len(result.tables["rows"]) == TABLE_CAP
    assert result.notes == [f"rows: showing {TABLE_CAP} of {TABLE_CAP + 5} rows"]
    result.add_table("few", [{"n": 1}], cap=3)
    assert result.tables["few"] == [{"n": 1}]
    assert len(result.notes) == 1


def test_finding_related_defaults_to_empty():
    finding = Finding("a.b", "t", "battery", "low", "measured", "snapshot", "s")
    assert finding.related == []
    assert "related" in Result("a", findings=[finding]).to_dict()["findings"][0]


def test_text_evidence_collapses_and_cuts():
    text = Text("live/x.txt", "a   b\\t c\n" + "y" * 300, first_line=10)
    assert text.evidence(0).ref == "live/x.txt:10"
    assert text.evidence(0).excerpt == "a b\\t c"
    long = text.evidence(1)
    assert len(long.excerpt) == EXCERPT_CHARS
    assert long.excerpt.endswith("...")
    assert text.evidence(1, "  chosen   words ").excerpt == "chosen words"


def test_sources_memo_builds_once(workdir_factory):
    sources = Sources(Workdir(workdir_factory()))
    calls = []

    def build():
        calls.append(1)
        return [1, 2]

    assert sources.memo("k", build) is sources.memo("k", build)
    assert calls == [1]


# --- Packages -------------------------------------------------------------------

PACKAGE_DUMP = dedent(
    """\
    Packages:
      Package [com.example.system] (aaa):
        appId=1000
        flags=[ SYSTEM HAS_CODE ]
      Package [com.example.preloaded] (bbb):
        appId=10050
        flags=[ SYSTEM HAS_CODE ]
        pkgFlags=[ SYSTEM HAS_CODE ]
      Package [com.example.store] (ccc):
        appId=10200
        flags=[ HAS_CODE ALLOW_CLEAR_USER_DATA ]
        pkgFlags=[ HAS_CODE ALLOW_CLEAR_USER_DATA ]
    """,
)


def test_package_dump_third_party():
    packages = PackageMap.from_package_dump(PACKAGE_DUMP)
    assert packages.third_party == frozenset({10200})
    assert packages.packages(10050) == ["com.example.preloaded"]
    assert packages.packages(1000) == ["com.example.system"]
    merged = packages.merge(PackageMap({}, frozenset({10300})))
    assert merged.third_party == frozenset({10200, 10300})


def test_build_packages_third_party(workdir_factory):
    import analyze

    pm_3p = "package:com.example.store uid:10201\n"
    with_list = Sources(
        Workdir(
            workdir_factory(
                live={"packages_3p": pm_3p},
                services={"package": PACKAGE_DUMP},
            ),
        ),
    )
    assert analyze.build_packages(with_list).third_party == frozenset({10201})
    dump_only = Sources(Workdir(workdir_factory(services={"package": PACKAGE_DUMP})))
    assert analyze.build_packages(dump_only).third_party == frozenset({10200})
    nothing = Sources(Workdir(workdir_factory(live={"battery": "x"})))
    assert analyze.build_packages(nothing).third_party == frozenset()


# --- Settings ---------------------------------------------------------------------

SETTINGS_LIST = dedent(
    """\
    adb_enabled=0
    low_power_sticky=1
    ===SECURE
    default_input_method=com.example.keyboard/.Ime
    search_engine={
      "name": "Example"
    }
    tts_default_synth=null
    ===SYSTEM
    screen_brightness=100
    low_power_sticky=0
    """,
)
SETTINGS_DUMP = dedent(
    """\
    Service host process PID: 1234
    CONFIG SETTINGS (user 0)
    version: -1
    _id:1 name:example/flag pkg:com.example value:true
    GLOBAL SETTINGS (user 0)
    version: 200
    _id:10 name:low_power_sticky pkg:android value:1 default:1 defaultSystemSet:true
    _id:11 name:carrier_names pkg:com.example value:Example Carrier One
    SECURE SETTINGS (user 0)
    version: 200
    _id:20 name:default_input_method pkg:android value:com.example.keyboard/.Ime default:x defaultSystemSet:true
    _id:21 name:tts_default_synth pkg:android value:null
    SYSTEM SETTINGS (user 0)
    version: 200
    _id:30 name:screen_brightness pkg:android value:100 default:50 defaultSystemSet:true tag:x
    SECURE SETTINGS (user 10)
    version: 200
    _id:40 name:default_input_method pkg:android value:com.example.other/.Ime
    """,  # ruff: ignore[line-too-long] - dump lines are long
)


@pytest.mark.parametrize("body", [SETTINGS_LIST, SETTINGS_DUMP])
def test_parse_settings_both_forms(body):
    settings = parse_settings(Text("x", body))
    assert settings.namespaced
    assert settings.value("low_power_sticky") == "1"
    assert settings.value("low_power_sticky", "global") == "1"
    assert settings.value("default_input_method") == "com.example.keyboard/.Ime"
    assert settings.value("default_input_method", "global") is None
    assert settings.value("tts_default_synth", "secure") is None
    assert settings.get("tts_default_synth", "secure") is not None
    assert settings.value("screen_brightness", "system") == "100"
    assert settings.items("system")["screen_brightness"] == "100"
    assert settings.value("no_such_key") is None
    [evidence] = settings.evidence("screen_brightness")
    assert evidence.ref.startswith("x:")
    assert "screen_brightness" in evidence.excerpt
    assert settings.evidence("no_such_key") == []


def test_settings_dump_details():
    settings = parse_settings(Text("x", SETTINGS_DUMP))
    assert settings.value("carrier_names") == "Example Carrier One"
    assert settings.value("example/flag") is None
    assert settings.value("default_input_method", "secure") == (
        "com.example.keyboard/.Ime"
    )


def test_settings_list_without_markers_searches_everything():
    settings = parse_settings(Text("x", "screen_brightness=7\n"))
    assert not settings.namespaced
    assert settings.value("screen_brightness", "system") == "7"
    assert parse_settings(Text("x", SETTINGS_LIST)).skipped == 2


def test_load_settings_falls_back_to_bugreport(context_factory):
    ctx = context_factory(services={"settings": SETTINGS_DUMP})
    settings = load_settings(ctx)
    assert settings is not None
    assert settings.text.origin == "bugreport:dumpsys settings"
    assert settings.value("low_power_sticky") == "1"
    assert load_settings(ctx) is settings
    assert load_settings(context_factory(live={"battery": "x"})) is None


# --- ps ---------------------------------------------------------------------------

PS_LIVE = dedent(
    """\
      PID  PPID USER            RSS     VSZ     TIME S NAME
        1     0 root           1000 1000000 00:00:10 S init
       90     2 root              0       0 1-02:00:05 S [kswapd0]
      500     1 system         2000 2000000 00:01:00 S example_daemon
      501     1 system         2000 2000000 00:00:30 S example_daemon
     2000   300 u0_a50         9000 9000000 01:00:00 S com.example.app
    garbage line
    """,
)
PS_THREADS = dedent(
    """\
    LABEL                 USER     PID   TID  PPID   VSZ   RSS WCHAN  ADDR S PRI  NI RTPRIO SCH PCY     TIME CMD
    u:r:init:s0           root       1     1     0  1000  100 0         0 S  19   0      -   0  fg 00:00:10 init
    u:r:vendor:s0         system   700   700     1  1000  100 0         0 S  19   0      -   0     00:00:20 example_long_da
    u:r:vendor:s0         system   700   701     1  1000  100 0         0 S  19   0      -   0  fg 00:01:40 worker thread
    u:r:app:s0            u0_a50  2000  2000   300  1000  100 0         0 S  19   0      -   0  ta 00:00:05 example.mailapp
    u:r:app:s0            u0_a50  2000  2001   300  1000  100 0         0 S  19   0      -   0  ta 00:00:15 RenderThread
    """,  # ruff: ignore[line-too-long] - dump lines are long
)


def test_parse_ps_live_layout():
    rows = parse_ps(Text("live/ps.txt", PS_LIVE))
    assert [(r.pid, r.tid, r.user, r.cpu_s, r.name) for r in rows] == [
        (1, None, "root", 10, "init"),
        (90, None, "root", 93_605, "[kswapd0]"),
        (500, None, "system", 60, "example_daemon"),
        (501, None, "system", 30, "example_daemon"),
        (2000, None, "u0_a50", 3600, "com.example.app"),
    ]
    assert rows[1].ref == "live/ps.txt:3"
    found = ps_cpu_by_name(rows, ["example_daemon", "kswapd0", "missing"])
    assert found == {"example_daemon": 90, "kswapd0": 93_605}


def test_parse_ps_thread_layout_with_blank_columns():
    rows = parse_ps(Text("bugreport:PROCESSES AND THREADS", PS_THREADS))
    assert [(r.pid, r.tid, r.cpu_s, r.name) for r in rows] == [
        (1, 1, 10, "init"),
        (700, 700, 20, "example_long_da"),
        (700, 701, 100, "worker thread"),
        (2000, 2000, 5, "example.mailapp"),
        (2000, 2001, 15, "RenderThread"),
    ]
    names = ["example_long_daemon", "com.example.mailapp", "init"]
    assert ps_cpu_by_name(rows, names) == {
        "example_long_daemon": 120,
        "com.example.mailapp": 20,
        "init": 10,
    }


def test_load_ps_prefers_live(context_factory):
    title = "PROCESSES AND THREADS (ps -A -T -Z -O pri,nice,rtprio,sched,pcy,time)"
    ctx = context_factory(live={"ps": PS_LIVE}, sections={title: PS_THREADS})
    assert load_ps(ctx)[0].tid is None
    assert load_ps(ctx) is load_ps(ctx)
    ctx = context_factory(sections={title: PS_THREADS})
    assert load_ps(ctx)[0].tid == 1
    assert load_ps(context_factory(live={"battery": "x"})) == []


# --- Event log --------------------------------------------------------------------

EVENT_LOG = dedent(
    """\
    --------- beginning of events
    01-15 10:00:00.000  1000  1500  1600 I battery_status: [3,2,1,0,Li-ion]
    01-15 10:05:00.000  1000  1500  1600 I screen_toggled: 1
    01-15 10:06:00.000  1000  1500  1600 I battery_status: [2,2,1,2,Li-ion]
    01-15 10:07:00.000  1000  1500  1600 I battery_status: [2,2,1,2,Li-ion]
    01-15 10:20:00.000  1000  1500  1600 I screen_toggled: 0
    01-15 10:30:00.000  1000  1500  1600 I battery_status: [3,2,1,0,Li-ion]
    01-15 10:31:00.000  1000  1500  1600 I screen_toggled: 2
    01-15 10:32:00.000  1000  1500  1600 I am_proc_start: [0,4321,10050,com.example.app]
    """,
)


def test_event_log_transitions(context_factory):
    ctx = context_factory(
        sections={"EVENT LOG (logcat -b events -v threadtime)": EVENT_LOG}
    )
    ctx.windows.dump_time = datetime(2026, 1, 15, 12, 0)
    log = load_event_log(ctx)
    assert load_event_log(ctx) is log
    start, end = datetime(2026, 1, 15, 10, 0), datetime(2026, 1, 15, 10, 32)
    assert log.span() == (start, end)
    screen = [(t.ts.minute, t.on) for t in log.screen_transitions()]
    assert screen == [(5, True), (20, False)]
    assert len(log.battery_states()) == 4
    power = log.power_transitions()
    assert [(t.ts.minute, t.on) for t in power] == [(6, True), (30, False)]
    first_line = ctx.sources.get("logcat_events").first_line
    assert power[0].ref == f"bugreport:EVENT LOG:{first_line + 3}"
    assert power[0].line.endswith("battery_status: [2,2,1,2,Li-ion]")
    assert [line.tag for line in log.by_tag("am_proc_start")] == ["am_proc_start"]


def test_event_log_missing(context_factory):
    log = load_event_log(context_factory(live={"battery": "x"}))
    assert log.lines == []
    assert log.span() is None
    assert log.power_transitions() == []


def test_log_span():
    reference = datetime(2026, 1, 15, 12, 0)
    span = log_span(Text("x", EVENT_LOG), reference)
    assert span == (datetime(2026, 1, 15, 10, 0), datetime(2026, 1, 15, 10, 32))
    assert log_span(Text("x", "no stamps\n"), reference) is None


# --- Catalog ----------------------------------------------------------------------


def test_catalog_optional_commands_and_settings_fallback():
    optional = {c.key for c in catalog.LIVE_COMMANDS if c.optional}
    assert optional == {"proc_pressure"}
    assert catalog.Service("settings") in catalog.SOURCES["settings"]


# --- Robust inputs (a broken zip or manifest never stops the analysis) ----------------


def test_truncated_zip_is_reported_and_live_dumps_still_used(workdir_factory):
    root = workdir_factory(live={"battery": "  level: 50"})
    whole = make_bugreport(root / "full.zip", services={"battery": "  level: 1"})
    (root / "bugreport-partial.zip").write_bytes(whole.read_bytes()[:200])
    whole.unlink()
    workdir = Workdir(root)
    assert workdir.bugreport is None
    assert workdir.problems == [
        "bugreport bugreport-partial.zip ignored: File is not a zip file",
    ]
    proc = run_analyze(root)
    assert proc.returncode in {0, 3}, proc.stderr
    doc = json.loads((root / "analysis.json").read_text(encoding="utf-8"))
    assert doc["notes"] == workdir.problems
    assert doc["sources"]["battery"] == "live/battery.txt"
    assert "note: bugreport bugreport-partial.zip ignored" in proc.stdout


def test_unreadable_zip_without_live_dumps_exits_2(tmp_path):
    root = tmp_path / "wd"
    root.mkdir()
    (root / "bugreport-x.zip").write_bytes(b"PK\x03\x04 not really a zip")
    proc = run_analyze(root)
    assert proc.returncode == 2
    assert "no readable bugreport zip" in proc.stderr
    assert "bugreport-x.zip ignored" in proc.stderr


def test_zip_without_main_text_is_reported(workdir_factory):
    root = workdir_factory(live={"battery": "  level: 50"})
    with zipfile.ZipFile(root / "bugreport-empty.zip", "w") as zf:
        zf.writestr("version.txt", "2.0")
        zf.writestr("dumpstate_log.txt", "log")
    workdir = Workdir(root)
    assert workdir.bugreport is None
    assert (
        "no main_entry.txt, bugreport-*.txt or dumpstate-*.txt" in (workdir.problems[0])
    )


def test_dumpstate_member_and_any_zip_name(tmp_path):
    root = tmp_path / "wd"
    root.mkdir()
    with zipfile.ZipFile(root / "Example phone - shared.zip", "w") as zf:
        zf.writestr("dumpstate-2026-01-15-12-00-00.txt", bugreport_text())
        zf.writestr("dumpstate_log.txt", "x" * 10_000)
    with zipfile.ZipFile(root / "photos.zip", "w") as zf:
        zf.writestr("a.jpg", "x")
    workdir = Workdir(root)
    assert workdir.bugreport_path == root / "Example phone - shared.zip"
    assert workdir.bugreport is not None
    assert workdir.bugreport.main_name == "dumpstate-2026-01-15-12-00-00.txt"
    assert workdir.bugreport.header["build"] == "TEST.1.0"
    assert workdir.problems == []


def test_truncated_manifest_is_ignored(workdir_factory):
    root = workdir_factory(live={"battery": "  level: 50"})
    (root / "manifest.json").write_text('{"device": ', encoding="utf-8")
    workdir = Workdir(root)
    assert workdir.manifest == {}
    assert workdir.problems[0].startswith("manifest.json ignored: ")
    proc = run_analyze(root)
    assert proc.returncode in {0, 3}, proc.stderr
    doc = json.loads((root / "analysis.json").read_text(encoding="utf-8"))
    assert doc["notes"] == workdir.problems


def test_analyze_bugreport_option_with_any_name(tmp_path):
    source = make_bugreport(tmp_path / "shared report.zip", services={"battery": "x"})
    root = tmp_path / "wd"
    proc = run_analyze(root, "--bugreport", source)
    assert proc.returncode in {0, 3}, proc.stderr
    assert (root / "shared report.zip").is_symlink()
    doc = json.loads((root / "analysis.json").read_text(encoding="utf-8"))
    assert doc["sources"]["battery"] == "bugreport:dumpsys battery"
    assert doc["notes"] == []

    odd = tmp_path / "report.bin"
    odd.write_bytes(source.read_bytes())
    other = tmp_path / "wd2"
    proc = run_analyze(other, "--bugreport", odd)
    assert proc.returncode in {0, 3}, proc.stderr
    assert (other / "bugreport.zip").is_symlink()


def test_analyze_bugreport_option_rejects_non_zip(tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("not a zip", encoding="utf-8")
    proc = run_analyze(tmp_path / "wd", "--bugreport", text)
    assert proc.returncode == 2
    assert "is not a zip file" in proc.stderr


def test_analyze_list_needs_no_workdir():
    proc = run_analyze("--list")
    assert proc.returncode == 0, proc.stderr
    assert "windows" in proc.stdout
    assert "needs:" in proc.stdout
    missing = run_analyze()
    assert missing.returncode == 2
    assert "WORKDIR is required" in missing.stderr


def test_analysis_json_is_deterministic():
    import analyze

    assert analyze.json_default({"b", "a", "c"}) == ["a", "b", "c"]
    assert analyze.json_default(frozenset({2, 1})) == [1, 2]
    assert analyze.json_default(datetime(2026, 1, 15, 12, 0)) == "2026-01-15 12:00:00"
