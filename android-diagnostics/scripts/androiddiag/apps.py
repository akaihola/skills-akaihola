"""Per-app view: UID mapping, background activity and third-party inventory.

Three analyzers share the parsers in this module.

``uid_package_map``
    How many UIDs seen in batterystats can be named, which UIDs several
    packages share, which are isolated or pseudo UIDs, and how much modelled
    power sits on UIDs that no installed package explains.
``app_background_activity``
    The modelled drain split into core UIDs, third-party apps and preinstalled
    apps (screen and non-screen), and a per-UID table of background
    indicators on battery: foreground-service time, screen-off CPU, Bluetooth
    LE scans, wakeup alarms and time left on top with the screen off. Long BLE
    scans, app background power and frequent wakeup alarms have their own
    findings in other modules; this one flags only the third-party share and
    apps left on top with the screen off.
``third_party_apps``
    One row per third-party app: last use, standby bucket, battery-optimisation
    exemption, foreground services, procstats run time and memory, modelled
    power, alarms and its notification-listener, accessibility and keyboard
    roles. It flags dormant apps that still run (one finding for all of
    them), persistent foreground services, exempt apps that use background
    energy, and duplicate launchers or keyboards.

Usage statistics count only time on screen. An app with zero launches may
still be used through its background features (push messages, watch or
desktop sync), so every dormancy finding leaves the decision to the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Any

from .batterystats import load_since_charge
from .common import (
    FIRST_APPLICATION_UID,
    FIRST_ISOLATED_UID,
    PER_USER_RANGE,
    SYSTEM_UIDS,
    format_uid,
    load_settings,
    parse_clock_s,
    parse_decimal,
    parse_duration_ms,
    parse_size_bytes,
    parse_uid,
    pct,
    per_hour,
    uid_class,
)
from .model import Finding, Result, SkipError, analyzer, link

if TYPE_CHECKING:
    from .batterystats import SinceCharge, UidPower
    from .common import PackageMap, Settings
    from .model import Context, Evidence, Windows
    from .source import Text

# --- Thresholds -------------------------------------------------------------

# An app not opened for a month is dormant. Thirty days skips apps used weekly
# or on a monthly trip; the original audit used the same cut-off.
DORMANT_DAYS = 30
# A process alive (in any non-cached state, foreground use included) for at
# least this share of the procstats window runs all the time.
PERSISTENT_PCT = 90.0
# A dormant app whose process stayed alive for a quarter of the window runs in
# the background, rather than waking up now and then for a sync.
BACKGROUND_PCT = 25.0
# An hour of Bluetooth LE scanning on battery is far beyond the seconds that
# finding a nearby device takes.
BLE_SCAN_FLAG_S = 3600
# Modelled energy outside the screen and foreground use of 0.2 mAh/h (1-2% of
# a 10-20 mAh/h healthy idle drain, a general benchmark rather than a
# measurement), or ten seconds of screen-off CPU per hour, shows steady
# background work. It marks dormant apps as active and shows that exempt apps
# use their exemption.
ACTIVE_BG_MAH_PER_H = 0.2
ACTIVE_SCREEN_OFF_CPU_S_PER_H = 10.0
# An app that stays the top activity for half an hour with the screen off
# keeps its process at foreground priority while the user is away.
TOP_SLEEPING_FLAG_S = 1800
# More than one wakeup alarm every 10 minutes wakes the phone from Doze often
# enough to matter.
WAKEUP_ALARMS_PER_H = 6.0
# When third-party non-screen energy is below 10% of the measured drain, app
# changes cannot fix the drain; above 25% they are a main lever.
APP_SHARE_MINOR_PCT = 10.0
APP_SHARE_MAJOR_PCT = 25.0
# Modelled power on UIDs that no package explains is worth a finding from
# 5 mAh, a quarter to half an hour of a healthy 10-20 mAh/h idle drain; less
# does not change any conclusion.
UNMAPPED_MAH_FLAG = 5.0
# Three enabled keyboards or more is worth listing.
SEVERAL_IMES = 3

_MS_PER_DAY = 86_400_000
# Dumps print "never" as the epoch in local time, e.g. 1970-01-01 02:00:00.
_EPOCH_YEAR = 1970
_LAUNCHER_FALLBACK = "com.android.settings"
# Per-state mAh are printed with three significant digits, so their sum may
# exceed the total by rounding; beyond 1% the state data is inconsistent.
_STATE_SUM_TOLERANCE = 1.01
# Evidence kinds the dormant-active finding cites per app, and its total cap.
_DORMANT_EVIDENCE = ("usage", "fgs", "bt", "power", "battery_uid", "procstats")
_DORMANT_EVIDENCE_CAP = 24

# Foreground-service type bits, AOSP android.content.pm.ServiceInfo.
FGS_TYPES = {
    0x1: "dataSync",
    0x2: "mediaPlayback",
    0x4: "phoneCall",
    0x8: "location",
    0x10: "connectedDevice",
    0x20: "mediaProjection",
    0x40: "camera",
    0x80: "microphone",
    0x100: "health",
    0x200: "remoteMessaging",
    0x400: "systemExempted",
    0x800: "shortService",
    0x1000: "fileManagement",
    0x2000: "mediaProcessing",
    0x40000000: "specialUse",
}

# App standby buckets, AOSP android.app.usage.UsageStatsManager.
STANDBY_BUCKETS = {
    5: "exempted",
    10: "active",
    20: "working_set",
    30: "frequent",
    40: "rare",
    45: "restricted",
    50: "never",
}


def _component_package(component: str) -> str:
    return component.split("/", 1)[0].strip()


def setting_components(settings: Settings | None, key: str) -> list[str]:
    """Split a ``:``-separated component list, dropping IME subtype ids."""
    raw = settings.value(key) if settings else None
    if not raw:
        return []
    return [part.split(";", 1)[0] for part in raw.split(":") if "/" in part]


def decode_fgs_types(mask: int) -> list[str]:
    """Return the foreground-service type names set in ``mask``."""
    names = [name for bit, name in FGS_TYPES.items() if mask & bit]
    unknown = mask & ~sum(FGS_TYPES)
    if unknown:
        names.append(f"0x{unknown:x}")
    return names


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


# --- Package lists ----------------------------------------------------------

_PM_LINE_RE = re.compile(
    r"(?:^package:|=)(?P<pkg>[A-Za-z][\w.]*) uid:(?P<uids>[\d,]+)$"
)


@dataclass
class ThirdParty:
    """The third-party packages, by package name."""

    app_ids: dict[str, int]
    evidence: dict[str, Evidence]
    source: str
    multi_user: int = 0


def parse_pm_list(text: Text) -> ThirdParty:
    """Parse ``pm list packages -3 -U`` (with or without ``-f`` apk paths).

    Multi-user installs list one UID per user (``uid:10208,1010208``).
    """
    app_ids: dict[str, int] = {}
    evidence: dict[str, Evidence] = {}
    multi_user = 0
    for i, line in enumerate(text.lines):
        m = _PM_LINE_RE.search(line.strip())
        if not m:
            continue
        uids = [int(u) for u in m["uids"].split(",") if u]
        if not uids or m["pkg"] in app_ids:
            continue
        multi_user += len(uids) > 1
        app_ids[m["pkg"]] = uids[0] % PER_USER_RANGE
        evidence[m["pkg"]] = text.evidence(i, f"package:{m['pkg']} uid:{m['uids']}")
    return ThirdParty(app_ids, evidence, text.origin, multi_user)


@dataclass
class PackageState:
    """Facts about one package from ``dumpsys package``."""

    app_id: int | None = None
    first_install: datetime | None = None
    not_launched: bool | None = None
    index: int = 0


@dataclass
class PackageDump:
    """The parts of ``dumpsys package`` this module uses."""

    text: Text
    packages: dict[str, PackageState] = field(default_factory=dict)
    home: str | None = None
    home_index: int | None = None
    home_candidates: list[str] = field(default_factory=list)
    recents: str | None = None
    recents_index: int | None = None


# Section names start with a capital letter. Some builds (seen on Honor) print
# unindented "<package> overlay paths:" lines inside "Packages:".
_TOP_HEADER_RE = re.compile(r"^(?P<name>[A-Z][^:]*):$")
_PKG_BLOCK_RE = re.compile(r"^\s+Package \[(?P<pkg>[\w.]+)\]")
_PKG_APPID_RE = re.compile(r"^\s+(?:appId|userId)=(?P<id>\d+)")
_PKG_USER0_RE = re.compile(r"^\s+User 0: .*\bnotLaunched=(?P<nl>true|false)")
_PKG_FIRST_INSTALL_RE = re.compile(
    r"^\s+firstInstallTime=(?P<t>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)",
)
_PREF_COMPONENT_RE = re.compile(r"^\s+[0-9a-f]+ (?P<comp>[\w.]+/[\w.$]+)$")
_PLAIN_COMPONENT_RE = re.compile(r"^\s+(?P<comp>[\w.]+/[\w.$]+)$")
_HOME_CATEGORY = 'Category: "android.intent.category.HOME"'


class _PackageDumpParser:
    """A single pass over ``dumpsys package`` (about 120k lines)."""

    def __init__(self, text: Text) -> None:
        self.dump = PackageDump(text)
        self.section = ""
        self.current: PackageState | None = None
        self.in_user0 = False
        self.component: tuple[str, int] | None = None
        self.candidates: list[str] = []
        self.selecting = False
        self.after_recents = False

    def run(self) -> PackageDump:
        for i, line in enumerate(self.dump.text.lines):
            if m := _TOP_HEADER_RE.match(line):
                self.section = m["name"]
                self.current = None
                continue
            if self.section == "Known Packages":
                self._known(i, line)
            elif self.section == "Preferred Activities User 0":
                self._preferred(i, line)
            elif self.section in {"Packages", "Hidden system packages"}:
                self._package(i, line)
        return self.dump

    def _known(self, i: int, line: str) -> None:
        if line.strip() == "Recents:":
            self.after_recents = True
        elif self.after_recents:
            self.after_recents = False
            if re.fullmatch(r"\s+[\w.]+", line):
                self.dump.recents = line.strip()
                self.dump.recents_index = i

    def _preferred(self, i: int, line: str) -> None:
        if m := _PREF_COMPONENT_RE.match(line):
            self.component = (m["comp"], i)
            self.candidates = []
            self.selecting = False
        elif line.strip() == "Selected from:":
            self.selecting = True
        elif self.selecting and (m := _PLAIN_COMPONENT_RE.match(line)):
            self.candidates.append(m["comp"])
        elif _HOME_CATEGORY in line and self.component:
            self.dump.home, self.dump.home_index = self.component
            self.dump.home_candidates = list(self.candidates)
        elif line.strip().startswith(("Action:", "Category:")):
            self.selecting = False

    def _package(self, i: int, line: str) -> None:
        if m := _PKG_BLOCK_RE.match(line):
            state = self.dump.packages.setdefault(m["pkg"], PackageState(index=i))
            self.current = state
            self.in_user0 = False
            return
        state = self.current
        if state is None:
            return
        if (m := _PKG_APPID_RE.match(line)) and state.app_id is None:
            state.app_id = int(m["id"]) % PER_USER_RANGE
        elif m := _PKG_USER0_RE.match(line):
            self.in_user0 = True
            state.not_launched = m["nl"] == "true"
        elif re.match(r"^\s+User \d+:", line):
            self.in_user0 = False
        elif self.in_user0 and (m := _PKG_FIRST_INSTALL_RE.match(line)):
            try:
                stamp = datetime.strptime(m["t"], "%Y-%m-%d %H:%M:%S")
            except ValueError:  # a damaged line such as month 13
                return
            state.first_install = stamp if stamp.year > _EPOCH_YEAR else None


def parse_package_dump(text: Text) -> PackageDump:
    """Parse ``dumpsys package``: app ids, user-0 install state, Home, Recents."""
    return _PackageDumpParser(text).run()


_CHECKIN_PKG_RE = re.compile(r"^pkg,(?P<pkg>[\w.]+),(?P<app_id>\d+),")
_CHECKIN_USER0_RE = re.compile(
    r"^pkg-usr,0,(?P<flags>[A-Za-z]+),[^,]*,[^,]*,(?P<first>\d+),"
)


def parse_package_checkin(text: Text) -> dict[str, PackageState]:
    """Parse ``dumpsys package --checkin``: app id, never-launched flag, install time.

    The user flags field encodes states as upper or lower case letters; ``l``
    means the app was never launched (AOSP ``dumpPackagesLPr`` checkin).
    Install times are epoch milliseconds, converted to UTC wall time.
    """
    result: dict[str, PackageState] = {}
    current: PackageState | None = None
    for i, line in enumerate(text.lines):
        if m := _CHECKIN_PKG_RE.match(line):
            current = result.setdefault(
                m["pkg"],
                PackageState(app_id=int(m["app_id"]) % PER_USER_RANGE, index=i),
            )
        elif current and (m := _CHECKIN_USER0_RE.match(line)):
            current.not_launched = "l" in m["flags"]
            first = int(m["first"])
            try:
                stamp = datetime(1970, 1, 1) + timedelta(milliseconds=first)
            except OverflowError:  # a damaged time far beyond year 9999
                continue
            if first > 0:
                current.first_install = stamp
        elif not line.startswith("pkg-"):
            current = None
    return result


# --- Usage statistics -------------------------------------------------------

_USER_RE = re.compile(r"^user=(?P<user>\d+)")
_INTERVAL_RE = re.compile(r"^\s+In-memory (?P<name>\w+) stats")
_TIME_RANGE_RE = re.compile(r'^\s+timeRange="(?P<range>[^"]*)"')
_BEGIN_END_RE = re.compile(r"^\s+beginTime=(?P<begin>\d+) endTime=(?P<end>\d+)")
_USAGE_PKG_RE = re.compile(r"^\s+package=(?P<pkg>[\w.]+) totalTimeUsed=")
_KV_RE = re.compile(r'(?P<key>\w+)=(?:"(?P<quoted>[^"]*)"|(?P<plain>\S+))')
_STANDBY_RE = re.compile(
    r"^\s*package=(?P<pkg>[\w.]+) u=(?P<user>\d+) bucket=(?P<bucket>\d+) "
    r"reason=(?P<reason>\S+) used=\S+ usedByUser=(?P<by_user>\S+)",
)
# The app-standby history's own clock; AOSP AppIdleHistory.dumpUsers prints it
# after the standby rows.
_TOTAL_ELAPSED_RE = re.compile(r"^\s+totalElapsedTime=(?P<elapsed>\+\S+)")
_ISO_DATE_RE = re.compile(r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})")
_DOTTED_DATE_RE = re.compile(r"(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})")
_ENGLISH_DATE_RE = re.compile(
    r"(?P<mon>[A-Z][a-z]{2})[a-z]*\.? (?P<d>\d{1,2}), (?P<y>\d{4})"
)
_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def parse_localized_date(text: str) -> datetime | None:
    """Return the first date in a localized usagestats ``timeRange``.

    Handles ISO ``2026-06-10``, dotted ``10.6.2026`` and English
    ``Jun 10, 2026``; slash dates are ambiguous (day or month first) and
    return None.
    """
    found: list[tuple[int, datetime]] = []
    for regex in (_ISO_DATE_RE, _DOTTED_DATE_RE, _ENGLISH_DATE_RE):
        m = regex.search(text)
        if not m:
            continue
        month = (
            _MONTHS.index(m["mon"]) + 1
            if "mon" in m.groupdict() and m["mon"] in _MONTHS
            else int(m.groupdict().get("m") or 0)
        )
        try:
            found.append((m.start(), datetime(int(m["y"]), month, int(m["d"]))))
        except ValueError:
            continue
    return min(found)[1] if found else None


@dataclass
class AppUsage:
    """One package's yearly usage record."""

    age_days: float | None  # days since last use; None = no use in the window
    launches: int | None
    used_s: float | None
    fgs_s: float | None
    index: int


@dataclass
class Standby:
    """One package's app-standby state."""

    bucket: int
    reason: str
    # Device-on days since the user last used it; None = never or unknown.
    by_user_days: float | None
    index: int


@dataclass
class Usage:
    """Usage statistics of user 0: the longest (yearly) interval and standby."""

    text: Text
    apps: dict[str, AppUsage] = field(default_factory=dict)
    standby: dict[str, Standby] = field(default_factory=dict)
    window_days: float | None = None
    window_start: str | None = None
    window_index: int | None = None
    skipped: int = 0


def _usage_time(kv: dict[str, str], key: str) -> datetime | int | None:
    """Return a lastTime* value: a datetime (dump text) or epoch ms (checkin)."""
    value = kv.get(key)
    if value is None:
        return None
    if value.isdigit():
        return int(value) or None
    try:
        stamp = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return stamp if stamp.year > _EPOCH_YEAR else None


def _usage_duration_s(kv: dict[str, str], key: str) -> float | None:
    """Return a total* value: ``H:MM:SS`` or ``MM:SS`` text, or checkin ms."""
    value = kv.get(key)
    if value is None:
        return None
    if value.isdigit():
        return int(value) / 1000
    try:
        return parse_clock_s(value)
    except ValueError:
        return None


class _UsageParser:
    def __init__(self, text: Text, reference: datetime | None) -> None:
        self.usage = Usage(text)
        self.reference = reference
        self.user = 0
        self.interval = ""
        self.raw: dict[str, tuple[dict[str, str], int]] = {}
        self.begin_ms: int | None = None
        self.end_ms: int | None = None
        self.start: datetime | None = None
        self.by_user_ms: dict[str, int] = {}
        self.total_elapsed_ms: int | None = None

    def run(self) -> Usage:
        for i, line in enumerate(self.usage.text.lines):
            self._line(i, line)
        self._finish()
        return self.usage

    def _line(self, i: int, line: str) -> None:
        if m := _USER_RE.match(line):
            self.user = int(m["user"])
        elif m := _INTERVAL_RE.match(line):
            self.interval = m["name"]
        elif m := _STANDBY_RE.match(line):
            self._standby(i, m)
        elif m := _TOTAL_ELAPSED_RE.match(line):
            self._total_elapsed(m["elapsed"])
        elif self.user != 0 or self.interval != "yearly":
            return
        elif m := _TIME_RANGE_RE.match(line):
            self.start = parse_localized_date(m["range"])
            self.usage.window_start = m["range"]
            self.usage.window_index = i
        elif m := _BEGIN_END_RE.match(line):
            self.begin_ms, self.end_ms = int(m["begin"]), int(m["end"])
            self.usage.window_index = i
        elif m := _USAGE_PKG_RE.match(line):
            kv = {
                k.group("key"): k.group("quoted") or k.group("plain") or ""
                for k in _KV_RE.finditer(line)
            }
            self.raw[m["pkg"]] = (kv, i)
        elif "totalTimeUsed=" in line:
            self.usage.skipped += 1

    def _standby(self, i: int, m: re.Match[str]) -> None:
        if int(m["user"]) != 0:
            return
        ms = None
        if m["by_user"].startswith("+"):
            try:
                ms = parse_duration_ms(m["by_user"])
            except ValueError:  # cut mid-token, as in a timed-out dump
                self.usage.skipped += 1
        if ms is not None:
            self.by_user_ms[m["pkg"]] = ms
        self.usage.standby[m["pkg"]] = Standby(
            int(m["bucket"]),
            m["reason"],
            ms / _MS_PER_DAY if ms is not None else None,
            i,
        )

    def _total_elapsed(self, value: str) -> None:
        # The clock is shared by all users; the first value is enough.
        if self.total_elapsed_ms is not None:
            return
        try:
            self.total_elapsed_ms = parse_duration_ms(value)
        except ValueError:
            self.usage.skipped += 1

    def _finish(self) -> None:
        # A last use at the history's time zero (usedByUser equal to
        # totalElapsedTime) means never used: AOSP AppIdleHistory treats a
        # lastUsedByUserElapsedTime of 0 or less as unknown.
        for pkg, ms in self.by_user_ms.items():
            if ms == self.total_elapsed_ms:
                self.usage.standby[pkg].by_user_days = None
        stamps = [
            t
            for kv, _ in self.raw.values()
            for t in (_usage_time(kv, "lastTimeUsed"),)
            if isinstance(t, datetime)
        ]
        reference = self.reference or (max(stamps) if stamps else None)
        if self.begin_ms and self.end_ms:
            self.usage.window_days = (self.end_ms - self.begin_ms) / _MS_PER_DAY
            self.usage.window_start = self.usage.window_start or (
                f"{self.usage.window_days:.0f} days before capture"
            )
        elif self.start and reference:
            self.usage.window_days = (reference - self.start).total_seconds() / 86400
        for pkg, (kv, i) in self.raw.items():
            last = [
                t
                for key in ("lastTimeUsed", "lastTimeVisible")
                if (t := _usage_time(kv, key)) is not None
            ]
            age = None
            if last and isinstance(last[0], datetime) and reference:
                newest = max(t for t in last if isinstance(t, datetime))
                age = max((reference - newest).total_seconds() / 86400, 0.0)
            elif last and isinstance(last[0], int) and self.end_ms:
                newest_ms = max(t for t in last if isinstance(t, int))
                age = max((self.end_ms - newest_ms) / _MS_PER_DAY, 0.0)
            launches = kv.get("appLaunchCount")
            self.usage.apps[pkg] = AppUsage(
                age_days=age,
                launches=int(launches) if launches and launches.isdigit() else None,
                used_s=_usage_duration_s(kv, "totalTimeUsed"),
                fgs_s=_usage_duration_s(kv, "totalTimeFS"),
                index=i,
            )


def parse_usage(text: Text, reference: datetime | None) -> Usage:
    """Parse ``dumpsys usagestats`` or its ``-c`` checkin form, user 0 only.

    ``reference`` is the capture time (local wall time) used to turn the dump
    text's local timestamps into ages; checkin timestamps are epoch
    milliseconds and use the interval's own ``endTime``.
    """
    return _UsageParser(text, reference).run()


# --- Exemptions, services ---------------------------------------------------

_WHITELIST_USER_RE = re.compile(r"^\s+Whitelist user apps:$")
_WHITELIST_ITEM_RE = re.compile(r"^\s{3,}(?P<pkg>[\w.]+)$")
_WHITELIST_CMD_RE = re.compile(r"^user,(?P<pkg>[\w.]+),\d+$")


def parse_exemptions(text: Text) -> dict[str, Evidence]:
    """Return the user apps exempt from battery optimisation.

    Reads ``dumpsys deviceidle`` (``Whitelist user apps:`` block) or
    ``cmd deviceidle whitelist`` (``user,<package>,<uid>`` lines).
    """
    found: dict[str, Evidence] = {}
    in_block = False
    for i, line in enumerate(text.lines):
        if m := _WHITELIST_CMD_RE.match(line.strip()):
            found[m["pkg"]] = text.evidence(i)
        elif _WHITELIST_USER_RE.match(line):
            in_block = True
        elif in_block and (m := _WHITELIST_ITEM_RE.match(line)):
            found[m["pkg"]] = text.evidence(i, f"Whitelist user apps: {m['pkg']}")
        else:
            in_block = False
    return found


_SERVICE_RECORD_RE = re.compile(
    r"^\s+\* ServiceRecord\{\S+ u(?P<user>\d+) (?P<pkg>[\w.]+)/(?P<cls>[^\s}]+)",
)
_IS_FOREGROUND_RE = re.compile(
    r"^\s+isForeground=true foregroundId=-?\d+(?: types=(?P<types>0x[0-9a-fA-F]+))?",
)
_SERVICES_HEADER = "ACTIVITY MANAGER SERVICES"


@dataclass
class ForegroundService:
    """A service record that is in the foreground at capture."""

    package: str
    service: str
    types: list[str]
    evidence: Evidence


def parse_foreground_services(text: Text) -> list[ForegroundService]:
    """Return ``isForeground=true`` service records of user 0.

    Accepts ``dumpsys activity services`` or the full ``dumpsys activity``
    (only its ``ACTIVITY MANAGER SERVICES`` part is read).
    """
    lines = text.lines
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(_SERVICES_HEADER)),
        0,
    )
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith("ACTIVITY MANAGER ")
        ),
        len(lines),
    )
    found: list[ForegroundService] = []
    record: re.Match[str] | None = None
    for i in range(start, end):
        if m := _SERVICE_RECORD_RE.match(lines[i]):
            record = m if m["user"] == "0" else None
        elif record and (m := _IS_FOREGROUND_RE.match(lines[i])):
            mask = int(m["types"], 16) if m["types"] else 0
            excerpt = lines[i].strip().split(" foregroundNoti")[0]
            found.append(
                ForegroundService(
                    package=record["pkg"],
                    service=record["cls"],
                    types=decode_fgs_types(mask) if mask else ["none"],
                    evidence=text.evidence(i, excerpt),
                ),
            )
            record = None
    return found


# --- procstats --------------------------------------------------------------

_PS_HEADER_RE = re.compile(r"^AGGREGATED OVER LAST (?P<hours>\d+) HOURS:")
_PS_PROC_RE = re.compile(r"^  \* (?P<proc>\S+) / (?P<uid>\S+) / v\S*:$")
_PS_STATE_RE = re.compile(
    r"^\s+(?P<state>[A-Za-z(][A-Za-z ()]*?): (?P<pct>[\d.,]+)%(?: \((?P<mem>[^)]*)\))?",
)
_PS_RUN_TOTAL_RE = re.compile(r"^\s+TOTAL: \+(?P<dur>\S+)$")


@dataclass
class ProcAgg:
    """procstats summary for one app id (the busiest of its processes)."""

    alive_pct: float = 0.0  # TOTAL: share of the window in a non-cached state
    fgs_pct: float = 0.0
    rss_avg_mb: float | None = None
    pss_avg_mb: float | None = None
    processes: int = 0
    # The busiest process's largest state, e.g. "Bnd Fgs" (bound by a
    # foreground process such as the system server).
    state: str | None = None
    evidence: Evidence | None = None


@dataclass
class Procstats:
    """``dumpsys procstats --hours N`` summaries per app id."""

    apps: dict[int, ProcAgg] = field(default_factory=dict)
    hours: float | None = None
    skipped: int = 0


def _memory_avg_mb(mem: str | None) -> tuple[float | None, float | None]:
    """Return (PSS avg, RSS avg) in MB from ``a-b-c/d-e-f/g-h-i over N``.

    The triplets are PSS, USS and RSS minimum-average-maximum. Builds that
    do not sample PSS print zeros, which become None.
    """
    averages: list[float | None] = []
    for triplet in (mem or "").split(" over ")[0].split("/"):
        try:
            _, avg, _ = triplet.split("-")
            averages.append(parse_size_bytes(avg) / 1024**2 or None)
        except ValueError:
            averages.append(None)
    pss, _, rss = [*averages, None, None, None][:3]
    return pss, rss


class _ProcstatsParser:
    def __init__(self, text: Text) -> None:
        self.text = text
        self.result = Procstats()
        self.states: dict[str, float] = {}
        self.proc: tuple[int, int, str] | None = None  # app id, line, memory
        self.in_summary = False

    def run(self) -> Procstats:
        for i, line in enumerate(self.text.lines):
            if m := _PS_HEADER_RE.match(line):
                self.in_summary = True
                self.result.hours = float(m["hours"])
            elif line.startswith("Run time Stats:") and self.in_summary:
                self._close()
                self.in_summary = False
                self._run_time(i)
            elif self.in_summary:
                self._line(i, line)
        self._close()
        return self.result

    def _line(self, i: int, line: str) -> None:
        if m := _PS_PROC_RE.match(line):
            self._close()
            try:
                self.proc = (parse_uid(m["uid"]) % PER_USER_RANGE, i, "")
            except ValueError:
                self.result.skipped += 1
        elif self.proc and (m := _PS_STATE_RE.match(line)):
            try:
                self.states[m["state"]] = parse_decimal(m["pct"])
            except ValueError:  # a damaged share such as "1,2,3%"
                self.result.skipped += 1
                return
            if m["state"] == "TOTAL":
                self.proc = (self.proc[0], self.proc[1], m["mem"] or "")

    def _close(self) -> None:
        if self.proc is None:
            return
        app_id, index, mem = self.proc
        states = self.states
        self.proc, self.states = None, {}
        agg = self.result.apps.setdefault(app_id, ProcAgg())
        agg.processes += 1
        # TOTAL includes Top: a VPN or other system-bound service can sit in
        # the Top state for hours without being on screen.
        alive = states.get("TOTAL", 0.0)
        if alive >= agg.alive_pct:
            agg.alive_pct = alive
            agg.pss_avg_mb, agg.rss_avg_mb = _memory_avg_mb(mem)
            agg.evidence = self.text.evidence(index)
            shares = [(v, name) for name, v in states.items() if name != "TOTAL"]
            agg.state = max(shares)[1] if shares else None
        agg.fgs_pct = max(agg.fgs_pct, states.get("Fgs", 0.0))

    def _run_time(self, i: int) -> None:
        """Read the covered duration from ``Run time Stats: ... TOTAL: +21h4m``."""
        for later in self.text.lines[i + 1 : i + 20]:
            if m := _PS_RUN_TOTAL_RE.match(later):
                try:
                    self.result.hours = parse_duration_ms(m["dur"]) / 3_600_000
                except ValueError:  # cut mid-token; keep the header's hours
                    self.result.skipped += 1
                return


def parse_procstats(text: Text) -> Procstats:
    """Parse the per-process summary of ``dumpsys procstats --hours N``.

    Only the aggregated form is read; the default dump (committed 3-hour
    slices) is not comparable and yields an empty result. ``hours`` is the
    time the summary really covers, from its ``Run time Stats``.
    """
    return _ProcstatsParser(text).run()


# --- batterystats -----------------------------------------------------------


@dataclass
class PowerRow:
    """One UID of the power model (``Estimated power use``), on battery.

    With the power-state data of Android 15+ the total and the screen part
    are the sums of the ``on battery`` states. The process-state shares
    (``fg``, ``fgs``...) are printed only over all states, so they are scaled
    by the on-battery part of the UID's total.
    """

    uid: int
    total: float
    screen: float
    states: dict[str, float]
    index: int

    @property
    def background(self) -> float:
        """Modelled mAh outside the screen and the foreground state."""
        return max(self.total - self.screen - self.states.get("fg", 0.0), 0.0)


def _power_row(uid: UidPower) -> PowerRow:
    on_battery = uid.on_battery()
    total = sum(on_battery.values())
    # Some builds (seen on vivo) repeat one value in every state, so the
    # on-battery states add up to more than the UID's total; use the total.
    by_state = any("on battery" in label for label in uid.power_states)
    if not by_state or total > uid.total * _STATE_SUM_TOLERANCE:
        screen = uid.components.get("screen", 0.0)
        return PowerRow(uid.uid, uid.total, screen, dict(uid.states), uid.index)
    share = total / uid.total if uid.total else 0.0
    states = {name: round(mah * share, 4) for name, mah in uid.states.items()}
    screen = on_battery.get("screen", 0.0)
    return PowerRow(uid.uid, round(total, 4), screen, states, uid.index)


@dataclass
class UidStats:
    """Per-UID counters of the since-charge section (on battery)."""

    uid: int
    bt_scan_s: float = 0.0
    bt_results: int | None = None
    top_sleeping_s: float = 0.0
    fgs_s: float = 0.0
    fg_service_s: float = 0.0
    cached_s: float = 0.0
    cpu_s: float = 0.0
    screen_off_cpu_s: float = 0.0
    wakelock_total_s: float | None = None  # "TOTAL wake" (several wakelocks)
    wakelock_sum_s: float = 0.0  # sum of per-tag partial wakelock time
    wakeup_alarms: int = 0
    multicast_s: float = 0.0
    wifi_rx_packets: int = 0
    jobs: int = 0
    refs: dict[str, int] = field(default_factory=dict)  # field kind -> line

    @property
    def wakelock_s(self) -> float:
        """Partial wakelock time blamed on this UID."""
        if self.wakelock_total_s is not None:
            return self.wakelock_total_s
        return self.wakelock_sum_s


_UID_FIELDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^\s+Bluetooth Scan \(total actual realtime\): "
            r"(?P<dur>.+?)\s+\(\d+ times\)",
        ),
        "bt_scan",
    ),
    (re.compile(r"^\s+Bluetooth Scan Results: (?P<n>\d+)"), "bt_results"),
    (re.compile(r"^\s+Top Sleeping for: (?P<dur>.+?)\s*$"), "top_sleeping"),
    (re.compile(r"^\s+Foreground services: (?P<dur>.+?) realtime"), "fgs"),
    (re.compile(r"^\s+Fg Service for: (?P<dur>.+?)\s*$"), "fg_service"),
    (re.compile(r"^\s+Cached for: (?P<dur>.+?)\s*$"), "cached"),
    (re.compile(r"^\s+Total cpu time: u=(?P<u>.+?) s=(?P<s>.+?)\s*$"), "cpu"),
    (
        re.compile(r"^\s+Total screen-off cpu time per freq: (?P<vals>[\d ]+)$"),
        "so_cpu",
    ),
    (re.compile(r"^\s+TOTAL wake: (?P<dur>.+?) blamed partial"), "total_wake"),
    (
        re.compile(
            r"^\s+Wake lock .*?(?:: |, )"
            r"(?P<dur>(?:\d+(?:ms|[dhms]) ?)+) partial \(\d+ times\)",
        ),
        "wakelock",
    ),
    (re.compile(r"^\s+Wakeup alarm .+: (?P<n>\d+) times$"), "alarm"),
    (
        re.compile(r"^\s+WiFi Multicast Wakelock count = \d+ time = (?P<dur>.+?)\s*$"),
        "multicast",
    ),
    (re.compile(r"^\s+Wi-Fi network: .*\(packets (?P<n>\d+) received"), "wifi_rx"),
    (re.compile(r"^\s+Job .+?: .+? realtime \((?P<n>\d+) times\)"), "job"),
)


_DURATION_FIELDS = {
    "bt_scan": "bt_scan_s",
    "top_sleeping": "top_sleeping_s",
    "fgs": "fgs_s",
    "fg_service": "fg_service_s",
    "cached": "cached_s",
    "multicast": "multicast_s",
    "total_wake": "wakelock_total_s",
}
_COUNT_FIELDS = {"alarm": "wakeup_alarms", "job": "jobs"}
_VALUE_FIELDS = {"bt_results": "bt_results", "wifi_rx": "wifi_rx_packets"}


def _apply_uid_field(stats: UidStats, kind: str, m: re.Match[str]) -> None:
    """Store one matched per-UID counter; durations become seconds.

    Raises ValueError for a duration cut mid-token.
    """
    if kind in _DURATION_FIELDS:
        setattr(stats, _DURATION_FIELDS[kind], parse_duration_ms(m["dur"]) / 1000)
    elif kind in _COUNT_FIELDS:
        attr = _COUNT_FIELDS[kind]
        setattr(stats, attr, getattr(stats, attr) + int(m["n"]))
    elif kind in _VALUE_FIELDS:
        setattr(stats, _VALUE_FIELDS[kind], int(m["n"]))
    elif kind == "cpu":
        stats.cpu_s = (parse_duration_ms(m["u"]) + parse_duration_ms(m["s"])) / 1000
    elif kind == "so_cpu":
        stats.screen_off_cpu_s = sum(int(v) for v in m["vals"].split()) / 1000
    elif kind == "wakelock":
        stats.wakelock_sum_s += parse_duration_ms(m["dur"]) / 1000


def _parse_uid_line(stats: UidStats, line: str, index: int) -> None:
    for regex, kind in _UID_FIELDS:
        if m := regex.match(line):
            _apply_uid_field(stats, kind, m)
            stats.refs.setdefault(kind, index)
            return


@dataclass
class BatteryUse:
    """The per-UID power model and counters of the since-charge block."""

    since_charge: SinceCharge
    power: dict[int, PowerRow]
    uids: dict[int, UidStats]
    skipped: int = 0  # per-UID counter lines that could not be read

    @property
    def text(self) -> Text:
        """The batterystats text that the line indexes refer to."""
        return self.since_charge.text

    def measured_drain(self) -> tuple[float | None, int | None]:
        """Return the measured discharge and its line.

        The counter-based ``Discharge`` line comes first, then the low end of
        ``actual drain``. ``Computed drain`` is the model's total on some
        builds, so it is only the last resort.
        """
        discharge = self.since_charge.mah("Discharge")
        found = self.since_charge.header("Discharge")
        if discharge and found:
            return discharge, found[1]
        model = self.since_charge.power
        if model is None:
            return None, None
        return model.actual_drain_min or model.computed_drain, model.capacity_index

    def drain_range(self) -> tuple[float, float] | None:
        """Return the level-based ``actual drain`` range, when it is a range."""
        model = self.since_charge.power
        low = model.actual_drain_min if model else None
        high = model.actual_drain_max if model else None
        if low is None or high is None or low == high:
            return None
        return low, high


def parse_battery_use(since_charge: SinceCharge) -> BatteryUse | None:
    """Return the per-UID view of a since-charge block, or None if it has none.

    A per-UID line that cannot be read (a dump cut mid-token by a timeout)
    is counted in ``skipped``.
    """
    model = since_charge.power
    power = {uid: _power_row(row) for uid, row in model.uids.items()} if model else {}
    uids: dict[int, UidStats] = {}
    skipped = 0
    for uid, lines in since_charge.uid_blocks.items():
        stats = uids[uid] = UidStats(uid)
        for index, line in lines:
            try:
                _parse_uid_line(stats, line, index)
            except ValueError:
                skipped += 1
    if not power and not uids:
        return None
    return BatteryUse(since_charge, power, uids, skipped)


_CHECKIN_ROW_RE = re.compile(r"^\d+,(?P<uid>-?\d+),(?P<kind>[a-z]+),")


def checkin_uids(text: Text) -> set[int]:
    """Return the UIDs with since-charge (``l``) rows in a batterystats checkin.

    Works for ``dumpsys batterystats -c`` and the bugreport's CHECKIN
    BATTERYSTATS section. Its ``i,uid`` package rows are already in the
    context's package map.
    """
    return {int(m["uid"]) for _, m in text.find(_CHECKIN_ROW_RE) if m["kind"] == "l"}


# --- Alarms -----------------------------------------------------

_ALARM_STATS_RE = re.compile(
    r"^  (?P<uid>u\d+[ais]\d+|-?\d+):(?P<pkg>[\w.]+) "
    r"\+\S+ running, (?P<wakeups>\d+) wakeups:",
)
_RESTRICTED_HEADER_RE = re.compile(r"^(?P<indent>\s+)Restricted packages:$")
_RESTRICTED_ITEM_RE = re.compile(r"^\s+(?:u\d+[ais]\d+|\d+) (?P<pkg>[\w.]+)$")


@dataclass
class Alarms:
    """Wakeup alarms per package since boot, and background-restricted apps."""

    wakeups: dict[str, tuple[int, Evidence]] = field(default_factory=dict)
    uids: set[int] = field(default_factory=set)
    restricted: dict[str, Evidence] = field(default_factory=dict)
    restricted_listed: bool = False


def parse_alarms(text: Text) -> Alarms:
    """Parse ``dumpsys alarm``: ``Alarm Stats`` headers and restricted packages."""
    result = Alarms()
    restricted_indent: int | None = None
    for i, line in enumerate(text.lines):
        if m := _ALARM_STATS_RE.match(line):
            result.wakeups[m["pkg"]] = (int(m["wakeups"]), text.evidence(i))
            result.uids.add(parse_uid(m["uid"]))
        elif m := _RESTRICTED_HEADER_RE.match(line):
            restricted_indent = len(m["indent"])
            result.restricted_listed = True
        elif restricted_indent is not None:
            indent = len(line) - len(line.lstrip())
            if indent <= restricted_indent:
                restricted_indent = None
            elif m := _RESTRICTED_ITEM_RE.match(line):
                result.restricted[m["pkg"]] = text.evidence(i)
    return result


_HOME_COMPONENT_RE = re.compile(r"^(?P<comp>[\w.]+/[\w.$]+)$")


# --- Shared inputs ----------------------------------------------------------


class _Inputs:
    """Lazily parsed sources, shared by the analyzers of one call."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.notes: list[str] = []

    @cached_property
    def package_dump(self) -> PackageDump | None:
        text = self.ctx.sources.get("package")
        return parse_package_dump(text) if text else None

    @cached_property
    def package_states(self) -> dict[str, PackageState]:
        if self.package_dump:
            return self.package_dump.packages
        text = self.ctx.sources.get("package_checkin")
        return parse_package_checkin(text) if text else {}

    @cached_property
    def third_party(self) -> ThirdParty | None:
        if text := self.ctx.sources.get("packages_3p"):
            parsed = parse_pm_list(text)
            if parsed.app_ids:
                return parsed
        # Without the list, the context's third-party app ids (packages that
        # dumpsys package does not flag as SYSTEM) name the packages.
        dump = self.package_dump
        if dump is None:
            return None
        known = self.ctx.packages.third_party
        app_ids = {
            pkg: state.app_id
            for pkg, state in dump.packages.items()
            if state.app_id in known
        }
        evidence = {
            pkg: dump.text.evidence(dump.packages[pkg].index) for pkg in app_ids
        }
        return ThirdParty(app_ids, evidence, dump.text.origin)

    @cached_property
    def usage(self) -> Usage | None:
        reference = self.ctx.windows.dump_time
        usage = None
        if text := self.ctx.sources.get("usagestats"):
            usage = parse_usage(text, reference)
        checkin = self.ctx.sources.get("usagestats_checkin")
        if checkin and (usage is None or not usage.apps or usage.window_days is None):
            fallback = parse_usage(checkin, reference)
            if usage is None or not usage.apps:
                usage = fallback
            else:
                usage.window_days = fallback.window_days
        return usage

    @cached_property
    def settings(self) -> Settings | None:
        return load_settings(self.ctx)

    @cached_property
    def exemptions(self) -> dict[str, Evidence]:
        found: dict[str, Evidence] = {}
        for key in ("deviceidle_whitelist", "deviceidle"):
            if text := self.ctx.sources.get(key):
                found = parse_exemptions(text) | found
        return found

    @cached_property
    def foreground_services(self) -> list[ForegroundService]:
        text = self.ctx.sources.get("activity_services") or self.ctx.sources.get(
            "activity",
        )
        return parse_foreground_services(text) if text else []

    @cached_property
    def procstats(self) -> Procstats:
        text = self.ctx.sources.get("procstats")
        parsed = parse_procstats(text) if text else Procstats()
        if text and not parsed.apps:
            self.notes.append(
                "procstats has no 'AGGREGATED OVER LAST N HOURS' summary "
                "(collect 'dumpsys procstats --hours 24'); run-time shares unknown.",
            )
        return parsed

    @cached_property
    def battery(self) -> BatteryUse | None:
        def build() -> BatteryUse | None:
            since_charge = load_since_charge(self.ctx)
            return parse_battery_use(since_charge) if since_charge else None

        return self.ctx.sources.memo("apps.battery_use", build)

    @cached_property
    def alarms(self) -> Alarms | None:
        text = self.ctx.sources.get("alarm")
        return parse_alarms(text) if text else None

    @cached_property
    def home(self) -> tuple[str, Evidence] | None:
        if text := self.ctx.sources.get("home_activity"):
            for i, line in enumerate(text.lines):
                if m := _HOME_COMPONENT_RE.match(line.strip()):
                    return _component_package(m["comp"]), text.evidence(i)
        dump = self.package_dump
        if dump and dump.home and dump.home_index is not None:
            return _component_package(dump.home), dump.text.evidence(dump.home_index)
        return None


# --- uid_package_map ----------------------------------------------------------

_NETSTATS_UID_RE = re.compile(r"\buid=(?P<uid>-?\d+)\b")


def _uid_kind(uid: int, packages: PackageMap) -> str:
    app_id = uid % PER_USER_RANGE if uid >= 0 else uid
    names = packages.packages(uid) if uid >= 0 else []
    if uid < 0:
        return "pseudo"
    if FIRST_ISOLATED_UID <= app_id < PER_USER_RANGE:
        return "isolated"
    if len(names) > 1:
        return "shared"
    if names or app_id in SYSTEM_UIDS:
        return "mapped"
    return "unmapped" if app_id >= FIRST_APPLICATION_UID else "system-unnamed"


def _seen_uids(inputs: _Inputs, checkin_seen: set[int]) -> dict[int, set[str]]:
    seen: dict[int, set[str]] = {}
    use = inputs.battery
    if use:
        model = use.since_charge.power
        for uid in model.uids if model else {}:
            seen.setdefault(uid, set()).add("power model")
        for uid in use.uids:
            seen.setdefault(uid, set()).add("batterystats")
    for uid in checkin_seen:
        seen.setdefault(uid, set()).add("checkin")
    if inputs.alarms:
        for uid in inputs.alarms.uids:
            seen.setdefault(uid, set()).add("alarm")
    if text := inputs.ctx.sources.get("netstats"):
        for _, m in text.find(_NETSTATS_UID_RE):
            uid = int(m["uid"])
            if uid < 0:
                seen.setdefault(uid, set()).add("netstats")
    return seen


def _uid_rows(
    seen: dict[int, set[str]],
    packages: PackageMap,
    power: dict[int, UidPower],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Classify each seen UID; return the unnamed/shared/pseudo tables and counts."""
    rows: dict[str, list[dict[str, Any]]] = {"unnamed": [], "shared": [], "pseudo": []}
    counts: dict[str, int] = {}
    for uid in sorted(seen):
        kind = _uid_kind(uid, packages)
        counts[kind] = counts.get(kind, 0) + 1
        row = {
            "uid": uid,
            "label": format_uid(uid) if uid >= 0 else str(uid),
            "kind": kind,
            "seen_in": ", ".join(sorted(seen[uid])),
            "model_mah": power[uid].total if uid in power else None,
        }
        if kind in {"unmapped", "system-unnamed"}:
            rows["unnamed"].append(row)
        elif kind == "shared":
            names = packages.packages(uid)
            rows["shared"].append(
                row | {"packages": len(names), "names": ", ".join(names[:5])},
            )
        elif kind == "pseudo":
            rows["pseudo"].append(row)
    return rows, counts


@analyzer("uid_package_map")
def uid_package_map(ctx: Context) -> Result:
    """Report how well UIDs seen in batterystats map to installed packages."""
    inputs = _Inputs(ctx)
    checkin = ctx.sources.get("batterystats_checkin")
    if inputs.battery is None and checkin is None:
        msg = "no batterystats or batterystats checkin dump"
        raise SkipError(msg)
    packages = ctx.packages
    seen = _seen_uids(inputs, checkin_uids(checkin) if checkin else set())
    # The power model over the whole since-charge period, charger included.
    model = inputs.battery.since_charge.power if inputs.battery else None
    power = model.uids if model else {}
    rows, counts = _uid_rows(seen, packages, power)
    app_seen = [
        u
        for u in seen
        if u >= 0 and FIRST_APPLICATION_UID <= u % PER_USER_RANGE < FIRST_ISOLATED_UID
    ]
    app_mapped = sum(1 for u in app_seen if packages.packages(u))
    unmapped = [r for r in rows["unnamed"] if r["kind"] == "unmapped"]
    unmapped_mah = sum(r["model_mah"] or 0.0 for r in unmapped)
    result = Result(
        "uid_package_map",
        window="since_charge",
        metrics={
            "uids_seen": len(seen),
            "app_uids_seen": len(app_seen),
            "app_uids_mapped": app_mapped,
            "app_uid_coverage_pct": pct(app_mapped, len(app_seen)),
            "unmapped_app_uids": len(unmapped),
            "unmapped_app_model_mah": round(unmapped_mah, 3),
            "unnamed_system_uids": counts.get("system-unnamed", 0),
            "shared_uids": counts.get("shared", 0),
            "isolated_uids": counts.get("isolated", 0),
            "pseudo_uids": counts.get("pseudo", 0),
            "app_ids_known": len(packages.by_app_id),
        },
    )
    for name, table in rows.items():
        table.sort(key=lambda r: (-(r["model_mah"] or 0.0), r["uid"]))
        result.add_table(name, table)
    if not packages.by_app_id:
        result.notes.append(
            "No package list (cmd package list packages -U or dumpsys package): "
            "names come only from the batterystats checkin, if present.",
        )
    if counts.get("shared"):
        result.notes.append(
            "Shared UIDs run several packages (table 'shared'); report their "
            "numbers as system/shared, not as the first package's.",
        )
    if counts.get("isolated"):
        result.notes.append(
            "Isolated UIDs (u0iN) belong to sandboxed processes such as WebView "
            "renderers; their host app is not recorded here.",
        )
    if unmapped_mah >= UNMAPPED_MAH_FLAG and inputs.battery:
        result.findings.append(
            _unmapped_finding(unmapped, unmapped_mah, power, inputs.battery.text),
        )
    return result


def _unmapped_finding(
    rows: list[dict[str, Any]],
    unmapped_mah: float,
    power: dict[int, UidPower],
    text: Text,
) -> Finding:
    top = [r for r in rows if r["model_mah"]][:5]
    return Finding(
        id="uid_package_map.unmapped-power",
        title="Modelled power on UIDs without a known package",
        symptom="battery",
        severity="low",
        basis="modelled",
        window="since_charge",
        summary=(
            f"{unmapped_mah:.1f} mAh of the power model sits on {len(rows)} app "
            "UIDs that no package list explains (apps uninstalled since the last "
            "charge, or a package list that was not collected)."
        ),
        metrics={
            "unmapped_app_model_mah": round(unmapped_mah, 2),
            "uids": ", ".join(r["label"] for r in top),
        },
        evidence=[
            text.evidence(power[r["uid"]].index) for r in top if r["uid"] in power
        ],
        recommendation=(
            "Collect 'cmd package list packages -U' together with batterystats so "
            "every UID can be named; an app removed since the last charge keeps "
            "its UID in batterystats until the next full charge."
        ),
        followups=[
            "Check the package manager's 'Package Changes' history for removals."
        ],
    )


# --- app_background_activity ----------------------------------------------------


def _drain_split(third_party: frozenset[int], use: BatteryUse) -> dict[str, Any]:
    """Split the modelled mAh by UID class; shares are of the measured drain.

    When the per-UID model adds up to more than the measured drain (a coarse
    counter, or a model that overestimates), shares are of the model total
    and nothing is left unbilled.
    """
    groups: dict[str, dict[str, float]] = {}
    for row in use.power.values():
        group = groups.setdefault(
            uid_class(row.uid, third_party),
            {"total": 0.0, "screen": 0.0, "fg": 0.0},
        )
        group["total"] += row.total
        group["screen"] += row.screen
        group["fg"] += row.states.get("fg", 0.0)
    drain, _ = use.measured_drain()
    model = use.since_charge.power
    model_sum = round(sum(r.total for r in use.power.values()), 2)
    metrics: dict[str, Any] = {
        "model_capacity_mah": model.capacity if model else None,
        "computed_drain_mah": model.computed_drain if model else None,
        "measured_drain_mah": drain,
        "model_uid_sum_mah": model_sum,
        "model_uids": len(use.power),
    }
    for name, group in sorted(groups.items()):
        nonscreen = group["total"] - group["screen"]
        metrics[f"{name}_mah"] = round(group["total"], 2)
        metrics[f"{name}_screen_mah"] = round(group["screen"], 2)
        metrics[f"{name}_nonscreen_mah"] = round(nonscreen, 2)
        metrics[f"{name}_background_mah"] = round(max(nonscreen - group["fg"], 0.0), 2)
    if not drain:
        return metrics
    exceeds = model_sum > drain
    metrics["share_basis"] = "model" if exceeds else "measured_drain"
    metrics["unbilled_mah"] = 0.0 if exceeds else round(drain - model_sum, 1)
    metrics["unbilled_share_pct"] = pct(metrics["unbilled_mah"], drain)
    if exceeds:
        metrics["model_excess_mah"] = round(model_sum - drain, 1)
    for name in groups:
        metrics[f"{name}_nonscreen_share_pct"] = pct(
            metrics[f"{name}_nonscreen_mah"],
            model_sum if exceeds else drain,
        )
    return metrics


def _background_rows(ctx: Context, use: BatteryUse) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for uid in sorted(set(use.power) | set(use.uids)):
        if uid % PER_USER_RANGE < FIRST_APPLICATION_UID:
            continue
        power = use.power.get(uid)
        counters = use.uids.get(uid) or UidStats(uid)
        rows.append(
            {
                "uid": format_uid(uid),
                "name": ctx.packages.name(uid),
                "class": uid_class(uid, ctx.packages.third_party),
                "model_total_mah": power.total if power else None,
                "model_screen_mah": power.screen if power else None,
                "model_background_mah": _round(power.background, 3) if power else None,
                "model_fgs_mah": power.states.get("fgs") if power else None,
                "model_cached_mah": power.states.get("cached") if power else None,
                "cpu_s": round(counters.cpu_s, 1),
                "screen_off_cpu_s": round(counters.screen_off_cpu_s, 1),
                "fgs_s": round(counters.fgs_s),
                "fg_service_state_s": round(counters.fg_service_s),
                "top_sleeping_s": round(counters.top_sleeping_s),
                "cached_s": round(counters.cached_s),
                "partial_wakelock_s": round(counters.wakelock_s, 1),
                "wakeup_alarms": counters.wakeup_alarms,
                "bt_scan_s": round(counters.bt_scan_s),
                "bt_results": counters.bt_results,
                "wifi_multicast_lock_s": round(counters.multicast_s),
                "wifi_rx_packets": counters.wifi_rx_packets,
                "jobs": counters.jobs,
            },
        )
    rows.sort(
        key=lambda r: (
            -(r["model_background_mah"] or 0.0),
            -r["screen_off_cpu_s"],
            r["uid"],
        ),
    )
    return rows


def _share_finding(metrics: dict[str, Any], use: BatteryUse) -> Finding | None:
    drain, drain_index = use.measured_drain()
    share = metrics.get("third_party_nonscreen_share_pct")
    if not drain or share is None:
        return None
    # Shares of a model that exceeds the measured drain do not say how much
    # of the real drain apps caused, so they never raise the severity.
    of_model = metrics.get("share_basis") == "model"
    whole = "modelled drain" if of_model else "drain"
    if share >= APP_SHARE_MAJOR_PCT:
        severity = "low" if of_model else "medium"
        title = f"Third-party apps' background use is a main share of the {whole}"
    elif share < APP_SHARE_MINOR_PCT:
        severity = "info"
        title = f"Third-party apps' background use is a small share of the {whole}"
    else:
        return None
    core = metrics.get("core_mah", 0.0)
    if of_model:
        measured = f"{drain:g} mAh measured drain"
        if span := use.drain_range():
            measured += f" (level-based estimate {span[0]:g}-{span[1]:g} mAh)"
        basis = (
            f"{share}% of the {metrics['model_uid_sum_mah']:g} mAh the model bills "
            f"to all UIDs; the model exceeds the {measured} by "
            f"{metrics['model_excess_mah']:g} mAh, so shares are of the model"
        )
        rest = f"core UIDs below 10000 get {core} mAh."
    else:
        basis = f"{share}% of the {drain:g} mAh measured drain"
        rest = (
            f"core UIDs below 10000 get {core} mAh and "
            f"{metrics.get('unbilled_mah', 0.0)} mAh is billed to no UID."
        )
    evidence = [use.text.evidence(drain_index)] if drain_index is not None else []
    return Finding(
        id="app_background_activity.third-party-share",
        title=title,
        symptom="battery",
        severity=severity,
        basis="modelled",
        window="on_battery",
        summary=(
            "The power model bills third-party apps "
            f"{metrics.get('third_party_nonscreen_mah')} mAh outside the screen "
            f"({basis}); {rest} Kernel and radio wakeups are not billed to the app "
            "that triggered them, so app numbers are a floor."
        ),
        metrics={
            k: metrics.get(k)
            for k in (
                "measured_drain_mah",
                "model_uid_sum_mah",
                "share_basis",
                "third_party_nonscreen_mah",
                "third_party_background_mah",
                "preinstalled_app_nonscreen_mah",
                "core_mah",
                "unbilled_mah",
                "model_excess_mah",
            )
        },
        evidence=evidence,
        recommendation=(
            "Restrict the apps with the largest background energy first "
            "(Settings > Apps > (app) > App battery usage > Restricted)."
            if severity == "medium"
            else "Treat app restrictions as trimming triggers, not as the main fix, "
            "when the app share is small or uncertain; look at kernel wakeups, "
            "radio and system UIDs first."
        ),
        followups=[
            "Compare with the measured screen-off drain rate and kernel wakeup counts.",
            "A screen-off test with the suspect apps restricted shows the real effect.",
        ],
    )


def _top_sleeping_finding(use: BatteryUse, packages: PackageMap) -> Finding | None:
    flagged = sorted(
        (c for c in use.uids.values() if c.top_sleeping_s >= TOP_SLEEPING_FLAG_S),
        key=lambda c: -c.top_sleeping_s,
    )
    if not flagged:
        return None
    listing = ", ".join(
        f"{packages.name(c.uid)} {c.top_sleeping_s / 3600:.1f} h" for c in flagged[:5]
    )
    return Finding(
        id="app_background_activity.top-sleeping",
        title="Apps stayed on top while the screen was off",
        symptom="battery",
        severity="low",
        basis="measured",
        window="on_battery",
        summary=(
            f"{len(flagged)} app(s) were the top activity with the screen off for "
            f"at least {TOP_SLEEPING_FLAG_S // 60} min: {listing}. Their processes "
            "kept foreground priority while the phone slept."
        ),
        metrics={
            "apps": len(flagged),
            "max_top_sleeping_h": round(flagged[0].top_sleeping_s / 3600, 2),
        },
        evidence=[use.text.evidence(c.refs["top_sleeping"]) for c in flagged[:5]],
        recommendation=(
            "Go to the home screen before locking the phone, or close the app from "
            "Recents, so it can drop to the background and be frozen."
        ),
        followups=[
            "Compare each app's screen-off CPU: a top app that idles costs little.",
        ],
    )


@analyzer("app_background_activity")
def app_background_activity(ctx: Context) -> Result:
    """Split the modelled drain by app class and list per-app background use."""
    use = _Inputs(ctx).battery
    if use is None:
        msg = "no batterystats dump with a since-charge section"
        raise SkipError(msg)
    result = Result("app_background_activity", window="on_battery")
    if use.power:
        result.metrics.update(_drain_split(ctx.packages.third_party, use))
    else:
        result.notes.append("No 'Estimated power use' block: no modelled split.")
    seconds = ctx.windows.on_battery_s
    result.metrics["on_battery_h"] = _round(seconds / 3600 if seconds else None)
    if not ctx.packages.third_party:
        result.notes.append(
            "No third-party package list: app UIDs are not split into third-party "
            "and preinstalled apps.",
        )
    result.add_table("apps", _background_rows(ctx, use))
    if use.skipped:
        result.notes.append(
            f"{use.skipped} per-UID batterystats lines could not be read "
            "(cut off mid-value?).",
        )
    if result.metrics.get("share_basis") == "model":
        result.notes.append(
            "The per-UID power model adds up to more than the measured drain, so "
            "class shares are of the model total and nothing is unbilled.",
        )
    result.notes.append(
        "Modelled mAh come from the power profile; kernel and radio wakeups are "
        "billed to no app, and WorkSource blaming can bill one piece of work to "
        "several UIDs. Do not add per-app numbers across apps or with other causes.",
    )
    result.notes.append(
        "preinstalled_app covers every app UID outside the third-party list: "
        "preinstalled apps and apps removed since the last charge.",
    )
    if share := _share_finding(result.metrics, use):
        result.findings.append(share)
    if top := _top_sleeping_finding(use, ctx.packages):
        result.findings.append(top)
    return result


# --- third_party_apps ---------------------------------------------------------


@dataclass
class AppFacts:
    """Everything known about one third-party app."""

    package: str
    app_id: int
    days_since_use: float | None = None
    use_lower_bound: bool = False
    since_install: bool = False  # no use since install: days_since_use is its age
    launches: int | None = None
    used_h: float | None = None
    fgs_h: float | None = None
    bucket: str | None = None
    installed_days: float | None = None
    never_launched: bool | None = None
    exempt: bool = False
    restricted: bool = False
    listener: bool = False
    accessibility: bool = False
    keyboard: str | None = None
    role: str | None = None  # in use through a system role (Home, keyboard, TTS)
    fgs_types: list[str] = field(default_factory=list)
    procstats_alive_pct: float | None = None
    procstats_fgs_pct: float | None = None
    procstats_state: str | None = None
    rss_avg_mb: float | None = None
    pss_avg_mb: float | None = None
    model_total_mah: float | None = None
    model_background_mah: float | None = None
    screen_off_cpu_s: float | None = None
    bt_scan_s: float | None = None
    bt_results: int | None = None
    wakeup_alarms: int | None = None
    alarm_wakeups_since_boot: int | None = None
    evidence: dict[str, Evidence] = field(default_factory=dict)

    @property
    def dormant(self) -> bool | None:
        """True when not used for DORMANT_DAYS and installed for longer."""
        if self.role:
            return False
        if self.days_since_use is None:
            return None
        if self.installed_days is not None and self.installed_days < DORMANT_DAYS:
            return False
        return self.days_since_use >= DORMANT_DAYS

    @property
    def persistent_fgs(self) -> bool:
        """A foreground service now, or the Fgs state for nearly all of the window."""
        return bool(self.fgs_types) or (self.procstats_fgs_pct or 0.0) >= PERSISTENT_PCT

    @property
    def alive(self) -> bool:
        """The process stayed alive for BACKGROUND_PCT of the procstats window."""
        return (self.procstats_alive_pct or 0.0) >= BACKGROUND_PCT

    @property
    def system_bound(self) -> bool:
        """The system keeps the process bound as a listener or accessibility service.

        The procstats state ``Bnd Fgs`` or ``Bnd Top`` means a foreground
        process (here the system server) holds a binding to it; such an app
        runs because of a privilege, not because of work it started.
        """
        bound = (self.procstats_state or "").startswith("Bnd ")
        return bound and (self.listener or self.accessibility)

    def presence_signals(self) -> list[str]:
        """Describe how the app stays running without the user."""
        signals = []
        if self.fgs_types:
            signals.append(f"foreground service running ({', '.join(self.fgs_types)})")
        if self.alive:
            signals.append(
                f"process alive {self.procstats_alive_pct:.0f}% of the "
                "procstats window"
                + (", kept bound by the system" if self.system_bound else ""),
            )
        return signals

    def energy_signals(self, windows: Windows) -> list[str]:
        """Describe the measured background work on battery."""
        signals = []
        scan_s = self.bt_scan_s or 0.0
        if scan_s >= BLE_SCAN_FLAG_S:
            signals.append(
                f"Bluetooth LE scan {scan_s / 3600:.1f} h on battery "
                f"with {self.bt_results or 0} results",
            )
        rate = per_hour(self.model_background_mah, windows.on_battery_s, 6)
        if rate is not None and rate >= ACTIVE_BG_MAH_PER_H:
            signals.append(f"{rate:.2f} mAh/h modelled background energy")
        cpu_rate = per_hour(self.screen_off_cpu_s, windows.screen_off_on_battery_s, 6)
        if cpu_rate is not None and cpu_rate >= ACTIVE_SCREEN_OFF_CPU_S_PER_H:
            signals.append(f"{cpu_rate:.0f} s/h screen-off CPU")
        alarm_rate = per_hour(self.wakeup_alarms, windows.on_battery_s, 6)
        if alarm_rate is not None and alarm_rate > WAKEUP_ALARMS_PER_H:
            signals.append(f"{alarm_rate:.1f} wakeup alarms per hour")
        return signals

    def background_signals(self, windows: Windows) -> list[str]:
        """Describe every measured sign that the app runs without the user."""
        return self.presence_signals() + self.energy_signals(windows)

    def runs_on_its_own(self, windows: Windows) -> bool:
        """Tell whether the app works in the background beyond a system binding."""
        return bool(
            self.fgs_types
            or (self.alive and not self.system_bound)
            or self.energy_signals(windows),
        )

    def privileges(self) -> list[str]:
        """List the standing permissions that let the app run or stay bound."""
        names = []
        if self.exempt:
            names.append("exempt from battery optimisation")
        if self.listener:
            names.append("notification listener")
        if self.accessibility:
            names.append("accessibility service")
        if self.keyboard == "default":
            names.append("default keyboard")
        return names

    def row(self) -> dict[str, Any]:
        """Return the table row for this app."""
        return {
            "package": self.package,
            "uid": format_uid(self.app_id),
            "dormant": self.dormant,
            "days_since_use": _round(self.days_since_use, 1),
            "days_since_use_is_lower_bound": self.use_lower_bound,
            "launches_in_usage_window": self.launches,
            "used_h_in_usage_window": _round(self.used_h),
            "fgs_h_in_usage_window": _round(self.fgs_h),
            "standby_bucket": self.bucket,
            "installed_days": _round(self.installed_days, 1),
            "never_launched": self.never_launched,
            "exempt": self.exempt,
            "background_restricted": self.restricted,
            "notification_listener": self.listener,
            "accessibility_service": self.accessibility,
            "keyboard": self.keyboard,
            "role": self.role,
            "fgs_types_now": ", ".join(self.fgs_types) or None,
            "procstats_alive_pct": _round(self.procstats_alive_pct, 1),
            "procstats_fgs_pct": _round(self.procstats_fgs_pct, 1),
            "procstats_state": self.procstats_state,
            "rss_avg_mb": _round(self.rss_avg_mb, 1),
            "pss_avg_mb": _round(self.pss_avg_mb, 1),
            "model_total_mah": self.model_total_mah,
            "model_background_mah": _round(self.model_background_mah, 3),
            "screen_off_cpu_s": _round(self.screen_off_cpu_s, 1),
            "bt_scan_s": _round(self.bt_scan_s, 0),
            "bt_results": self.bt_results,
            "wakeup_alarms_on_battery": self.wakeup_alarms,
            "alarm_wakeups_since_boot": self.alarm_wakeups_since_boot,
        }


def _apply_usage(facts: AppFacts, usage: Usage | None) -> None:
    """Set the last use; ``facts.installed_days`` must already be known."""
    if usage is None:
        return
    record = usage.apps.get(facts.package)
    standby = usage.standby.get(facts.package)
    if standby:
        facts.bucket = STANDBY_BUCKETS.get(standby.bucket, str(standby.bucket))
    if record and record.age_days is not None:
        facts.days_since_use = record.age_days
        facts.evidence["usage"] = usage.text.evidence(record.index)
    else:
        # No use inside the usage window: the window length is a lower bound,
        # and the standby history may know an older last use. Neither can be
        # older than the install.
        candidates = [usage.window_days] if usage.window_days else []
        if standby and standby.by_user_days is not None:
            candidates.append(standby.by_user_days)
        if candidates:
            facts.days_since_use = max(candidates)
            facts.use_lower_bound = True
            installed = facts.installed_days
            if installed is not None and facts.days_since_use >= installed:
                facts.days_since_use = installed
                facts.since_install = True
        if record:
            facts.evidence["usage"] = usage.text.evidence(record.index)
        elif usage.window_index is not None:
            facts.evidence["usage"] = usage.text.evidence(
                usage.window_index,
                f"no usage record for {facts.package} in "
                + usage.text.lines[usage.window_index].strip(),
            )
        if standby and standby.by_user_days is not None:
            facts.evidence["standby"] = usage.text.evidence(standby.index)
    if record:
        facts.launches = record.launches
        facts.used_h = record.used_s / 3600 if record.used_s is not None else None
        facts.fgs_h = record.fgs_s / 3600 if record.fgs_s is not None else None


def _apply_roles(facts: AppFacts, inputs: _Inputs) -> None:
    pkg = facts.package
    settings = inputs.settings
    if pkg in inputs.exemptions:
        facts.exempt = True
        facts.evidence["exempt"] = inputs.exemptions[pkg]
    if inputs.alarms and pkg in inputs.alarms.restricted:
        facts.restricted = True
    for key, attr in (
        ("enabled_notification_listeners", "listener"),
        ("enabled_accessibility_services", "accessibility"),
    ):
        components = setting_components(settings, key)
        if settings and pkg in {_component_package(c) for c in components}:
            setattr(facts, attr, True)
            facts.evidence[attr] = settings.evidence(key)[0]
    _apply_system_roles(facts, inputs)
    services = [s for s in inputs.foreground_services if s.package == pkg]
    for service in services:
        facts.fgs_types.extend(t for t in service.types if t not in facts.fgs_types)
    if services:
        facts.evidence["fgs"] = services[0].evidence


def _apply_system_roles(facts: AppFacts, inputs: _Inputs) -> None:
    """Mark the default keyboard, text-to-speech engine and Home app."""
    pkg = facts.package
    settings = inputs.settings
    default_ime = settings.value("default_input_method") if settings else None
    if pkg == _component_package(default_ime or ""):
        facts.keyboard = "default"
        facts.role = "default keyboard"
    elif pkg in {
        _component_package(c)
        for c in setting_components(settings, "enabled_input_methods")
    }:
        facts.keyboard = "enabled"
    if settings and pkg == settings.value("tts_default_synth"):
        facts.role = "default text-to-speech engine"
    if inputs.home and pkg == inputs.home[0]:
        facts.role = "Home app"


def _apply_counters(facts: AppFacts, inputs: _Inputs) -> None:
    proc = inputs.procstats.apps.get(facts.app_id)
    if proc:
        facts.procstats_alive_pct = proc.alive_pct
        facts.procstats_fgs_pct = proc.fgs_pct
        facts.procstats_state = proc.state
        facts.rss_avg_mb, facts.pss_avg_mb = proc.rss_avg_mb, proc.pss_avg_mb
        if proc.evidence:
            facts.evidence["procstats"] = proc.evidence
    use = inputs.battery
    if use:
        uid = facts.app_id  # batterystats keys user-0 UIDs by their plain number
        if row := use.power.get(uid):
            facts.model_total_mah = row.total
            facts.model_background_mah = row.background
            facts.evidence["power"] = use.text.evidence(row.index)
        if counters := use.uids.get(uid):
            facts.screen_off_cpu_s = counters.screen_off_cpu_s
            facts.bt_scan_s = counters.bt_scan_s
            facts.bt_results = counters.bt_results
            facts.wakeup_alarms = counters.wakeup_alarms
            if "bt_scan" in counters.refs and counters.bt_scan_s >= BLE_SCAN_FLAG_S:
                facts.evidence["bt"] = use.text.evidence(counters.refs["bt_scan"])
            elif "so_cpu" in counters.refs and counters.screen_off_cpu_s:
                facts.evidence["battery_uid"] = use.text.evidence(
                    counters.refs["so_cpu"],
                )
    if inputs.alarms and facts.package in inputs.alarms.wakeups:
        count, evidence = inputs.alarms.wakeups[facts.package]
        facts.alarm_wakeups_since_boot = count
        facts.evidence["alarms"] = evidence


def _collect_facts(inputs: _Inputs, third_party: ThirdParty) -> list[AppFacts]:
    reference = inputs.ctx.windows.dump_time
    result = []
    for pkg, app_id in sorted(third_party.app_ids.items()):
        facts = AppFacts(pkg, app_id)
        facts.evidence["installed"] = third_party.evidence[pkg]
        state = inputs.package_states.get(pkg)
        if state:
            facts.never_launched = state.not_launched
            if state.first_install and reference:
                facts.installed_days = (
                    reference - state.first_install
                ).total_seconds() / 86400
        _apply_usage(facts, inputs.usage)
        _apply_roles(facts, inputs)
        _apply_counters(facts, inputs)
        result.append(facts)
    return result


def _use_phrase(facts: AppFacts) -> str:
    if facts.days_since_use is None:
        return "usage unknown"
    if facts.since_install:
        return f"not opened since it was installed {facts.days_since_use:.0f} days ago"
    if facts.use_lower_bound:
        return f"not opened for at least {facts.days_since_use:.0f} days"
    if facts.days_since_use < 1:
        return "opened today"
    return f"last opened {facts.days_since_use:.0f} days ago"


_RESTRICT_ADVICE = (
    "Whether to keep it is the user's call. If it is no longer needed, uninstall "
    "it (Settings > Apps > (app) > Uninstall). If it is needed only now and then, "
    "set Settings > Apps > (app) > App battery usage > Restricted and remove any "
    "notification or accessibility access it does not need (Settings > "
    "Notifications > Device & app notifications; Settings > Accessibility)."
)


def _dormant_active_finding(
    apps: list[tuple[AppFacts, list[str]]],
    windows: Windows,
) -> Finding:
    """One finding for every dormant app that still works in the background.

    It is medium only when at least one app shows background energy on
    battery; a foreground service or a live process alone is low.
    """
    energetic = [a.package for a, _ in apps if a.energy_signals(windows)]
    listing = "; ".join(
        f"{a.package} ({_use_phrase(a)}: {', '.join(signals)}"
        + (f"; {', '.join(a.privileges())}" if a.privileges() else "")
        + ")"
        for a, signals in apps[:10]
    )
    if energetic:
        window = "on_battery"
        energy = f"Background energy on battery: {', '.join(energetic)}. "
    else:
        window = "last_24h" if any(a.alive for a, _ in apps) else "snapshot"
        energy = (
            "None of them shows background energy on battery; they keep a "
            "process or a foreground service running. "
        )
    evidence = [
        a.evidence[kind]
        for a, _ in apps
        for kind in _DORMANT_EVIDENCE
        if kind in a.evidence
    ]
    return Finding(
        id="third_party_apps.dormant-active",
        title=f"Apps not opened for {DORMANT_DAYS}+ days still run in the background",
        symptom="battery",
        severity="medium" if energetic else "low",
        basis="measured",
        window=window,
        summary=(
            f"{len(apps)} third-party app(s) not opened for {DORMANT_DAYS}+ days "
            f"still run without the user: {listing}. {energy}Usage stats count "
            "only screen time, so a background feature may still be in use."
        ),
        metrics={
            "apps": len(apps),
            "packages": ", ".join(a.package for a, _ in apps),
            "apps_with_background_energy": len(energetic),
            "energy_packages": ", ".join(energetic),
        },
        evidence=evidence[:_DORMANT_EVIDENCE_CAP],
        recommendation=_RESTRICT_ADVICE,
        followups=[
            "Ask whether their background features (sync, watch link, push) are used.",
            (
                "After restricting, check their UIDs in 'dumpsys batterystats "
                "--charged' after the next charge: foreground-service and scan "
                "time should go."
            ),
        ],
    )


def _dormant_privileged_finding(apps: list[AppFacts]) -> Finding:
    listing = "; ".join(
        f"{a.package} ({_use_phrase(a)}; {', '.join(a.privileges())}"
        + (
            f"; process alive {a.procstats_alive_pct:.0f}% of the procstats window, "
            "kept bound by the system"
            if a.alive and a.system_bound
            else ""
        )
        + ")"
        for a in apps[:10]
    )
    return Finding(
        id="third_party_apps.dormant-privileged",
        title="Unused apps keep battery exemptions or system bindings",
        symptom="battery",
        severity="low",
        basis="measured",
        window="snapshot",
        summary=(
            f"{len(apps)} third-party app(s) not opened for {DORMANT_DAYS}+ days hold "
            "standing privileges but showed no background work of their own in the "
            f"data: {listing}."
        ),
        metrics={"apps": len(apps), "packages": ", ".join(a.package for a in apps)},
        evidence=[ev for a in apps[:6] for ev in list(a.evidence.values())[:2]],
        recommendation=_RESTRICT_ADVICE,
        followups=[
            "An exemption lets the app run in Doze at will; check again in a few days.",
        ],
    )


def _persistent_finding(apps: list[AppFacts], procstats_h: float | None) -> Finding:
    listing = "; ".join(
        f"{a.package} ("
        + ", ".join(
            filter(
                None,
                [
                    ", ".join(a.fgs_types) or None,
                    f"Fgs {a.procstats_fgs_pct:.0f}%" if a.procstats_fgs_pct else None,
                    _use_phrase(a),
                ],
            ),
        )
        + ")"
        for a in apps[:10]
    )
    return Finding(
        id="third_party_apps.persistent-foreground-services",
        title="Third-party apps keep a foreground service running all the time",
        symptom="both",
        severity="low",
        basis="measured",
        window="last_24h",
        summary=(
            f"{len(apps)} third-party app(s) run a foreground service now or spent at "
            f"least {PERSISTENT_PCT:.0f}% of the procstats window"
            + (f" ({procstats_h:.1f} h)" if procstats_h else "")
            + f" in that state: {listing}. A foreground service keeps the process "
            "and its memory alive and exempts it from most background limits."
        ),
        metrics={"apps": len(apps), "packages": ", ".join(a.package for a in apps)},
        evidence=[
            a.evidence.get("fgs")
            or a.evidence.get("procstats")
            or a.evidence["installed"]
            for a in apps[:10]
        ],
        recommendation=(
            "Keep the ones whose always-on function is wanted (VPN, watch link, push "
            "notifications). For the others, turn the feature off in the app or set "
            "Settings > Apps > (app) > App battery usage > Restricted."
        ),
        followups=[
            "Check each app's network packets and wakeups on battery to rank them.",
        ],
    )


def _exempt_energy_finding(apps: list[tuple[AppFacts, list[str]]]) -> Finding:
    listing = "; ".join(f"{a.package} ({', '.join(s)})" for a, s in apps[:10])
    return Finding(
        id="third_party_apps.exempt-background-energy",
        title="Apps exempt from battery optimisation use energy in the background",
        symptom="battery",
        severity="low",
        basis="measured",
        window="on_battery",
        summary=(
            f"{len(apps)} app(s) on the battery-optimisation exemption list used "
            f"the exemption on battery: {listing}. The exemption lets them run, "
            "hold wakelocks and use the network during Doze."
        ),
        metrics={"apps": len(apps), "packages": ", ".join(a.package for a, _ in apps)},
        evidence=[a.evidence["exempt"] for a, _ in apps[:10] if "exempt" in a.evidence],
        recommendation=(
            "Remove the exemption unless the app must deliver real-time events: "
            "Settings > Apps > (app) > App battery usage > Optimized."
        ),
        followups=["Measure screen-off drain with and without the exemption."],
    )


def _launcher_finding(inputs: _Inputs) -> Finding | None:
    dump = inputs.package_dump
    home = inputs.home
    if not dump or not dump.recents or not home or dump.recents_index is None:
        return None
    home_pkg, home_ev = home
    if home_pkg in {dump.recents, _LAUNCHER_FALLBACK}:
        return None
    resident = []
    for pkg in (home_pkg, dump.recents):
        state = dump.packages.get(pkg)
        proc = (
            inputs.procstats.apps.get(state.app_id) if state and state.app_id else None
        )
        if proc:
            resident.append(
                f"{pkg} alive {proc.alive_pct:.0f}% "
                f"(RSS {proc.rss_avg_mb or 0:.0f} MB)",
            )
    return Finding(
        id="third_party_apps.two-launchers",
        title="Two launchers are loaded: the Home app and the system Recents provider",
        symptom="slowness",
        severity="low",
        basis="inferred",
        window="snapshot",
        summary=(
            f"The Home app is {home_pkg}, while {dump.recents} provides the Recents "
            "screen and stays loaded as well"
            + (f" (procstats: {'; '.join(resident)})" if resident else "")
            + ". Both launchers hold memory."
        ),
        metrics={
            "home": home_pkg,
            "recents": dump.recents,
            "home_candidates": ", ".join(
                _component_package(c)
                for c in dump.home_candidates
                if not c.startswith(_LAUNCHER_FALLBACK)
            ),
        },
        evidence=[home_ev, dump.text.evidence(dump.recents_index)],
        recommendation=(
            "If the third-party launcher's features are not needed, choose the "
            "system launcher in Settings > Apps > Default apps > Home app."
        ),
        followups=["Compare both launchers' PSS in 'dumpsys meminfo'."],
    )


def _keyboard_finding(inputs: _Inputs) -> Finding | None:
    settings = inputs.settings
    enabled = setting_components(settings, "enabled_input_methods")
    if settings is None or len(enabled) < SEVERAL_IMES:
        return None
    default = settings.value("default_input_method") or ""
    return Finding(
        id="third_party_apps.several-keyboards",
        title=f"{len(enabled)} input methods are enabled",
        symptom="info",
        severity="info",
        basis="measured",
        window="snapshot",
        summary=(
            f"{len(enabled)} keyboards and voice-input methods are enabled; only the "
            f"default ({_component_package(default) or 'unknown'}) stays bound. The "
            "others load only when picked, so they cost memory only after a switch."
        ),
        metrics={
            "enabled_input_methods": len(enabled),
            "packages": ", ".join(_component_package(c) for c in enabled),
        },
        evidence=[
            ev
            for key in ("enabled_input_methods", "default_input_method")
            for ev in settings.evidence(key)
        ],
        recommendation=(
            "Turn off keyboards that are not used: Settings > System > Keyboard > "
            "On-screen keyboard."
        ),
    )


def _inventory_metrics(
    inputs: _Inputs,
    third_party: ThirdParty,
    apps: list[AppFacts],
) -> dict[str, Any]:
    usage = inputs.usage
    settings = inputs.settings
    with_record = [a for a in apps if usage and a.package in usage.apps]
    return {
        "third_party_apps": len(apps),
        "third_party_list_source": third_party.source,
        "multi_user_installs": third_party.multi_user,
        "usage_window_days": _round(usage.window_days, 1) if usage else None,
        "apps_without_usage_record": len(apps) - len(with_record),
        "apps_never_launched_in_usage_window": sum(
            1 for a in with_record if not a.launches and not a.used_h
        ),
        "dormant_apps": sum(1 for a in apps if a.dormant),
        "used_within_dormant_days": sum(1 for a in apps if a.dormant is False),
        "exempt_user_apps": len(inputs.exemptions),
        "exempt_third_party_apps": sum(1 for a in apps if a.exempt),
        "notification_listeners": len(
            setting_components(settings, "enabled_notification_listeners"),
        ),
        "accessibility_services": len(
            setting_components(settings, "enabled_accessibility_services"),
        ),
        "enabled_input_methods": len(
            setting_components(settings, "enabled_input_methods"),
        ),
        "foreground_services_now": len(inputs.foreground_services),
        "third_party_fgs_apps_now": sum(1 for a in apps if a.fgs_types),
        "third_party_persistent_apps": sum(
            1 for a in apps if (a.procstats_alive_pct or 0.0) >= PERSISTENT_PCT
        ),
        "background_restricted_apps": (
            len(inputs.alarms.restricted)
            if inputs.alarms and inputs.alarms.restricted_listed
            else None
        ),
        "procstats_window_h": _round(inputs.procstats.hours, 1),
    }


def _sort_key(facts: AppFacts, windows: Windows) -> tuple:
    signals = facts.background_signals(windows)
    return (
        -(bool(facts.dormant) and facts.runs_on_its_own(windows)),
        -len(signals),
        -len(facts.privileges()),
        -(facts.model_background_mah or 0.0),
        -(facts.procstats_alive_pct or 0.0),
        facts.package,
    )


def _scans_reported(ctx: Context, finding: Finding, apps: list[AppFacts]) -> None:
    """Link ``finding`` to the BLE finding when that names one of its scanning apps.

    background_scanning_sensors_location.ble owns the scan; this finding adds
    why the app is notable (dormant, exempt).
    """
    ble = ctx.finding("background_scanning_sensors_location.ble")
    if ble is None:
        return
    for facts in apps[:10]:
        named = re.search(
            rf"(?<![\w.]){re.escape(facts.package)}(?![\w.])", ble.summary
        )
        if (facts.bt_scan_s or 0.0) >= BLE_SCAN_FLAG_S and named:
            link(ble, finding)
            return


def _inventory_findings(inputs: _Inputs, apps: list[AppFacts]) -> list[Finding]:
    ctx = inputs.ctx
    windows = ctx.windows
    active: list[tuple[AppFacts, list[str]]] = []
    idle_privileged: list[AppFacts] = []
    persistent: list[AppFacts] = []
    exempt_energy: list[tuple[AppFacts, list[str]]] = []
    for facts in apps:
        if facts.dormant and facts.runs_on_its_own(windows):
            active.append((facts, facts.background_signals(windows)))
        elif facts.dormant and facts.privileges():
            idle_privileged.append(facts)
        elif not facts.dormant and facts.persistent_fgs:
            persistent.append(facts)
        energy = facts.energy_signals(windows)
        if facts.exempt and not facts.dormant and energy:
            exempt_energy.append((facts, facts.presence_signals() + energy))
    dormant = _dormant_active_finding(active, windows) if active else None
    always_on = (
        _persistent_finding(persistent, inputs.procstats.hours) if persistent else None
    )
    exempt = _exempt_energy_finding(exempt_energy) if exempt_energy else None
    if dormant:
        _scans_reported(ctx, dormant, [a for a, _ in active])
    if exempt:
        _scans_reported(ctx, exempt, [a for a, _ in exempt_energy])
        listed = {a.package for a, _ in exempt_energy[:10]}
        if always_on and listed & {a.package for a in persistent[:10]}:
            link(exempt, always_on)
    privileged = (
        _dormant_privileged_finding(idle_privileged) if idle_privileged else None
    )
    return [
        f
        for f in (
            dormant,
            privileged,
            always_on,
            exempt,
            _launcher_finding(inputs),
            _keyboard_finding(inputs),
        )
        if f
    ]


@analyzer("third_party_apps", after=("windows", "background_scanning_sensors_location"))
def third_party_apps(ctx: Context) -> Result:
    """Inventory third-party apps and flag dormant or always-running ones."""
    inputs = _Inputs(ctx)
    third_party = inputs.third_party
    if third_party is None:
        msg = "no third-party package list (pm list packages -3 -U or dumpsys package)"
        raise SkipError(msg)
    apps = _collect_facts(inputs, third_party)
    result = Result(
        "third_party_apps",
        window="snapshot",
        metrics=_inventory_metrics(inputs, third_party, apps),
    )
    apps.sort(key=lambda a: _sort_key(a, ctx.windows))
    result.add_table("apps", [a.row() for a in apps])
    result.add_table(
        "dormant_with_privileges_or_activity",
        [
            a.row()
            for a in apps
            if a.dormant and (a.privileges() or a.background_signals(ctx.windows))
        ],
    )
    result.add_table(
        "foreground_services",
        [
            {
                "package": s.package,
                "service": s.service,
                "types": ", ".join(s.types),
                "ref": s.evidence.ref,
            }
            for s in inputs.foreground_services
        ],
    )
    result.findings = _inventory_findings(inputs, apps)
    result.notes.extend(inputs.notes)
    if inputs.usage is None:
        result.notes.append("No usage statistics: dormancy is unknown.")
    elif inputs.usage.window_days is None:
        result.notes.append(
            "The usage-stats window start could not be read; apps without a usage "
            "record rely on the standby history for their last use.",
        )
    if inputs.usage and inputs.usage.skipped:
        result.notes.append(f"{inputs.usage.skipped} usage lines could not be parsed.")
    if inputs.procstats.skipped:
        result.notes.append(
            f"{inputs.procstats.skipped} procstats lines could not be read."
        )
    result.notes.append(
        "Days since use come from the yearly usage stats; for apps without use in "
        "that window they are a lower bound (window length, or the standby "
        "history's device-on time since the user last used the app), capped at "
        "the install age. A standby last use at the history's start "
        "(usedByUser equal to totalElapsedTime) means never and is ignored.",
    )
    return result
