"""What to collect from the phone, and where each analyzer input can be found.

``LIVE_COMMANDS`` is the complete, fixed list of shell commands that
``collect.py`` sends to the phone. Every entry is read-only. Two look harmless
but are not and are therefore absent:

- ``dumpsys batterystats --checkin`` prints the stored *previous* charge period
  and then deletes that file (AOSP ``BatteryStatsService``: ``isRealCheckin``).
  ``-c`` prints the same checkin format for the current period and changes
  nothing.
- ``logcat -c`` clears the log buffers.

``SOURCES`` maps each logical input key to the places it can come from, in
order of preference: a live dump saved as ``live/<key>.txt`` by ``collect.py``,
a ``------ TITLE (...) ------`` section of the bugreport, a ``DUMP OF SERVICE``
block of the bugreport, or a file inside the bugreport zip.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveCommand:
    """One read-only command run through ``adb shell``."""

    key: str
    shell: str
    purpose: str
    timeout_s: int = 60
    min_sdk: int = 0
    # Permission errors are expected on many phones; a failure does not count
    # as a collection failure.
    optional: bool = False


@dataclass(frozen=True)
class Live:
    """A dump saved by ``collect.py`` as ``live/<key>.txt``."""

    key: str


@dataclass(frozen=True)
class Section:
    """A bugreport ``------ TITLE (...) ------`` section, matched on TITLE."""

    title: str


@dataclass(frozen=True)
class Service:
    """A bugreport ``DUMP OF SERVICE [PRIORITY ]name:`` block."""

    name: str


@dataclass(frozen=True)
class Member:
    """A file inside the bugreport zip; ``*`` and ``?`` glob within the path."""

    pattern: str


Locator = Live | Section | Service | Member

_LOGCAT_FORMAT = "-v threadtime -v year -v uid"

# Ordered so that the time-sensitive battery state is captured first: plugging
# the phone in ends the on-battery period and turns a sticky battery saver off.
LIVE_COMMANDS: tuple[LiveCommand, ...] = (
    LiveCommand(
        "clock",
        "date +%s; date '+%Y-%m-%d %H:%M:%S %z'; cat /proc/uptime",
        "device epoch, local time with UTC offset, and uptime for time alignment",
    ),
    LiveCommand("battery", "dumpsys battery", "plug state, level, temperature"),
    LiveCommand(
        "batterystats_charged",
        "dumpsys batterystats --charged",
        "since-last-charge discharge, wakeup reasons, per-UID power estimates",
    ),
    LiveCommand(
        "batterystats_checkin",
        "dumpsys batterystats -c",
        "checkin CSV with full history; never use --checkin (it deletes data)",
        timeout_s=120,
    ),
    LiveCommand(
        "batterystats",
        "dumpsys batterystats",
        "full text dump: history, kernel wakelocks, daily step history",
        timeout_s=180,
    ),
    LiveCommand(
        "power_profile",
        "dumpsys batterystats --power-profile",
        "OEM power-model constants (suspend and idle currents, CPU tables)",
    ),
    LiveCommand("power", "dumpsys power", "wake locks, battery saver, drain stats"),
    LiveCommand("deviceidle", "dumpsys deviceidle", "Doze state and exemptions"),
    LiveCommand(
        "deviceidle_whitelist",
        "cmd deviceidle whitelist",
        "apps exempt from battery optimisation (listing only, no arguments)",
    ),
    LiveCommand("alarm", "dumpsys alarm", "wakeup alarms per package"),
    LiveCommand(
        "jobscheduler",
        "dumpsys jobscheduler",
        "jobs and restrictions",
        timeout_s=120,
    ),
    LiveCommand("cpuinfo", "dumpsys cpuinfo", "recent per-process CPU"),
    LiveCommand("meminfo", "dumpsys meminfo", "PSS per process and OOM group"),
    LiveCommand("procstats", "dumpsys procstats --hours 24", "24 h process states"),
    LiveCommand(
        "activity_processes",
        "dumpsys activity processes",
        "running processes, OOM adjustments, cached-app limits",
    ),
    LiveCommand(
        "activity_services",
        "dumpsys activity services",
        "running and foreground services",
        timeout_s=120,
    ),
    LiveCommand(
        "exit_info",
        "dumpsys activity exit-info",
        "why processes died (low memory, CPU, crash)",
        timeout_s=120,
    ),
    LiveCommand(
        "start_info",
        "dumpsys activity start-info",
        "app start types and timings",
        min_sdk=35,
    ),
    LiveCommand(
        "device_config_am",
        "device_config list activity_manager; "
        "echo '=== activity_manager_native_boot'; "
        "device_config list activity_manager_native_boot",
        "cached-app freezer and compaction flags",
    ),
    LiveCommand("thermalservice", "dumpsys thermalservice", "thermal status"),
    LiveCommand(
        "thermal_zones",
        "for z in /sys/class/thermal/thermal_zone*; do "
        'echo "$(cat $z/type 2>/dev/null) $(cat $z/temp 2>/dev/null)"; done',
        "temperature sensors",
    ),
    LiveCommand(
        "cpufreq",
        "for d in /sys/devices/system/cpu/cpu[0-9]*/cpufreq; do "
        'echo "$d $(cat $d/scaling_cur_freq $d/scaling_min_freq '
        '$d/scaling_max_freq $d/cpuinfo_max_freq 2>/dev/null)"; done',
        "CPU frequency caps",
    ),
    LiveCommand("proc_meminfo", "cat /proc/meminfo", "kernel memory counters"),
    LiveCommand("proc_vmstat", "cat /proc/vmstat", "reclaim, refault, swap counters"),
    LiveCommand("proc_zoneinfo", "cat /proc/zoneinfo", "zone watermarks"),
    LiveCommand("graphicsstats", "dumpsys graphicsstats", "frame jank per app"),
    LiveCommand("display", "dumpsys display", "displays, including projections"),
    LiveCommand("location", "dumpsys location", "location requests per app"),
    LiveCommand("sensorservice", "dumpsys sensorservice", "active sensor listeners"),
    LiveCommand("wifi", "dumpsys wifi", "Wi-Fi state, multicast locks, wake reasons"),
    LiveCommand("connectivity", "dumpsys connectivity", "networks and VPNs"),
    LiveCommand(
        "netstats",
        "dumpsys netstats detail",
        "per-UID traffic",
        timeout_s=120,
    ),
    LiveCommand(
        "telephony_registry",
        "dumpsys telephony.registry",
        "signal strength and data state",
    ),
    LiveCommand("bluetooth_manager", "dumpsys bluetooth_manager", "BLE scanners"),
    LiveCommand("diskstats", "dumpsys diskstats", "storage and write latency"),
    LiveCommand(
        "usagestats",
        "dumpsys usagestats",
        "app usage and standby buckets",
        timeout_s=120,
    ),
    LiveCommand("dropbox", "dumpsys dropbox --print", "crashes, ANRs, watchdogs"),
    LiveCommand(
        "settings",
        "settings list global; echo '===SECURE'; settings list secure; "
        "echo '===SYSTEM'; settings list system",
        "global, secure and system settings",
    ),
    LiveCommand("getprop", "getprop", "build and vendor properties"),
    LiveCommand(
        "packages_uid",
        "cmd package list packages -U",
        "UID to package mapping",
    ),
    LiveCommand(
        "packages_3p",
        "pm list packages -3 -U",
        "third-party packages",
    ),
    LiveCommand("packages_disabled", "pm list packages -d", "disabled packages"),
    LiveCommand(
        "home_activity",
        "cmd package resolve-activity --brief "
        "-a android.intent.action.MAIN -c android.intent.category.HOME",
        "current launcher",
    ),
    LiveCommand(
        "ps",
        "ps -A -o PID,PPID,USER,RSS,VSZ,TIME,S,NAME",
        "processes with CPU time since start",
    ),
    LiveCommand(
        "top",
        "top -b -n 3 -d 3 -m 40",
        "three CPU samples three seconds apart",
        timeout_s=30,
    ),
    LiveCommand(
        "logcat_system",
        f"logcat -d -b main,system,crash {_LOGCAT_FORMAT}",
        "main, system and crash log buffers",
        timeout_s=120,
    ),
    LiveCommand(
        "logcat_events",
        f"logcat -d -b events {_LOGCAT_FORMAT}",
        "event log: process starts and kills, screen state",
    ),
    LiveCommand(
        "logcat_radio",
        f"logcat -d -b radio {_LOGCAT_FORMAT}",
        "telephony log",
    ),
    LiveCommand(
        "network_stack",
        "dumpsys network_stack",
        "packet-filter (APF) and DTIM changes caused by Wi-Fi multicast locks",
    ),
    LiveCommand(
        "package_dexopt",
        "dumpsys package dexopt",
        "ART compiler filter per package (only the dexopt section)",
        timeout_s=120,
    ),
    LiveCommand(
        "rollback",
        "dumpsys rollback",
        "mainline rollback records, which bracket the last OTA install",
    ),
    LiveCommand(
        "storaged_service",
        "dumpsys storaged",
        "per-boot I/O intervals split by charger state",
    ),
    LiveCommand("kernel_release", "uname -r", "kernel release for known issues"),
    LiveCommand(
        "activity_settings",
        "dumpsys activity settings",
        "cached-process limits, cached-app freezer and compaction state",
    ),
    LiveCommand(
        "proc_pressure",
        'for r in cpu memory io; do echo "== $r"; cat /proc/pressure/$r; done',
        "pressure stall information (PSI) since boot",
        optional=True,
    ),
    LiveCommand(
        "activity_lmk",
        "dumpsys activity lmk",
        "lmkd kills since boot counted by the activity manager, by oom_adj",
    ),
    LiveCommand("isub", "dumpsys isub", "Wi-Fi calling and VoLTE switches per SIM"),
    LiveCommand(
        "vpn_management",
        "dumpsys vpn_management",
        "VPN owner, always-on and lockdown state",
    ),
)

# Substrings that must never appear in a command sent to the phone. Tests
# check LIVE_COMMANDS against this list; adb_ro.py enforces it at run time.
FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "--checkin",
    "--reset",
    "--enable",
    "--disable",
    "--write",
    "logcat -c",
    "settings put",
    "settings delete",
    "settings reset",
    "device_config put",
    "device_config delete",
    "device_config reset",
    "device_config set",
    " set-",
    "pm clear",
    "pm uninstall",
    "pm disable",
    "pm enable",
    "pm grant",
    "pm revoke",
    "am force-stop",
    "am kill",
    "am start",
    "am broadcast",
    "appops set",
    "svc ",
    "input tap",
    "input swipe",
    "input text",
    "input keyevent",
    "reboot",
    "cmd package clear",
    "cmd package uninstall",
    "cmd package disable",
    "cmd package enable",
    "cmd package grant",
    "cmd package revoke",
    "cmd battery",
    "dumpsys battery set",
    "dumpsys battery unplug",
    "dumpsys battery reset",
    "force-idle",
    "ss -K",
    " rm ",
    "setprop",
)

SOURCES: dict[str, tuple[Locator, ...]] = {
    "clock": (Live("clock"),),
    "battery": (Live("battery"), Service("battery")),
    "batterystats": (Live("batterystats"), Service("batterystats")),
    # --charged has no bugreport twin; the full dump contains the same
    # "Statistics since last charge" block, so analyzers may fall back to it.
    "batterystats_charged": (Live("batterystats_charged"),),
    "batterystats_checkin": (
        Section("CHECKIN BATTERYSTATS"),
        Live("batterystats_checkin"),
    ),
    "power_profile": (Live("power_profile"),),
    "power": (Live("power"), Service("power")),
    "deviceidle": (Live("deviceidle"), Service("deviceidle")),
    "deviceidle_whitelist": (Live("deviceidle_whitelist"),),
    "alarm": (Live("alarm"), Service("alarm")),
    "jobscheduler": (Live("jobscheduler"), Service("jobscheduler")),
    "cpuinfo": (Live("cpuinfo"), Service("cpuinfo")),
    "meminfo": (Live("meminfo"), Service("meminfo")),
    "procstats": (Live("procstats"), Service("procstats")),
    "procstats_checkin": (Section("CHECKIN PROCSTATS"),),
    "usagestats_checkin": (Section("CHECKIN USAGESTATS"),),
    "netstats_checkin": (Section("CHECKIN NETSTATS"),),
    "package_checkin": (Section("CHECKIN PACKAGE"),),
    "activity_processes": (Live("activity_processes"),),
    "activity_services": (Live("activity_services"),),
    "activity": (Service("activity"),),
    "exit_info": (Live("exit_info"),),
    "start_info": (Live("start_info"),),
    "device_config_am": (Live("device_config_am"),),
    "thermalservice": (Live("thermalservice"), Service("thermalservice")),
    "thermal_zones": (Live("thermal_zones"),),
    "cpufreq": (Live("cpufreq"),),
    "proc_meminfo": (Live("proc_meminfo"), Section("MEMORY INFO")),
    "proc_vmstat": (Live("proc_vmstat"), Section("VIRTUAL MEMORY STATS")),
    "proc_zoneinfo": (Live("proc_zoneinfo"), Section("ZONEINFO")),
    "psi_cpu": (Section("PSI cpu"),),
    "psi_memory": (Section("PSI memory"),),
    "psi_io": (Section("PSI io"),),
    "graphicsstats": (Live("graphicsstats"), Service("graphicsstats")),
    "display": (Live("display"), Service("display")),
    "location": (Live("location"), Service("location")),
    "sensorservice": (Live("sensorservice"), Service("sensorservice")),
    "wifi": (Live("wifi"), Service("wifi")),
    "connectivity": (Live("connectivity"), Service("connectivity")),
    "connmetrics": (Service("connmetrics"),),
    "netstats": (Live("netstats"), Service("netstats")),
    "telephony_registry": (
        Live("telephony_registry"),
        Service("telephony.registry"),
    ),
    "bluetooth_manager": (Live("bluetooth_manager"), Service("bluetooth_manager")),
    "diskstats": (Live("diskstats"), Service("diskstats")),
    "storaged": (Section("STORAGED IO INFO"), Service("storaged")),
    "usagestats": (Live("usagestats"), Service("usagestats")),
    "dropbox": (Live("dropbox"), Service("dropbox")),
    # The bugreport's settings tables are the fallback (common.parse_settings
    # reads both forms).
    "settings": (Live("settings"), Service("settings")),
    "getprop": (Live("getprop"), Section("SYSTEM PROPERTIES")),
    "packages_uid": (Live("packages_uid"),),
    "packages_3p": (Live("packages_3p"),),
    "packages_disabled": (Live("packages_disabled"),),
    "package": (Service("package"),),
    "home_activity": (Live("home_activity"),),
    "ps": (Live("ps"),),
    "ps_threads": (Section("PROCESSES AND THREADS"),),
    "process_times": (Section("PROCESS TIMES"),),
    "top": (Live("top"), Section("CPU INFO")),
    "logcat_system": (Live("logcat_system"), Section("SYSTEM LOG")),
    "logcat_events": (Live("logcat_events"), Section("EVENT LOG")),
    "logcat_radio": (Live("logcat_radio"), Section("RADIO LOG")),
    "dmesg": (Section("KERNEL LOG"),),
    "suspend_control": (Service("suspend_control_internal"),),
    "health_hal": (Member("lshal-debug/android.hardware.health*"),),
    "powerstats": (Service("powerstats"),),
    "arp": (Section("ARP CACHE"),),
    "update_engine_logs": (Member("FS/data/misc/update_engine_log/*"),),
    "tombstones": (Member("FS/data/tombstones/*"),),
    # IpClient log: packet-filter (APF) installs with their multicast and doze
    # flags, and DTIM multiplier changes driven by Wi-Fi multicast locks.
    "network_stack": (Live("network_stack"), Service("network_stack")),
    # IPv6 neighbours (MAC to address), to name the senders of Wi-Fi wake packets.
    "ipv6_neigh": (Section("IPv6 ND CACHE"),),
    # Compiler filter per package. The full package dump in a bugreport can
    # time out before its "Dexopt state:" block, so the live dump comes first.
    "package_dexopt": (Live("package_dexopt"), Service("package")),
    # Mainline rollback records; their lifecycle brackets the last OTA install.
    "rollback": (Live("rollback"), Service("rollback")),
    # Per-boot I/O intervals split by charger state (the per-UID table since
    # boot is under "storaged").
    "storaged_service": (Live("storaged_service"), Service("storaged")),
    "kernel_release": (Live("kernel_release"),),
    # Activity manager constants and the CachedAppOptimizer (freezer,
    # compaction) block; the full bugreport activity dump is under "activity".
    "activity_settings": (Live("activity_settings"),),
    # /proc/pressure/{cpu,memory,io} with "== <resource>" headers.
    "proc_pressure": (Live("proc_pressure"),),
    # All device_config flags as "namespace/key=value" (bugreport only; the
    # live collection keeps just the activity_manager namespaces).
    "device_config": (Service("device_config"),),
    # Per-process "** MEMINFO in pid N [name] **" blocks with SwapPss; the
    # summary-only live meminfo lacks them.
    "meminfo_detail": (Service("meminfo"),),
    # The activity manager's lmkd kill counter since boot (not a ring buffer);
    # analyzers fall back to the same block inside the "activity" dump.
    "activity_lmk": (Live("activity_lmk"),),
    # Settings tables per namespace and user ("SECURE SETTINGS (user 0)" with
    # "_id:N name:K pkg:P value:V" rows): the bugreport fallback for "settings".
    "settings_dump": (Service("settings"),),
    # The PREVIOUS charge period as printed by the destructive
    # "dumpsys batterystats --checkin". collect.py never runs that command;
    # a user may supply its output as live/batterystats_checkin_previous.txt.
    "batterystats_checkin_previous": (Live("batterystats_checkin_previous"),),
    # AIDL health HAL (Android 13+), the successor of the HIDL lshal dump in
    # "health_hal": cycle count, full charge, design capacity.
    "health_aidl": (Service("android.hardware.health.IHealth/default"),),
    # Subscriptions with the Wi-Fi calling and VoLTE switches per SIM.
    "isub": (Live("isub"), Service("isub")),
    # VPN owner UID, always-on and lockdown history (Android 14+).
    "vpn_management": (Live("vpn_management"), Service("vpn_management")),
    # "dumpsys activity service all-platform-non-critical": includes the
    # phone process's AccessNetworksManager log of IMS transport preferences.
    "app_services_platform": (Section("APP SERVICES PLATFORM"),),
    # A combined "logcat -b all -d -v threadtime" capture supplied by the user.
    # Buffers are merged by time, so lines cannot be told apart by buffer;
    # analyzers use it only when the per-buffer dumps are missing.
    "logcat_all": (Live("logcat_all"),),
    # ANR trace files (Subject, pid and time, then thread stacks).
    "anr_traces": (Member("FS/data/anr/*"),),
}
