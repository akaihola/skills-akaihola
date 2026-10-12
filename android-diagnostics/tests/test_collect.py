"""Tests for the collection side: the read-only guard, collect, adb_ro, sample_live.

A fake ``adb`` written into ``tmp_path`` and put first on PATH logs every call
and prints canned, invented output. No phone is needed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import adb_ro
import collect
import pytest
import sample_live
from androiddiag.catalog import FORBIDDEN_FRAGMENTS, LIVE_COMMANDS, LiveCommand
from androiddiag.readonly import (
    DeviceError,
    check_adhoc,
    check_shell,
    choose_device,
    parse_devices,
    serial_hash,
)
from conftest import SCRIPTS

SERIAL = "0123456789ABCDEF"
WIFI_SERIAL = "192.0.2.10:5555"

FAKE_ADB = dedent(
    r'''
    """Fake adb: log argv, print invented output per command."""
    import json
    import os
    import sys
    import zipfile
    from pathlib import Path

    args = sys.argv[1:]
    env = os.environ
    with Path(env["FAKE_ADB_LOG"]).open("a") as log:
        log.write(json.dumps(args) + "\n")

    DEVICES = {
        "one": [
            "0123456789ABCDEF       device usb:1-1 product:exampleprod "
            "model:Example_Phone device:example transport_id:1",
        ],
        "two": [
            "0123456789ABCDEF       device usb:1-1 product:exampleprod "
            "model:Example_Phone device:example transport_id:1",
            "192.0.2.10:5555        device product:otherprod "
            "model:Other_Phone device:other transport_id:2",
        ],
        "unauthorized": ["0123456789ABCDEF       unauthorized usb:1-1 transport_id:1"],
        "none": [],
    }

    if args[:2] == ["devices", "-l"]:
        print("* daemon started successfully")
        print("List of devices attached")
        for line in DEVICES[env.get("FAKE_ADB_DEVICES", "one")]:
            print(line)
        print()
        sys.exit(0)

    serial, command = args[1], args[2]
    if command == "bugreport":
        if env.get("FAKE_ADB_BUGREPORT") == "fail":
            print("Failed to take bugreport", file=sys.stderr)
            sys.exit(1)
        with zipfile.ZipFile(args[3], "w") as zf:
            zf.writestr("main_entry.txt", "bugreport-test.txt")
            zf.writestr("bugreport-test.txt", "== dumpstate: 2026-01-15 12:00:00\n")
        sys.exit(0)

    shell = args[3]
    if env.get("FAKE_ADB_FAIL") and env["FAKE_ADB_FAIL"] in shell:
        print(f"simulated failure on {serial}", file=sys.stderr)
        sys.exit(1)

    # How often this exact command ran before: sample n sees counters for n.
    state_path = Path(env["FAKE_ADB_STATE"])
    counts = json.loads(state_path.read_text()) if state_path.exists() else {}
    n = counts.get(shell, 0)
    counts[shell] = n + 1
    state_path.write_text(json.dumps(counts))


    def dur(ms):
        return f"{ms // 3600000}h {ms // 60000 % 60}m {ms // 1000 % 60}s {ms % 1000}ms"


    if shell.startswith("getprop ro.product.model;"):
        print("Example Phone\nexampleprod\nExampleVendor")
        print("Vendor/exampleprod/example:15/TEST.1/1:user/release-keys")
        print(env.get("FAKE_ADB_SDK", "35"))
    elif shell == "dumpsys battery":
        print("Current Battery Service state:\n  AC powered: true")
        print("  USB powered: false\n  Wireless powered: false")
        print("  Dock powered: false\n  level: 80")
    elif shell.startswith("cat /proc/uptime;"):
        print(f"{1000 + 120.5 * n:.2f} 4000.00\n{1768478400 + 120 * n}")
        print("  mWakefulness=Dozing\n  mIsPowered=true\n  mPlugType=1")
        print("  mBatteryLevel=80\n  mDeviceIdleMode=true\n  mIsPowered=true")
    elif shell == "cat /proc/net/snmp":
        print("Ip: Forwarding DefaultTTL\nIp: 1 64")
        print(
            "Tcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens "
            "AttemptFails EstabResets CurrEstab InSegs OutSegs RetransSegs "
            "InErrs OutRsts InCsumErrors"
        )
        opens, estab, rsts = 100 + 2 * n, 12 + n, 1000 + 15 * n
        print(f"Tcp: 1 200 120000 -1 {opens} 12 20 16 {estab} 5000 6000 15 4 {rsts} 0")
        print(
            "Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors "
            "SndbufErrors InCsumErrors IgnoredMulti"
        )
        udp_in, udp_out, multi = 20000 + 346 * n, 10000 + 325 * n, 3000 + 45 * n
        print(f"Udp: {udp_in} 100 10 {udp_out} 0 1 0 {multi}")
    elif shell == "cat /proc/net/snmp6":
        print(f"Ip6InReceives                   \t{500 + n}")
        print(f"Udp6InDatagrams                 \t{90 + 6 * n}")
    elif shell.startswith("dumpsys netstats |"):
        if env.get("FAKE_ADB_NO_BPF"):
            print("  mAppUidStatsMap: not available")
        else:
            print("  mAppUidStatsMap: OK\n  mStatsMapA: OK\n\n  mAppUidStatsMap:")
            print("    uid rxBytes rxPackets txBytes txPackets")
            print(f"    10101 {5200 + 624 * n} {100 + 12 * n} 1000 {10 + 12 * n}")
            print("    1000 5000 50 4000 40")
            print(f"    -253 {300 + 52 * n} {3 + n} 0 0")
            print("  mStatsMapA:\n  mIfaceStatsMap:")
            print("    ifaceIndex ifaceName rxBytes rxPackets txBytes txPackets")
            rx_bytes, rx, tx = 90000 + 64000 * n, 900 + 1222 * n, 90 + 1052 * n
            print(f"    20 wlan0 {rx_bytes} {rx} 9000 {tx}")
            print("    1 lo 100 2 100 2\n")
    elif shell.startswith("dumpsys batterystats --charged |"):
        decimal = env.get("FAKE_ADB_DECIMAL", ",")
        print(
            f"  Time on battery: {dur(3600000 + 120000 * n)} (99{decimal}1%) realtime, "
            f"{dur(1800000 + 30000 * n)} (66{decimal}9%) uptime"
        )
        print(
            f"  Time on battery screen off: {dur(3000000 + 120000 * n)} "
            f"(87{decimal}4%) realtime, {dur(1200000 + 12000 * n)} "
            f"(54{decimal}3%) uptime"
        )
        print(
            "  Wakeup reason 99 example_irq: 10m 0s 0ms "
            f"({1000 + 12 * n} times) realtime"
        )
        print(
            "  Wakeup reason Abort: Pending Wakeup Sources: example_ws: "
            f"20m 0s 0ms ({2000 + 6 * n} times) realtime"
        )
        print("  Wakeup reason -1 misconfigured IRQ 999 example realtime")
    elif shell == "cmd package list packages -U":
        print("package:com.example.app uid:10101\npackage:android uid:1000")
    else:
        print(f"invented output of: {shell}")
    ''',
)


class FakeAdb:
    """A fake adb on PATH plus helpers to read what it was asked to do."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.log = root / "adb-calls.jsonl"
        bin_dir = root / "bin"
        bin_dir.mkdir()
        exe = bin_dir / "adb"
        exe.write_text(f"#!{sys.executable}\n{FAKE_ADB}")
        exe.chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_ADB_LOG": str(self.log),
            "FAKE_ADB_STATE": str(root / "adb-state.json"),
        }
        for key, value in self.env.items():
            monkeypatch.setenv(key, value)
        self.monkeypatch = monkeypatch

    def set(self, **env: str) -> None:
        for key, value in env.items():
            self.monkeypatch.setenv(f"FAKE_ADB_{key}", value)

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def shell_commands(self) -> list[str]:
        return [c[3] for c in self.calls() if c[2:3] == ["shell"]]


@pytest.fixture
def adb(tmp_path, monkeypatch):
    return FakeAdb(tmp_path, monkeypatch)


def last_line(text: str) -> str:
    return text.strip().splitlines()[-1]


# ---------------------------------------------------------------- read-only guard


def test_every_live_command_passes_the_deny_list():
    for command in LIVE_COMMANDS:
        check_shell(command.shell)
    for _, command in sample_live.SAMPLE_COMMANDS:
        check_shell(command)


def test_batterystats_checkin_is_never_used():
    shells = [c.shell for c in LIVE_COMMANDS]
    assert "dumpsys batterystats -c" in shells
    assert not any("--checkin" in s for s in shells)


@pytest.mark.parametrize(
    "command",
    [
        "settings put global x 1",
        "dumpsys batterystats --reset",
        "dumpsys batterystats --checkin",
        "logcat -c",
        "pm clear com.example.x",
        "cat /data/x; rm -rf /",
        "dumpsys battery | sh",
        "dumpsys battery unplug",
        "dumpsys battery set level 5",
        "dumpsys deviceidle force-idle",
        "dumpsys thermalservice override-status 3",
        "dumpsys gfxinfo com.example.x reset",
        "dumpsys procstats --commit",
        "dumpsys SurfaceFlinger --latency-clear",
        "cmd deviceidle whitelist +com.example.x",
        "cmd package clear com.example.x",
        "cmd appops set com.example.x RUN_IN_BACKGROUND ignore",
        "logcat -d -c",
        "logcat -d -G 16M",
        "logcat -d -f /proc/x",
        "logcat -b events",
        "tail -f /proc/kmsg",
        "cat /proc/../data/x",
        "cat /sdcard/x",
        "cat /proc/self/root/data/x",
        "ls /proc/self/r*",
        "grep a* /proc/version",
        "date -s 2026-01-01",
        "date 010100002026",
        "ip route add 192.0.2.0/24 dev wlan0",
        "ip link set wlan0 down",
        "ss -K dst 192.0.2.1",
        "top -n 1",
        "top -b",
        "netstat -c",
        "sh -c id",
        "dumpsys",
        "cat '/proc/version'",
        "dumpsys meminfo $(id)",
        "cat /proc/version > /proc/x",
        "getprop ro.x\nreboot",
        "svc wifi disable",
        "am force-stop com.example.x",
    ],
)
def test_adhoc_rejects_state_changing_or_unknown_commands(command):
    with pytest.raises(ValueError, match=r".+"):
        check_adhoc(command)


# Each of these got past the old verb deny-list. AOSP android15-release shows
# what they do on the phone.
@pytest.mark.parametrize(
    "command",
    [
        # Clears the owner's data-limit snoozes and rewrites the policy file.
        "dumpsys netpolicy --unsnooze",
        # The dump forwards these to its shell: "motion" takes the phone out of
        # Doze, BatteryService pretends the charger input is suspended.
        "dumpsys deviceidle motion",
        "dumpsys deviceidle -u 0 motion",
        "dumpsys battery suspend_input",
        # Fake history events, an early write, re-read or rotated stats.
        "dumpsys batterystats --history-create-events 1000",
        "dumpsys batterystats --history-start 0",
        "dumpsys batterystats --read-daily",
        "dumpsys batterystats --usage",
        "dumpsys procstats --pretend-screen-on",
        "dumpsys procstats --pretend-screen-off",
        "dumpsys procstats --read",
        # Print the metrics, then delete them.
        "dumpsys wifi wifiMetricsProto",
        "dumpsys location --gnssmetrics",
        "dumpsys activity service TelephonyDebugService --metricsproto",
        "dumpsys activity service com.example.bt/.AdapterService --proto-bin",
        "dumpsys activity provider com.example.app/.DataProvider --anything",
        # "all" and "all-..." run the dump() of every app's services at once.
        "dumpsys activity service all",
        "dumpsys activity provider all",
        "dumpsys activity service all-non-platform",
        "dumpsys activity service all-platform-non-critical",
        # Sensors switched to injected data; I/O sampling interval changed.
        "dumpsys sensorservice data_injection com.example.app",
        "dumpsys storaged --time_window 3600",
        "dumpsys storaged --force",
        # dumpsys activity hands an unknown word to "am": crash, start, broadcast.
        "dumpsys activity crash com.example.app",
        "dumpsys activity start-activity com.example.app/.Main",
        "dumpsys activity broadcast -a android.intent.action.BOOT_COMPLETED",
        "dumpsys activity idle-maintenance",
        "dumpsys activity top",
        # Network probes, a forced persisting poll, frame stats reset.
        "dumpsys connectivity --diag",
        "dumpsys netstats poll",
        "dumpsys gfxinfo com.example.app framestats reset",
        "dumpsys meminfo --unreachable com.example.app",
        "dumpsys usagestats flush",
    ],
)
def test_adhoc_rejects_dumpsys_arguments_outside_the_allow_list(command):
    with pytest.raises(ValueError, match="dumpsys"):
        check_adhoc(command)


# Ways out of READ_PREFIXES, and reads that consume what they return.
@pytest.mark.parametrize(
    "command",
    [
        # mksh expands braces into extra file arguments.
        "grep {.,/sdcard/Download/notes.txt} /proc/version",
        "grep -e {.,/sdcard/x} /proc/version",
        "grep ~ /proc/version",
        "grep -r -e x #/proc/version",
        # -R follows /proc/self/root; -r without a path searches the cwd.
        "grep -R -l x /proc/self",
        "grep -r x /proc/self",
        # -S and -M take a value in toybox, which swallowed the pattern.
        "grep -r -S zzz /proc/version",
        "grep -M x y /proc/version",
        # getopt reads "-ei" as -e "i", so the next word becomes a file.
        "grep -ei /sdcard/Download/x.txt /proc/version",
        # With any -e, toybox and GNU grep read every other word as a file,
        # also one before the -e (adb shell starts in "/").
        "grep sdcard/Download/notes.txt -e . /proc/version",
        "grep sdcard/Download/notes.txt -ie . /proc/version",
        "grep /sdcard/Download/notes.txt -e . /proc/version",
        # A bare "*" expands to the file names in "/".
        "logcat -d *",
        "ls -RL /proc/self",
        "ls -LR /proc/self",
        "ls -H /proc/self",
        "cat /proc/kmsg",
        "head -c 4096 /proc/kmsg",
        "cat /proc/km*",
        "cat /sys/kernel/tracing/trace_pipe",
        "cat /sys/kernel/debug/tracing/trace_pipe",
        "cat /sys/kernel/tracing/per_cpu/cpu0/trace_pipe_raw",
        "cat /sys/kernel/tracing/trace",
        "grep x /sys/kernel/tracing/trace_pip?",
        "wc -c /sys/kernel/tracing/*",
    ],
)
def test_adhoc_rejects_escapes_and_consuming_reads(command):
    with pytest.raises(ValueError, match=r".+"):
        check_adhoc(command)


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("dumpsys batterystats --history-start 0", "--charged, -c, -a"),
        ("dumpsys procstats --read", "--hours N"),
        ("dumpsys activity service X --proto-bin", "service NAME"),
        ("dumpsys storaged --time_window 60", "--hours N, --debug"),
        ("dumpsys deviceidle motion", "takes no arguments"),
        ("grep -R x /proc/self", "no recursion"),
    ],
)
def test_adhoc_rejection_says_what_is_allowed(command, allowed):
    with pytest.raises(ValueError, match=re.escape(allowed)):
        check_adhoc(command)


def test_every_simple_live_command_passes_the_adhoc_check():
    """A catalog dump without shell syntax can be repeated through adb_ro.py."""
    simple = [c.shell for c in LIVE_COMMANDS if not set(c.shell) & set(";|'$\"")]
    assert "dumpsys batterystats --charged" in simple
    for command in simple:
        assert check_adhoc(command) == command.split()


@pytest.mark.parametrize(
    "command",
    [
        "dumpsys wifi",
        "dumpsys batterystats --charged",
        "dumpsys batterystats -c",
        "dumpsys activity exit-info",
        "dumpsys activity settings",
        "dumpsys package com.example.x",
        "dumpsys procstats --hours 24",
        # Forms the docs, follow-ups and experiments use.
        "dumpsys batterystats --power-profile",
        "dumpsys batterystats --history",
        "dumpsys batterystats --daily",
        "dumpsys batterystats --cpu",
        "dumpsys batterystats --wakeups",
        "dumpsys batterystats --charged com.example.x",
        "dumpsys procstats --hours 3 com.example.x",
        "dumpsys procstats --last 1 -c",
        "dumpsys procstats --current",
        "dumpsys procstats -a",
        "dumpsys activity services",
        "dumpsys activity processes com.example.x",
        "dumpsys activity start-info com.example.x",
        "dumpsys activity lmk",
        "dumpsys activity broadcasts history",
        "dumpsys activity service com.example.x/.SyncService",
        "dumpsys activity provider com.example.x/.DataProvider",
        "dumpsys package dexopt",
        "dumpsys meminfo 4321",
        "dumpsys meminfo -a com.example.x:remote",
        "dumpsys gfxinfo com.example.x",
        "dumpsys gfxinfo com.example.x framestats",
        "dumpsys netstats detail",
        "dumpsys dropbox --print",
        "dumpsys dropbox --print data_app_crash",
        "dumpsys storaged --hours 24",
        "dumpsys usagestats com.example.x",
        "dumpsys jobscheduler com.example.x",
        "dumpsys deviceidle",
        "dumpsys netpolicy",
        "dumpsys appwidget",
        "dumpsys -l",
        "grep -i -e wake -e sleep /proc/version",
        "grep -c -A 2 Tcp: /proc/net/snmp",
        "ls -lR /sys/class/power_supply",
        "ls /sys/kernel/tracing/trace_pipe",
        "cat /sys/kernel/tracing/trace_marker",
        "getprop ro.build.version.sdk",
        "getprop",
        "cat /proc/net/snmp",
        "cat /proc/*/status",
        "cat /sys/class/thermal/thermal_zone0/temp",
        "grep -E Tcp: /proc/net/snmp",
        "head -n 80 /proc/vmstat",
        "ls -la /vendor/etc/init",
        "wc -l /proc/net/tcp",
        "cmd deviceidle whitelist",
        "cmd deviceidle get deep",
        "cmd appops get com.example.x",
        "cmd package list packages -U",
        "logcat -d -b events -v threadtime",
        "logcat -d -s ConnectivityService:E",
        "logcat -d ActivityManager:I *:S",
        "grep -e wlan /proc/interrupts /proc/version",
        "settings get global wifi_scan_always_enabled",
        "settings list secure",
        "device_config get activity_manager use_freezer",
        "pm list packages -3 -f -U",
        "pm path com.example.x",
        "ps -A -o PID,PPID,USER,RSS,VSZ,TIME,S,NAME",
        "top -b -n 3 -d 3 -m 40",
        "ip -4 route show table all",
        "ip addr show tun0",
        "netstat -tun",
        "ss -tunap",
        "service list",
        "date +%s",
        "uptime",
        "uname -r",
        "df -h /data",
        "id",
    ],
)
def test_adhoc_accepts_read_only_commands(command):
    assert check_adhoc(command) == command.split()


@pytest.mark.parametrize(
    "command",
    ["settings 'put' global x 1", "cat /proc/x;rm -rf /", "dumpsys x\t--reset"],
)
def test_deny_list_sees_through_quotes_and_separators(command):
    with pytest.raises(ValueError, match="deny-list"):
        check_shell(command)


def test_parse_devices_reads_states_and_models():
    text = dedent(
        """\
        * daemon not running; starting now at tcp:5037
        List of devices attached
        0123456789ABCDEF       device usb:1-1 product:p model:Example_Phone device:d transport_id:1
        192.0.2.10:5555        unauthorized transport_id:2
        ABCDEF                 no permissions (user is not in the plugdev group); see [http://example.com] usb:1-2 transport_id:3
        """,  # ruff: ignore[line-too-long] - adb output lines are long
    )
    devices = parse_devices(text)
    assert [(d.serial, d.state, d.model) for d in devices] == [
        (SERIAL, "device", "Example_Phone"),
        (WIFI_SERIAL, "unauthorized", ""),
        ("ABCDEF", "no permissions", ""),
    ]


def test_choose_device_explains_problems():
    one = parse_devices(f"{SERIAL} device model:Example_Phone")
    two = [*one, *parse_devices(f"{WIFI_SERIAL} device model:Other_Phone")]
    assert choose_device(one, None).serial == SERIAL
    assert choose_device(two, WIFI_SERIAL).serial == WIFI_SERIAL
    with pytest.raises(DeviceError, match="no device attached"):
        choose_device([], None)
    with pytest.raises(DeviceError, match="Other_Phone"):
        choose_device(two, None)
    with pytest.raises(DeviceError, match="not attached"):
        choose_device(one, "198.51.100.1:5555")
    with pytest.raises(DeviceError, match="Allow USB debugging"):
        choose_device(parse_devices(f"{SERIAL} unauthorized"), None)


# ---------------------------------------------------------------- collect.py


def test_collect_writes_workdir_and_manifest(adb, tmp_path, capsys):
    code = collect.main(["--out", str(tmp_path / "out")])
    out, err = capsys.readouterr()

    assert code == 0, err
    workdir = Path(last_line(out))
    assert workdir.parent == tmp_path / "out"
    assert workdir.name.startswith("Example_Phone-")
    for command in LIVE_COMMANDS:
        assert (workdir / "live" / f"{command.key}.txt").exists(), command.key
    assert zipfile.is_zipfile(workdir / "bugreport.zip")

    manifest_text = (workdir / "manifest.json").read_text()
    assert SERIAL not in manifest_text
    manifest = json.loads(manifest_text)
    assert manifest["tool"] == "android-diagnostics collect"
    assert manifest["device"] == {
        "model": "Example Phone",
        "product": "exampleprod",
        "manufacturer": "ExampleVendor",
        "build_fingerprint": "Vendor/exampleprod/example:15/TEST.1/1:user/release-keys",
        "sdk": 35,
        "serial_sha256": serial_hash(SERIAL),
    }
    assert manifest["plugged_at_start"] == {
        "plugged": True,
        "sources": ["AC"],
        "level_pct": 80,
    }
    assert {c["status"] for c in manifest["commands"]} == {"ok"}
    assert manifest["bugreport"]["status"] == "ok"
    assert "bugreport storage" in manifest["bugreport"]["note"]
    assert manifest["started"] <= manifest["finished"]
    assert "external power" in err

    shells = adb.shell_commands()
    for shell in shells:
        check_shell(shell)
        assert not any(fragment in shell for fragment in FORBIDDEN_FRAGMENTS)
    assert "dumpsys batterystats -c" in shells
    assert not any("--checkin" in arg for call in adb.calls() for arg in call)
    assert all(call[:2] == ["-s", SERIAL] for call in adb.calls()[1:])


def test_collect_with_several_devices_needs_serial(adb, tmp_path, capsys):
    adb.set(DEVICES="two")
    assert collect.main(["--out", str(tmp_path / "out"), "--no-bugreport"]) == 2
    _, err = capsys.readouterr()
    assert "Example_Phone" in err
    assert "Other_Phone" in err
    assert "--serial" in err
    assert adb.shell_commands() == []
    assert not (tmp_path / "out").exists()


def test_collect_uses_the_chosen_serial(adb, tmp_path, capsys):
    adb.set(DEVICES="two")
    args = ["--out", str(tmp_path / "out"), "--serial", WIFI_SERIAL]
    code = collect.main([*args, "--only", "battery", "--no-bugreport"])
    capsys.readouterr()
    assert code == 0
    assert {tuple(c[:2]) for c in adb.calls()[1:]} == {("-s", WIFI_SERIAL)}


@pytest.mark.parametrize("devices", ["none", "unauthorized"])
def test_collect_without_usable_device_fails_early(adb, tmp_path, capsys, devices):
    adb.set(DEVICES=devices)
    assert collect.main(["--out", str(tmp_path / "out")]) == 2
    assert "error:" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_collect_records_a_failing_command(adb, tmp_path, capsys):
    adb.set(FAIL="dumpsys wifi")
    code = collect.main(["--out", str(tmp_path / "out"), "--no-bugreport"])
    out, _ = capsys.readouterr()
    assert code == 3
    workdir = Path(last_line(out))
    manifest_text = (workdir / "manifest.json").read_text()
    assert SERIAL not in manifest_text
    manifest = json.loads(manifest_text)
    wifi = next(c for c in manifest["commands"] if c["key"] == "wifi")
    assert wifi["status"] == "failed"
    assert wifi["exit_code"] == 1
    assert wifi["error"] == "exit code 1: simulated failure on <serial>"
    err = (workdir / "live" / "wifi.err").read_text()
    assert err.startswith("simulated failure")
    others = [c for c in manifest["commands"] if c["key"] != "wifi"]
    assert {c["status"] for c in others} == {"ok"}
    assert "bugreport" not in manifest


@dataclass(frozen=True)
class OptionalCommand(LiveCommand):
    """A catalog entry whose failure is expected on some phones."""

    optional: bool = True


@pytest.mark.parametrize(("fail", "code"), [("suspend_control", 0), ("wifi", 3)])
def test_collect_tolerates_a_failing_optional_command(adb, capsys, fail, code):
    commands = (
        LiveCommand("wifi", "dumpsys wifi", "Wi-Fi state"),
        OptionalCommand("suspend_control", "dumpsys suspend_control_internal", "x"),
    )
    adb.monkeypatch.setattr(collect, "LIVE_COMMANDS", commands)
    adb.set(FAIL=next(c.shell for c in commands if c.key == fail))
    assert collect.main(["--out", str(adb.root / "out"), "--no-bugreport"]) == code
    out, _ = capsys.readouterr()
    manifest = json.loads((Path(last_line(out)) / "manifest.json").read_text())
    entry = next(c for c in manifest["commands"] if c["key"] == fail)
    assert entry["status"] == "failed"
    assert entry["error"].startswith("exit code 1")
    assert entry.get("optional", False) is (fail == "suspend_control")


def test_collect_reports_a_failed_bugreport(adb, tmp_path, capsys):
    adb.set(BUGREPORT="fail")
    code = collect.main(["--out", str(tmp_path / "out"), "--only", "clock"])
    out, _ = capsys.readouterr()
    assert code == 4
    manifest = json.loads((Path(last_line(out)) / "manifest.json").read_text())
    assert manifest["bugreport"]["status"] == "failed"


def test_collect_skips_commands_for_newer_android(adb, tmp_path, capsys):
    adb.set(SDK="30")
    args = ["--out", str(tmp_path / "out"), "--no-bugreport"]
    code = collect.main([*args, "--only", "start_info,clock"])
    out, _ = capsys.readouterr()
    assert code == 0
    manifest = json.loads((Path(last_line(out)) / "manifest.json").read_text())
    statuses = {c["key"]: c["status"] for c in manifest["commands"]}
    assert statuses == {"clock": "ok", "start_info": "skipped"}
    assert not any("start-info" in s for s in adb.shell_commands())
    # The plug state is still checked when "battery" is not selected.
    assert manifest["plugged_at_start"]["plugged"] is True


def test_collect_dry_run_runs_nothing(adb, tmp_path, capsys):
    assert collect.main(["--out", str(tmp_path / "out"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert adb.calls() == []
    assert "dumpsys batterystats -c" in out
    assert "bugreport" in out
    assert not (tmp_path / "out").exists()


def test_collect_list_prints_the_catalog(adb, capsys):
    assert collect.main(["--list"]) == 0
    out = capsys.readouterr().out
    for command in LIVE_COMMANDS:
        assert command.key in out
    assert adb.calls() == []


@pytest.mark.usefixtures("adb")
def test_collect_rejects_unknown_keys(capsys):
    with pytest.raises(SystemExit) as exc:
        collect.main(["--only", "battery,nonsense"])
    assert exc.value.code == 2
    assert "nonsense" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("dump", "expected"),
    [
        (
            "  AC powered: false\n  USB powered: true\n  level: 42\n",
            {"plugged": True, "sources": ["USB"], "level_pct": 42},
        ),
        (
            "  AC powered: false\n  USB powered: false\n  Wireless powered: false\n",
            {"plugged": False, "sources": [], "level_pct": None},
        ),
        ("Can't find service: battery\n", None),
    ],
)
def test_plug_state(dump, expected):
    assert collect.plug_state(dump) == expected


def test_scripts_run_from_the_command_line(adb):
    for script in ("collect.py", "adb_ro.py", "sample_live.py"):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Exit codes" in proc.stdout
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "collect.py"), "--dry-run", "--only", "clock"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert adb.calls() == []


# ---------------------------------------------------------------- adb_ro.py


@pytest.mark.parametrize(
    "words",
    [
        ["settings", "put", "global", "x", "1"],
        ["dumpsys", "batterystats", "--reset"],
        ["logcat", "-c"],
        ["pm", "clear", "com.example.x"],
        ["cat", "/data/x;", "rm", "-rf", "/"],
        ["dumpsys battery | sh"],
        ["dumpsys", "deviceidle", "motion"],
        ["dumpsys", "batterystats", "--history-create-events", "10"],
    ],
)
def test_adb_ro_rejects_without_calling_adb(adb, capsys, words):
    assert adb_ro.main(["--", *words]) == 2
    assert "rejected:" in capsys.readouterr().err
    assert adb.calls() == []


@pytest.mark.usefixtures("adb")
def test_adb_ro_refuses_a_key_with_a_newline(tmp_path, capsys):
    args = ["--save", "wifi\n", "--workdir", str(tmp_path / "wd")]
    with pytest.raises(SystemExit) as exc:
        adb_ro.main([*args, "--", "dumpsys", "wifi"])
    assert exc.value.code == 2
    assert "--save KEY" in capsys.readouterr().err
    assert not (tmp_path / "wd").exists()


def test_adb_ro_prints_the_output(adb, capsys):
    assert adb_ro.main(["--", "dumpsys", "wifi"]) == 0
    assert capsys.readouterr().out == "invented output of: dumpsys wifi\n"
    assert adb.calls()[-1] == ["-s", SERIAL, "shell", "dumpsys wifi"]


def test_adb_ro_passes_on_the_exit_code(adb, capsys):
    adb.set(FAIL="cat /proc/pressure/memory")
    assert adb_ro.main(["--", "cat", "/proc/pressure/memory"]) == 1
    assert "simulated failure" in capsys.readouterr().err


@pytest.mark.usefixtures("adb")
def test_adb_ro_saves_into_the_workdir(tmp_path, capsys):
    workdir = tmp_path / "wd"
    args = ["--save", "wifi_live", "--workdir", str(workdir)]
    assert adb_ro.main([*args, "--", "dumpsys", "wifi"]) == 0
    saved = workdir / "live" / "wifi_live.txt"
    assert capsys.readouterr().out.strip() == str(saved)
    assert saved.read_text() == "invented output of: dumpsys wifi\n"
    manifest = json.loads((workdir / "manifest.json").read_text())
    assert manifest["adhoc"][0]["key"] == "wifi_live"
    assert manifest["adhoc"][0]["command"] == "dumpsys wifi"
    assert manifest["adhoc"][0]["exit_code"] == 0
    with pytest.raises(SystemExit) as exc:
        adb_ro.main([*args, "--", "dumpsys", "wifi"])
    assert exc.value.code == 2


# ---------------------------------------------------------------- sample_live.py


SNMP = dedent(
    """\
    Ip: Forwarding DefaultTTL
    Ip: 1 64
    Tcp: RtoAlgorithm RtoMin MaxConn CurrEstab OutRsts
    Tcp: 1 200 -1 12 1000
    Udp: InDatagrams IgnoredMulti
    Udp: 20000 3000
    """,
)


def test_parse_snmp_pairs_headers_with_values():
    assert sample_live.parse_snmp(SNMP) == {
        "Ip.Forwarding": 1,
        "Ip.DefaultTTL": 64,
        "Tcp.RtoAlgorithm": 1,
        "Tcp.RtoMin": 200,
        "Tcp.MaxConn": -1,
        "Tcp.CurrEstab": 12,
        "Tcp.OutRsts": 1000,
        "Udp.InDatagrams": 20000,
        "Udp.IgnoredMulti": 3000,
    }
    assert sample_live.parse_snmp("Tcp: 1 2 3\ngarbage\n") == {}


def test_parse_netstats_reads_uid_and_interface_maps():
    text = dedent(
        """\
          mAppUidStatsMap: OK

          mAppUidStatsMap:
            uid rxBytes rxPackets txBytes txPackets
            10101 624 12 52 1
            -253 100 2 0 0
            not a row
            1000 10 1 10 1
          mStatsMapA:
            ifaceIndex ifaceName tag_hex uid_int cnt_set rxBytes rxPackets
            20 wlan0 0x0 10101 1 1 1
          mIfaceStatsMap:
            ifaceIndex ifaceName rxBytes rxPackets txBytes txPackets
            20 wlan0 1000 10 500 5
            21 wlan0 10 1 0 0
        """,
    )
    maps = sample_live.parse_netstats(text)
    assert maps.uids == {
        10101: (624, 12, 52, 1),
        -253: (100, 2, 0, 0),
        1000: (10, 1, 10, 1),
    }
    assert maps.ifaces == {"wlan0": (1010, 11, 500, 5)}
    assert maps.skipped == 1


@pytest.mark.parametrize("decimal", [",", "."])
def test_parse_charged_in_both_decimal_locales(decimal):
    text = dedent(
        f"""\
          Time on battery: 5h 0m 0s 100ms (99{decimal}0%) realtime, 3h 0m 0s 200ms (60{decimal}0%) uptime
          Time on battery screen off: 4h 0m 0s 300ms (80{decimal}0%) realtime, 2h 0m 0s 400ms (50{decimal}0%) uptime
          Time on battery screen doze: 0ms (0{decimal}0%)
          Wakeup reason Abort: Pending Wakeup Sources: example_ws: 1h 0m 0s 500ms (2000 times) realtime
          Wakeup reason 99 example_irq: 40m 0s 600ms (1000 times) realtime
          Wakeup reason -1 misconfigured IRQ 999 example realtime
        """,  # ruff: ignore[line-too-long] - batterystats lines are long
    )
    parsed = sample_live.parse_charged(text)
    assert parsed["on_battery_realtime_ms"] == 18_000_100
    assert parsed["on_battery_uptime_ms"] == 10_800_200
    assert parsed["screen_off_realtime_ms"] == 14_400_300
    assert parsed["screen_off_uptime_ms"] == 7_200_400
    assert parsed["wakeup_reasons"] == {
        "Abort: Pending Wakeup Sources: example_ws": (2000, 3_600_500),
        "99 example_irq": (1000, 2_400_600),
        "-1 misconfigured IRQ 999 example": (0, 0),
    }


def test_parse_state_keeps_the_first_value():
    text = "12345.67 45678.90\n1768478400\n  mWakefulness=Dozing\n  mIsPowered=false\n"
    state = sample_live.parse_state(f"{text}  mIsPowered=true\n")
    assert state == {
        "uptime_s": 12345.67,
        "epoch_s": 1768478400,
        "wakefulness": "Dozing",
        "is_powered": False,
    }


def run_sampler(workdir: Path, *extra: str) -> int:
    return sample_live.main(["--workdir", str(workdir), "--interval", "0", *extra])


def test_sample_live_computes_deltas_and_rates(adb, tmp_path, capsys):
    workdir = tmp_path / "wd"
    assert run_sampler(workdir) == 0
    out, err = capsys.readouterr()
    report_path = workdir / "sample-diff.json"
    assert last_line(out) == str(report_path)
    assert (workdir / "live" / "sample-1-snmp.txt").exists()
    assert (workdir / "live" / "sample-2-charged.txt").exists()

    report = json.loads(report_path.read_text())
    overall = report["overall"]
    assert overall["interval_clock"] == "phone /proc/uptime"
    counters = overall["snmp"]["counters"]
    assert counters["Tcp.OutRsts"] == {
        "start": 1000,
        "end": 1015,
        "delta": 15,
        "per_min": pytest.approx(15 / 120.5 * 60, abs=0.001),
    }
    assert counters["Udp.IgnoredMulti"]["delta"] == 45
    assert counters["Udp6InDatagrams"]["delta"] == 6
    assert "Ip.Forwarding" not in counters
    assert overall["snmp"]["gauges"]["Tcp.CurrEstab"] == {"start": 12, "end": 13}

    metrics = overall["metrics"]
    assert metrics["interval_s"] == pytest.approx(120.5)
    assert metrics["tcp_outrsts_per_min"] == pytest.approx(7.469, abs=0.001)

    uids = {row["uid"]: row for row in overall["traffic"]["uids"]}
    assert set(uids) == {10101, -253}  # UID 1000 sent nothing in between
    assert uids[10101]["name"] == "com.example.app"
    assert uids[10101]["rx_packets"] == 12
    assert uids[10101]["rx_bytes_per_packet"] == 52
    assert uids[10101]["rx_period_s"] == pytest.approx(10.0)
    assert uids[-253]["name"] == "pseudo-UID -253"
    wlan0 = overall["traffic"]["interfaces"][0]
    assert (wlan0["interface"], wlan0["rx_packets"], wlan0["tx_packets"]) == (
        "wlan0",
        1222,
        1052,
    )

    wakeups = overall["wakeups"]
    assert wakeups["on_battery_s"] == pytest.approx(120.0)
    assert wakeups["awake_share_pct"] == pytest.approx(25.0)
    assert wakeups["screen_off_awake_share_pct"] == pytest.approx(10.0)
    assert wakeups["wakeups_per_h"] == pytest.approx(360.0)
    assert wakeups["suspend_aborts_per_h"] == pytest.approx(180.0)
    assert [r["reason"] for r in wakeups["reasons"]] == [
        "99 example_irq",
        "Abort: Pending Wakeup Sources: example_ws",
    ]

    assert any("external power" in w for w in report["warnings"])
    assert "external power" in err
    assert "intervals" not in report
    manifest = json.loads((workdir / "manifest.json").read_text())
    assert manifest["samples"][0]["samples"] == 2
    for shell in adb.shell_commands():
        check_shell(shell)


@pytest.mark.usefixtures("adb")
def test_sample_live_with_three_samples_reports_each_interval(tmp_path, capsys):
    assert run_sampler(tmp_path / "wd", "--samples", "3") == 0
    capsys.readouterr()
    report = json.loads((tmp_path / "wd" / "sample-diff.json").read_text())
    assert [i["to_sample"] for i in report["intervals"]] == [2, 3]
    assert report["overall"]["snmp"]["counters"]["Tcp.OutRsts"]["delta"] == 30


def test_sample_live_notes_missing_bpf_maps_and_failures(adb, tmp_path, capsys):
    adb.set(NO_BPF="1", FAIL="cat /proc/net/snmp6", DECIMAL=".")
    assert run_sampler(tmp_path / "wd") == 3
    capsys.readouterr()
    report = json.loads((tmp_path / "wd" / "sample-diff.json").read_text())
    overall = report["overall"]
    assert overall["traffic"]["uids"] == []
    assert any("Android 12" in note for note in overall["notes"])
    assert report["samples"][0]["commands"]["snmp6"]["status"] == "failed"
    assert overall["snmp"]["counters"]["Tcp.OutRsts"]["delta"] == 15
    assert overall["wakeups"]["awake_share_pct"] == pytest.approx(25.0)


def test_sample_live_refuses_to_overwrite(adb, tmp_path, capsys):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "sample-diff.json").write_text("{}")
    with pytest.raises(SystemExit) as exc:
        run_sampler(workdir)
    assert exc.value.code == 2
    assert "--force" in capsys.readouterr().err
    assert adb.calls() == []
