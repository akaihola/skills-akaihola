"""Tests for the log analyzers (volume, crashes, ANRs, reboots), on invented logs."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from textwrap import dedent
from zoneinfo import ZoneInfo

import pytest
from androiddiag import logs
from androiddiag.model import SkipError, Windows

DUMP = datetime(2026, 1, 15, 12, 0, 0)
BOOT = datetime(2026, 1, 15, 10, 0, 0)
WINDOWS = Windows(
    dump_time=DUMP,
    boot_time=BOOT,
    since_charge_start=DUMP - timedelta(hours=1, minutes=50),
    on_battery_at_capture=False,
    on_battery_s=6000.0,
    plugged_at=datetime(2026, 1, 15, 11, 50, 1),
    plugged_at_source="event log battery_status",
)
# Written before the clock was set at boot: a stale date months back.
STALE = datetime(2025, 12, 2, 7, 30, 11)


SYSTEM = ("1000", 1394, "I")


def _line(ts: datetime, tag: str, message: str, who=SYSTEM) -> str:
    """Return a threadtime line with year and uid; ``who`` is (uid, pid, level)."""
    uid, pid, level = who
    stamp = ts.strftime("%Y-%m-%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d}"
    return f"{stamp} {uid:>5} {pid:5d} {pid:5d} {level} {tag}: {message}"


def _repeat(start: datetime, tag: str, count: int, seconds: float, who=SYSTEM):
    step = timedelta(seconds=seconds / count)
    return [
        _line(start + i * step, tag, f"value {i} at 0x{i:x}", who) for i in range(count)
    ]


def _fatal(ts: datetime, pid: int) -> str:
    message = f"Fatal signal 6 (SIGABRT), code -1 in tid {pid} (init), pid {pid} (init)"
    return _line(ts, "libc", message, ("root", pid, "F"))


def _system_log() -> str:
    t0 = datetime(2026, 1, 15, 11, 0, 0)
    lines = [
        "--------- beginning of crash",
        _fatal(STALE, 600),
        _fatal(BOOT + timedelta(seconds=30), 601),
        "--------- beginning of system",
    ]
    # Sustained spam: 120 lines per minute for ten minutes.
    lines += _repeat(t0, "ExampleSpam", 1200, 600, ("u0_a101", 4321, "I"))
    # A one-off burst: 1100 lines inside one minute.
    lines += _repeat(t0 + timedelta(minutes=20), "ExampleBurst", 1100, 50)
    lines += [
        "--------- beginning of main",
        _line(t0 + timedelta(minutes=55), "ExampleTag", "main buffer line"),
    ]
    return "\n".join(lines) + "\n"


def _events_log() -> str:
    t0 = datetime(2026, 1, 15, 11, 0, 0)
    lines = ["--------- beginning of events"]
    lines += _repeat(t0, "am_cpu", 2000, 600)
    wtf = "[0,1394,system_server,-1,ConnectivityService,BUG: example{network{103}}]"
    lines += [_line(t0 + timedelta(seconds=40 * i), "am_wtf", wtf) for i in range(25)]
    plug = datetime(2026, 1, 15, 11, 50, 0)
    lines += [
        _line(plug, "battery_status", "[4,2,1,0,Li-ion]"),
        _line(plug + timedelta(seconds=1), "battery_status", "[2,2,1,1,Li-ion]"),
    ]
    return "\n".join(lines) + "\n"


RADIO = dedent(
    """\
    --------- beginning of radio
    01-15 11:01:00.000  1001  2800  3100 D SST     : [0] handleMessage: received event 43
    01-15 11:30:00.000  1001  2800  3100 D SST     : [0] handleMessage: received event 43
    not a log line
    """,  # ruff: ignore[line-too-long] - log lines are long
)

LOGGING_POWER = dedent(
    """\
    Statistics since last charge:
      Estimated power use (mAh):
        UID 1036: 0,46 ( cpu=0,46 )
        UID 1066: 0,36 ( cpu=0,36 )
      1036:
        Total cpu time: u=1s 0ms s=1s 0ms
        Proc logd:
          CPU: 1s 0ms usr + 1s 0ms krn ; 0ms fg
    """,
)


def _volume_ctx(context_factory, **live):
    return context_factory(live=live, windows=WINDOWS)


def _finding(result, suffix):
    found = [f for f in result.findings if f.id.endswith(suffix)]
    return found[0] if found else None


def test_template_masks_numbers_hex_and_macs():
    message = "conn 42 to 02:00:00:aa:bb:cc at 0x7fff ok"
    assert logs.template(message) == "conn N to MAC at HEX ok"


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        ("reboot,userrequested", "requested"),
        ("shutdown,battery", "battery"),
        ("shutdown,thermal", "thermal"),
        ("kernel_panic", "unexpected"),
        ("reboot,longkey", "unexpected"),
        ("watchdog,sdi_apps_reset", "unexpected"),
        ("reboot,ota", "requested"),
        ("cold", "unknown"),
    ],
)
def test_boot_reason_kind(reason, kind):
    assert logs.boot_reason_kind(reason) == kind


def test_logcat_volume_spam_burst_wtf_and_coverage(context_factory):
    ctx = _volume_ctx(
        context_factory,
        logcat_system=_system_log(),
        logcat_events=_events_log(),
        logcat_radio=RADIO,
        batterystats_charged=LOGGING_POWER,
    )
    result = logs.logcat_volume(ctx)
    m = result.metrics
    assert m["lines_logcat_radio"] == 2
    assert m["unparsed_lines"] == 1
    assert m["logd_modelled_mah"] == pytest.approx(0.46)
    assert m["logging_modelled_mah_per_h"] == pytest.approx(0.492)
    # The crash line stamped before the boot is counted but has no usable time.
    assert m["stale_stamp_lines"] == 1
    assert m["lines_logcat_system"] == 2 + 1200 + 1100 + 1
    buffers = {b["buffer"]: b for b in result.tables["buffers"]}
    assert buffers["crash"]["start"] == "2026-01-15 10:00:30"
    assert buffers["crash"]["span_min"] == pytest.approx(114.5)
    assert buffers["system"]["start"] == "2026-01-15 11:00:00"
    assert buffers["main"]["span_min"] == pytest.approx(0.0)
    assert buffers["events"]["lines"] == 2027
    tags = {r["tag"]: r for r in result.tables["tags"]}
    assert tags["ExampleSpam"]["top_uid"] == "u0_a101"
    assert tags["ExampleSpam"]["peak_during"] == "on_battery"
    spam = _finding(result, "sustained-spam")
    assert spam is not None
    assert set(spam.metrics) == {"ExampleSpam"}  # am_cpu is high-volume by design
    assert spam.severity == "low"  # logging cost below 1 mAh/h
    burst = _finding(result, "bursts")
    assert burst is not None
    assert set(burst.metrics) == {"ExampleBurst"}
    wtf = _finding(result, "repeated-wtf")
    assert wtf is not None
    assert wtf.metrics == {"ConnectivityService": 25}
    assert wtf.evidence[0].ref.startswith("live/logcat_events.txt:")
    plug_note = "Plug-in time (event log battery_status): 2026-01-15 11:50:01."
    assert plug_note in result.notes


def test_logcat_volume_quiet_logs_have_no_findings(context_factory):
    t0 = datetime(2026, 1, 15, 11, 0, 0)
    quiet = "\n".join(_repeat(t0, "ExampleTag", 300, 600)) + "\n"
    result = logs.logcat_volume(_volume_ctx(context_factory, logcat_system=quiet))
    assert not result.findings
    assert result.metrics["sustained_spam_tags"] == 0
    assert "logd_modelled_mah" not in result.metrics


def test_logcat_volume_merged_capture(context_factory):
    merged = dedent(
        """\
        --------- beginning of crash
        12-02 07:30:11.123   600   600 F libc    : Fatal signal 6 (SIGABRT), in tid 600 (init), pid 600 (init)
        --------- beginning of events
        01-15 11:00:00.000  1300  1900 I am_cpu  : [35,0,ksoftirqd/3,70000,0,40]
        --------- beginning of main
        01-15 11:59:00.000  1035  3200 D ExampleTag: hello
        """,  # ruff: ignore[line-too-long] - log lines are long
    )
    result = logs.logcat_volume(_volume_ctx(context_factory, logcat_all=merged))
    assert result.metrics["lines_logcat_all"] == 3
    assert any("merged" in note for note in result.notes)
    # The crash buffer's only line is stamped before the boot, so its first
    # usable time is the next line's.
    buffers = {b["buffer"]: b["start"] for b in result.tables["buffers"]}
    assert buffers == {
        "crash": "2026-01-15 11:00:00",
        "events": "2026-01-15 11:00:00",
        "main": "2026-01-15 11:59:00",
    }


def test_logcat_volume_splits_the_plug_in_minute(context_factory):
    """Lines after the plug-in are charging even inside the plug-in minute."""
    plug = WINDOWS.plugged_at
    before = _repeat(plug - timedelta(seconds=40), "ExamplePlug", 50, 30)
    after = _repeat(plug + timedelta(seconds=1), "ExamplePlug", 300, 50)
    early = _repeat(datetime(2026, 1, 15, 11, 0, 0), "ExampleEarly", 30, 30)
    log = "\n".join(["--------- beginning of system", *early, *before, *after])
    result = logs.logcat_volume(_volume_ctx(context_factory, logcat_system=log))
    tags = {r["tag"]: r for r in result.tables["tags"]}
    assert tags["ExamplePlug"]["peak_minute"] == "2026-01-15 11:50"
    assert tags["ExamplePlug"]["peak_per_min"] == 300  # the charging part
    assert tags["ExamplePlug"]["peak_during"] == "charging"
    assert tags["ExampleEarly"]["peak_during"] == "on_battery"


def test_logcat_volume_skips_without_logs(context_factory):
    with pytest.raises(SkipError):
        logs.logcat_volume(_volume_ctx(context_factory, dropbox="x"))


def _epoch(local: datetime) -> int:
    """Seconds since the epoch for a local time two hours ahead of UTC."""
    return int((local - timedelta(hours=2)).replace(tzinfo=UTC).timestamp())


DROPBOX = dedent(
    """\
    Drop box contents: 6 entries
    Max entries: 1000

    ========================================
    2026-01-14 09:00:00 data_app_crash (text, 300 bytes)
    Process: com.example.crashy
    Foreground: No
    java.lang.IllegalStateException: example

    ========================================
    2026-01-14 10:00:00 data_app_crash (text, 300 bytes)
    Process: com.example.crashy
    Foreground: No

    ========================================
    2026-01-14 11:00:00 data_app_crash (text, 300 bytes)
    Process: com.example.crashy
    Foreground: No

    ========================================
    2026-01-15 10:00:30 SYSTEM_BOOT (text, 469 bytes)
    isPrevious: true

    ========================================
    2026-01-15 11:30:00 data_app_anr (compressed text, 6119 bytes)
    SystemUptimeMs: 5400000
    Process: com.example.slow
    Package: com.example.slow v12 (1.2)
    Foreground: Yes

    ========================================
    2026-01-15 11:40:00 SYSTEM_TOMBSTONE (compressed text, 900 bytes)
    pid: 7461, tid: 9995, name: worker  >>> com.example.native <<<
    """,
)


def _exit_record(ts: str, process: str, reason: str) -> str:
    return (
        "        ApplicationExitInfo #0:\n"
        f"          timestamp={ts} pid=100 realUid=10120 packageUid=10120 user=0\n"
        f"          process={process} reason={reason} subreason=0 (UNKNOWN) status=0\n"
    )


EXIT_INFO = (
    "ACTIVITY MANAGER PROCESS EXIT INFO (dumpsys activity exit-info)\n"
    "  package: com.example.old\n"
    "    Historical Process Exit for uid=10120\n"
    + _exit_record("2025-12-01 10:00:00.000", "com.example.old", "6 (ANR)")
    + _exit_record("2025-12-01 11:00:00.000", "com.example.old", "6 (ANR)")
    + _exit_record("2025-12-01 12:00:00.000", "com.example.old", "6 (ANR)")
    + _exit_record(
        "2026-01-15 11:00:00.000",
        "com.example.native",
        "5 (APP CRASH(NATIVE))",
    )
    + _exit_record("2026-01-15 11:10:00.000", "com.example.lmk", "3 (LOW_MEMORY)")
)

TOMBSTONE = dedent(
    """\
    *** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***
    Build fingerprint: 'Vendor/product/device:15/TEST.1.0/1:user/release-keys'
    Timestamp: 2026-01-15 11:40:00.123456789+0200
    pid: 7461, tid: 9995, name: worker  >>> com.example.native <<<
    uid: 10130
    signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0
    """,
)

ANR_TRACE = dedent(
    """\
    Subject: Input dispatching timed out (example window)

    ----- pid 2345 at 2026-01-15 11:30:00.500000000+0200 -----
    Cmd line: com.example.slow
    """,
)


def _getprop(history: list[tuple[str, datetime]]) -> str:
    entries = "\n".join(f"{reason},{_epoch(when)}" for reason, when in history)
    return (
        "[ro.build.type]: [user]\n"
        "[sys.boot.reason]: [reboot,userrequested]\n"
        f"[persist.sys.boot.reason.history]: [{entries}]\n"
        "[persist.sys.timezone]: [Etc/GMT-2]\n"
    )


def _crash_ctx(context_factory, live, windows=WINDOWS, **members):
    return context_factory(live=live, windows=windows, members=members or None)


def test_crash_anr_audit_findings(context_factory):
    getprop = _getprop(
        [
            ("reboot,userrequested", BOOT),
            ("kernel_panic", datetime(2026, 1, 10, 8, 0, 0)),
            ("shutdown,battery", datetime(2025, 12, 1, 8, 0, 0)),
        ],
    )
    ctx = _crash_ctx(
        context_factory,
        {"dropbox": DROPBOX, "exit_info": EXIT_INFO, "getprop": getprop},
        windows=replace(WINDOWS, utc_offset="+0200"),
        **{
            "FS/data/tombstones/tombstone_00": TOMBSTONE,
            "FS/data/tombstones/tombstone_00.pb": "\x00\x01binary",
            "FS/data/anr/anr_2026-01-15-11-30-00-500": ANR_TRACE,
        },
    )
    result = logs.crash_anr_audit(ctx)
    m = result.metrics
    assert m["dropbox_entries"] == 6
    assert m["tombstones"] == 1
    assert m["newest_tombstone_process"] == "com.example.native"
    assert m["exit_info_native_total"] == 1
    assert m["exit_info_anr_total"] == 3
    assert m["boot_reason"] == "reboot,userrequested"
    assert m["battery_shutdowns_in_history"] == 1
    assert m["crash_loops_recent"] == 1
    assert m["crash_loops_older"] == 1
    tags = {r["tag"]: r["count"] for r in result.tables["dropbox_tags"]}
    assert tags == {
        "data_app_crash": 3,
        "SYSTEM_BOOT": 1,
        "data_app_anr": 1,
        "SYSTEM_TOMBSTONE": 1,
    }
    boots = result.tables["boot_reasons"]
    assert boots[1] == {
        "reason": "kernel_panic",
        "kind": "unexpected",
        "recorded_at": "2026-01-10 08:00:00",
        "clock": "local",
        "ref": "live/getprop.txt:3",
    }
    ids = {f.id: f for f in result.findings}
    loop = ids["crash_anr_audit.crash-loop"]
    assert loop.metrics == {"com.example.crashy": 3}
    assert loop.severity == "medium"
    foreground = ids["crash_anr_audit.foreground-anr-or-crash"]
    assert "com.example.slow anr" in foreground.summary
    reboot = ids["crash_anr_audit.unexpected-reboot"]
    assert reboot.metrics == {"unexpected_reboots": 1}
    assert "crash_anr_audit.no-crash-loops" not in ids


def test_crash_anr_audit_watchdog_is_high(context_factory):
    dropbox = DROPBOX + dedent(
        """\

        ========================================
        2026-01-15 11:45:00 system_server_watchdog (text, 900 bytes)
        Process: system_server
        Subject: Blocked in handler on example thread
        """,
    )
    result = logs.crash_anr_audit(_crash_ctx(context_factory, {"dropbox": dropbox}))
    finding = _finding(result, "system-server-crash")
    assert finding is not None
    assert finding.severity == "high"


def test_crash_anr_audit_quiet_when_only_boot_noise_and_old_loops(context_factory):
    t_boot = BOOT + timedelta(seconds=20)
    crash_log = [_fatal(STALE, 600)]  # written before the clock was set
    crash_log += [_fatal(t_boot + timedelta(seconds=i), 700 + i) for i in range(3)]
    t_java = BOOT + timedelta(minutes=30)
    java = [
        _line(t_java, "AndroidRuntime", "FATAL EXCEPTION: main", ("1000", 5555, "E")),
        _line(
            t_java,
            "AndroidRuntime",
            "Process: com.example.once, PID: 5555",
            ("1000", 5555, "E"),
        ),
    ]
    getprop = _getprop([("reboot,userrequested", BOOT)])
    live = {
        "exit_info": EXIT_INFO,
        "logcat_system": "\n".join(crash_log + java) + "\n",
        "getprop": getprop,
    }
    result = logs.crash_anr_audit(_crash_ctx(context_factory, live))
    assert [f.id for f in result.findings] == ["crash_anr_audit.no-crash-loops"]
    quiet = result.findings[0]
    assert quiet.severity == "info"
    assert "4 crash or ANR records fell in the first 5 minutes" in quiet.summary
    assert result.metrics["native_records_since_boot"] == 5  # 4 logcat, 1 exit-info
    stale = [r for r in result.tables["events"] if r["stale_stamp"]]
    assert [(r["since_boot"], r["during_boot"]) for r in stale] == [(True, True)]
    events = {(r["source"], r["process"]) for r in result.tables["events"]}
    assert ("logcat", "com.example.once") in events
    assert result.metrics["crash_loops_older"] == 1
    assert result.metrics["boot_reason_kind"] == "requested"
    # Without an offset source the history is shown in UTC.
    assert result.tables["boot_reasons"][0]["clock"] == "UTC"


def test_crash_anr_audit_boot_reasons_follow_daylight_saving(context_factory):
    """A winter entry gets the winter offset, not the summer offset at capture."""
    summer = Windows(
        dump_time=datetime(2026, 7, 1, 12, 0, 0),
        utc_offset="+0300",
        zone=ZoneInfo("Europe/Helsinki"),
    )
    winter_utc = datetime(2026, 1, 10, 6, 0, 0, tzinfo=UTC)
    getprop = (
        "[persist.sys.boot.reason.history]: "
        f"[kernel_panic,{int(winter_utc.timestamp())}]\n"
    )
    result = logs.crash_anr_audit(
        _crash_ctx(context_factory, {"getprop": getprop}, windows=summer),
    )
    boot = result.tables["boot_reasons"][0]
    assert (boot["recorded_at"], boot["clock"]) == ("2026-01-10 08:00:00", "local")


def test_crash_anr_audit_no_loop_from_unnamed_dropbox_entries(context_factory):
    """Listing-only dropbox entries name no process, so they form no loop."""
    tags = ["data_app_crash", "SYSTEM_TOMBSTONE", "data_app_crash", "data_app_crash"]
    listing = "\n".join(
        f"2026-01-15 11:0{i}:00 {tag} (compressed text, 900 bytes)"
        for i, tag in enumerate(tags)
    )
    result = logs.crash_anr_audit(_crash_ctx(context_factory, {"dropbox": listing}))
    assert result.metrics["unattributed_records"] == 4
    assert result.tables["loops"] == []
    assert _finding(result, "crash-loop") is None


def test_crash_anr_audit_skips_without_inputs(context_factory):
    with pytest.raises(SkipError):
        logs.crash_anr_audit(_crash_ctx(context_factory, {"ps": "  PID NAME\n"}))
