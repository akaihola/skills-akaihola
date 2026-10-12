"""Parsing helpers shared by all analyzers: numbers, durations, UIDs, timestamps.

Android dumps mix locales and formats inside one file. A phone with a
decimal-comma locale prints ``99,1%`` and ``4,52MB`` in batterystats while the
power model still prints ``79.1`` and meminfo groups thousands as ``375,877K``.
Callers must pick the parser that matches the field, never a generic float().

The ``load_*`` functions parse one input once per run (``Sources.memo``) and
return a typed view that every analyzer can share: process CPU (``ps``),
settings and the event log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .model import Context, Evidence
    from .source import Text

_DURATION_RE = re.compile(r"(\d+)(ms|d|h|m|s)")
_DURATION_MS = {"d": 86_400_000, "h": 3_600_000, "m": 60_000, "s": 1000, "ms": 1}


def parse_duration_ms(text: str) -> int:
    """Return the milliseconds in a batterystats-style duration.

    Accepts the spaced summary form ``1d 2h 48m 39s 700ms``, the compact history
    form ``+1h05m05s381ms``, alarm offsets ``+38s482ms`` and ``0ms``. A leading
    ``-`` makes the result negative.
    """
    parts = _DURATION_RE.findall(text)
    if not parts:
        msg = f"no duration in {text!r}"
        raise ValueError(msg)
    total = sum(int(value) * _DURATION_MS[unit] for value, unit in parts)
    return -total if text.strip().startswith("-") else total


def parse_decimal(text: str) -> float:
    """Parse a locale-dependent decimal such as ``99,1``, ``91.9`` or ``87,4%``.

    A lone comma is a decimal separator. With both separators present, the
    last one is the decimal separator and the other groups thousands.
    """
    s = text.strip().strip("()").rstrip("%").replace("\u202f", "").replace("\xa0", "")
    s = s.replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


_SIZE_UNITS = {
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "M": 1024**2,
    "MB": 1024**2,
    "G": 1024**3,
    "GB": 1024**3,
}
_SIZE_RE = re.compile(r"^\s*([\d.,]+)\s*([KMG]?B?)\s*$", re.IGNORECASE)


def parse_size_bytes(text: str) -> int:
    """Parse a 1024-based size such as ``4,52MB``, ``380KB`` or ``12B``."""
    m = _SIZE_RE.match(text)
    if not m:
        msg = f"no size in {text!r}"
        raise ValueError(msg)
    unit = m.group(2).upper() or "B"
    return round(parse_decimal(m.group(1)) * _SIZE_UNITS[unit])


_CLOCK_RE = re.compile(r"^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:[.,]\d+)?)$")


def parse_clock_s(text: str) -> float:
    """Return the seconds in a clock-style duration.

    Accepts ``mm:ss``, ``hh:mm:ss`` (hours may exceed 24), toybox ps's
    ``dd-hh:mm:ss`` and top's ``mm:ss.cc``.
    """
    m = _CLOCK_RE.match(text.strip())
    if not m:
        msg = f"no clock time in {text!r}"
        raise ValueError(msg)
    days, hours, minutes = (int(g) if g else 0 for g in m.groups()[:3])
    return days * 86_400 + hours * 3600 + minutes * 60 + parse_decimal(m[4])


_UTC_OFFSET_RE = re.compile(r"^([+-])(\d\d):?(\d\d)$")


@lru_cache(maxsize=16)
def parse_utc_offset(text: str | None) -> timedelta | None:
    """Parse ``+0300`` or ``-05:30``; return None when absent or malformed."""
    m = _UTC_OFFSET_RE.match(text.strip()) if text else None
    if not m:
        return None
    offset = timedelta(hours=int(m[2]), minutes=int(m[3]))
    return -offset if m[1] == "-" else offset


# --- Formatting --------------------------------------------------------------


def fmt_duration(seconds: float | None, *, resolution: str = "s") -> str:
    """Format seconds as ``5h02m40s`` (``resolution="m"``: ``5h02m``).

    Parts below the resolution are dropped, as batterystats does; None gives
    ``"?"``.
    """
    if seconds is None:
        return "?"
    sign = "-" if seconds < 0 else ""
    hours, rest = divmod(int(abs(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    if resolution == "m":
        text = f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"
    elif hours:
        text = f"{hours}h{minutes:02d}m{secs:02d}s"
    else:
        text = f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"
    return sign + text


def pct(part: float | None, whole: float | None, digits: int = 1) -> float | None:
    """Return ``part`` as a rounded percentage of ``whole``, or None if unknown."""
    if part is None or not whole:
        return None
    return round(100 * part / whole, digits)


def per_hour(
    count: float | None,
    seconds: float | None,
    digits: int = 1,
) -> float | None:
    """Return ``count`` per hour over ``seconds``, rounded, or None if unknown."""
    if count is None or not seconds or seconds < 0:
        return None
    return round(count * 3600 / seconds, digits)


# Well-known Android system UIDs, from AOSP
# system/core/libcutils/include/private/android_filesystem_config.h
SYSTEM_UIDS = {
    0: "root",
    1000: "system",
    1001: "radio",
    1002: "bluetooth",
    1003: "graphics",
    1004: "input",
    1005: "audio",
    1010: "wifi",
    1013: "media",
    1021: "gps",
    1027: "nfc",
    1036: "logd",
    1041: "audioserver",
    1047: "cameraserver",
    1066: "statsd",
    1069: "lmkd",
    1073: "networkstack",
    2000: "shell",
    9999: "nobody",
}
PER_USER_RANGE = 100_000
FIRST_APPLICATION_UID = 10_000
FIRST_ISOLATED_UID = 99_000
_UID_RE = re.compile(r"^u(\d+)([ais])(\d+)$")


def parse_uid(text: str) -> int:
    """Parse ``u0a169``, ``u10a5``, ``u0i3``, ``u0s1000``, ``1000`` or ``10169``."""
    s = text.strip()
    m = _UID_RE.match(s)
    if not m:
        return int(s)
    user, kind, number = int(m.group(1)), m.group(2), int(m.group(3))
    base = {"a": FIRST_APPLICATION_UID, "i": FIRST_ISOLATED_UID, "s": 0}[kind]
    return user * PER_USER_RANGE + base + number


def uid_class(uid: int, third_party: frozenset[int]) -> str:
    """Classify a UID for drain splits.

    Returns ``core`` (system UIDs below 10000 and negative pseudo-UIDs),
    ``isolated``, ``third_party`` or ``preinstalled_app``. Without a
    third-party list every app UID is just ``app``.
    """
    if uid < 0:
        return "core"
    app_id = uid % PER_USER_RANGE
    if app_id < FIRST_APPLICATION_UID:
        return "core"
    if app_id >= FIRST_ISOLATED_UID:
        return "isolated"
    if not third_party:
        return "app"
    return "third_party" if app_id in third_party else "preinstalled_app"


def format_uid(uid: int) -> str:
    """Format a UID the way batterystats does (``u0a169``, ``1000``).

    Negative values are netstats pseudo-UIDs (tethering, removed apps) and are
    returned as plain numbers.
    """
    if uid < 0:
        return str(uid)
    user, app_id = divmod(uid, PER_USER_RANGE)
    if app_id >= FIRST_ISOLATED_UID:
        return f"u{user}i{app_id - FIRST_ISOLATED_UID}"
    if app_id >= FIRST_APPLICATION_UID:
        return f"u{user}a{app_id - FIRST_APPLICATION_UID}"
    return str(uid) if user == 0 else f"u{user}s{app_id}"


_PACKAGE_LINE_RE = re.compile(r"(?:^package:|=)([A-Za-z][\w.]*) uid:([\d,]+)\s*$")
_PACKAGE_BLOCK_RE = re.compile(r"^\s*Package \[([\w.]+)\]")
_PACKAGE_APPID_RE = re.compile(r"^\s*(?:appId|userId)=(\d+)")
_PACKAGE_FLAGS_RE = re.compile(r"^\s+(?:pkg)?flags=\[([^\]]*)\]")
_CHECKIN_UID_RE = re.compile(r"^9,0,i,uid,(\d+),([A-Za-z][\w.]*)\s*$")


@dataclass
class PackageMap:
    """Map UIDs to package names; several packages may share one UID.

    ``third_party`` holds the app ids of user-installed packages; it is empty
    when no package list says which ones those are.
    """

    by_app_id: dict[int, list[str]]
    third_party: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def empty(cls) -> PackageMap:
        """Return a map that knows only the well-known system UIDs."""
        return cls({})

    @classmethod
    def from_pm_list(cls, text: str) -> PackageMap:
        """Parse ``pm list packages -U`` output, with or without ``-f`` paths."""
        result: dict[int, list[str]] = {}
        for line in text.splitlines():
            m = _PACKAGE_LINE_RE.search(line.strip())
            if not m:
                continue
            for uid in m.group(2).split(","):
                if uid:
                    app_id = int(uid) % PER_USER_RANGE
                    names = result.setdefault(app_id, [])
                    if m.group(1) not in names:
                        names.append(m.group(1))
        return cls(result)

    @classmethod
    def from_package_dump(cls, text: str) -> PackageMap:
        """Parse the ``Package [name]`` blocks of ``dumpsys package``.

        App ids of packages whose flags lack ``SYSTEM`` become ``third_party``.
        """
        result: dict[int, list[str]] = {}
        third_party: set[int] = set()
        current: str | None = None
        app_id: int | None = None
        for line in text.splitlines():
            if m := _PACKAGE_BLOCK_RE.match(line):
                current, app_id = m.group(1), None
            elif current is None:
                continue
            elif app_id is None and (m := _PACKAGE_APPID_RE.match(line)):
                app_id = int(m.group(1)) % PER_USER_RANGE
                names = result.setdefault(app_id, [])
                if current not in names:
                    names.append(current)
            elif app_id is not None and (m := _PACKAGE_FLAGS_RE.match(line)):
                if app_id >= FIRST_APPLICATION_UID and "SYSTEM" not in m[1].split():
                    third_party.add(app_id)
                current = None
        return cls(result, frozenset(third_party))

    @classmethod
    def from_checkin(cls, text: str) -> PackageMap:
        """Parse the ``9,0,i,uid,<uid>,<package>`` rows of ``batterystats -c``."""
        result: dict[int, list[str]] = {}
        for line in text.splitlines():
            if m := _CHECKIN_UID_RE.match(line):
                names = result.setdefault(int(m[1]) % PER_USER_RANGE, [])
                if m[2] not in names:
                    names.append(m[2])
        return cls(result)

    def merge(self, other: PackageMap) -> PackageMap:
        """Return a map with the packages and third-party ids of both maps."""
        merged = {k: list(v) for k, v in self.by_app_id.items()}
        for app_id, names in other.by_app_id.items():
            target = merged.setdefault(app_id, [])
            target.extend(n for n in names if n not in target)
        return PackageMap(merged, self.third_party | other.third_party)

    def packages(self, uid: int) -> list[str]:
        """Return the packages that run under ``uid`` (any user)."""
        return list(self.by_app_id.get(uid % PER_USER_RANGE, []))

    def name(self, uid: int) -> str:
        """Return a readable name: packages, a system UID name, or the UID itself.

        System UIDs such as 1000 are shared by dozens of packages, so their
        well-known name ("system") is more truthful than any one package.
        """
        if uid < 0:
            return f"pseudo-UID {uid}"
        app_id = uid % PER_USER_RANGE
        if app_id in SYSTEM_UIDS:
            return SYSTEM_UIDS[app_id]
        if names := self.by_app_id.get(app_id):
            if len(names) == 1:
                return names[0]
            return f"{names[0]} (+{len(names) - 1} shared)"
        return format_uid(uid)


@dataclass
class LogLine:
    """One logcat line in threadtime format, optionally with ``-v year``/``-v uid``."""

    ts: datetime
    uid: str | None
    pid: int
    tid: int
    level: str
    tag: str
    message: str
    lineno: int


_LOGCAT_RE = re.compile(
    r"^(?:(?P<year>\d{4})-)?(?P<mon>\d\d)-(?P<day>\d\d) "
    r"(?P<hms>\d\d:\d\d:\d\d)\.(?P<ms>\d{3})\s+"
    r"(?:(?P<uid>\S+)\s+)?(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<level>[VDIWEFS])\s+"
    r"(?P<tag>.*?)\s*: (?P<msg>.*)$",
)


def infer_year(month: int, day: int, reference: datetime) -> int:
    """Pick the year for a yearless ``MM-DD`` stamp that is not after ``reference``.

    Logcat's threadtime format has no year, and lines written before the clock
    was set at boot can carry a stale date. A stamp more than a day after the
    reference belongs to the previous year.
    """
    try:
        candidate = datetime(reference.year, month, day)
    except ValueError:
        return reference.year - 1
    if candidate > reference + timedelta(days=1):
        return reference.year - 1
    return reference.year


def iter_logcat(
    text: str,
    reference: datetime,
    first_line: int = 1,
) -> Iterator[LogLine]:
    """Parse logcat text, skipping buffer markers and wrapped lines.

    Yields:
        One :class:`LogLine` per parsable line, in input order.

    """
    for offset, line in enumerate(text.splitlines()):
        m = _LOGCAT_RE.match(line)
        if not m:
            continue
        mon, day = int(m["mon"]), int(m["day"])
        year = int(m["year"]) if m["year"] else infer_year(mon, day, reference)
        try:
            ts = datetime.strptime(
                f"{year}-{mon:02d}-{day:02d} {m['hms']}.{m['ms']}",
                "%Y-%m-%d %H:%M:%S.%f",
            )
        except ValueError:
            continue
        yield LogLine(
            ts=ts,
            uid=m["uid"],
            pid=int(m["pid"]),
            tid=int(m["tid"]),
            level=m["level"],
            tag=m["tag"],
            message=m["msg"],
            lineno=first_line + offset,
        )


def log_span(text: Text, reference: datetime) -> tuple[datetime, datetime] | None:
    """Return the first and last timestamps of a single-buffer log."""
    first = _first_stamp(text.lines, reference)
    last = _first_stamp(reversed(text.lines), reference)
    return (first, last) if first and last else None


def _first_stamp(lines: Iterable[str], reference: datetime) -> datetime | None:
    for line in lines:
        if found := next(iter_logcat(line, reference), None):
            return found.ts
    return None


# --- Process CPU (ps) ---------------------------------------------------------

_PS_NAME_COLUMNS = frozenset({"NAME", "CMD", "ARGS", "COMMAND", "CMDLINE"})
# Linux truncates thread names (comm) to 15 characters.
_COMM_LEN = 15


@dataclass
class PsRow:
    """One process (live ``ps -A``) or thread (bugreport ``ps -A -T``) row.

    ``cpu_s`` is the CPU time since the process or thread started; ``tid`` is
    None for process rows.
    """

    index: int
    pid: int
    tid: int | None
    user: str
    cpu_s: float
    name: str
    line: str
    ref: str = ""


def _ps_header(line: str) -> list[str] | None:
    tokens = line.split()
    if {"PID", "TIME"} <= set(tokens) and tokens[-1] in _PS_NAME_COLUMNS:
        return tokens
    return None


def _ps_row(text: Text, index: int, columns: list[str]) -> PsRow | None:
    """Parse one row; tolerate blank columns (``PCY``) before ``TIME``."""
    line = text.lines[index]
    tokens = list(re.finditer(r"\S+", line))
    time_col = columns.index("TIME")
    # A blank column shifts TIME left; columns after it are never blank.
    at = next(
        (
            k
            for k in range(min(time_col, len(tokens) - 1), -1, -1)
            if _CLOCK_RE.match(tokens[k][0])
        ),
        None,
    )
    if at is None:
        return None
    name_at = at + len(columns) - 1 - time_col
    pid_col = columns.index("PID")
    if name_at >= len(tokens) or pid_col >= at:
        return None
    tid_col = columns.index("TID") if "TID" in columns else None
    user_col = columns.index("USER") if "USER" in columns else None
    try:
        pid = int(tokens[pid_col][0])
        tid = int(tokens[tid_col][0]) if tid_col is not None and tid_col < at else None
        cpu_s = parse_clock_s(tokens[at][0])
    except ValueError:
        return None
    user = tokens[user_col][0] if user_col is not None and user_col < at else ""
    name = line[tokens[name_at].start() :].strip()
    return PsRow(index, pid, tid, user, cpu_s, name, line, text.ref(index))


def parse_ps(text: Text) -> list[PsRow]:
    """Parse ``ps`` output that has ``PID``, ``TIME`` and a trailing name column.

    Understands the live ``ps -A -o PID,PPID,USER,RSS,VSZ,TIME,S,NAME`` and
    the bugreport's ``PROCESSES AND THREADS`` (``ps -A -T -Z -O ...``), whose
    rows are threads. Unparsable rows are skipped.
    """
    rows: list[PsRow] = []
    columns: list[str] | None = None
    for i, line in enumerate(text.lines):
        if header := _ps_header(line):
            columns = header
        elif columns and line.strip() and (row := _ps_row(text, i, columns)):
            rows.append(row)
    return rows


def load_ps(ctx: Context) -> list[PsRow]:
    """Return the parsed process list: live ``ps`` first, else the thread list."""

    def build() -> list[PsRow]:
        for key in ("ps", "ps_threads"):
            if (text := ctx.sources.get(key)) and (rows := parse_ps(text)):
                return rows
        return []

    return ctx.sources.memo("ps_rows", build)


def _comm_forms(name: str) -> set[str]:
    """Return the names a thread list may show for process ``name``.

    The main thread's name is the process name cut to 15 characters; app
    processes keep the end of dotted names, others the start.
    """
    bare = name.strip("[]")
    if len(bare) <= _COMM_LEN:
        return {bare}
    return {bare, bare[:_COMM_LEN], bare[-_COMM_LEN:]}


def ps_cpu_by_name(rows: list[PsRow], names: Iterable[str]) -> dict[str, float]:
    """Return CPU seconds since start per process name, for the names found.

    Several processes with one name are summed. For thread rows, the process
    is found by its main thread and all its threads are summed.
    """
    by_pid: dict[int, float] = {}
    for row in rows:
        if row.tid is not None:
            by_pid[row.pid] = by_pid.get(row.pid, 0.0) + row.cpu_s
    found: dict[str, float] = {}
    for name in names:
        bare = name.strip("[]")
        forms = _comm_forms(name)
        total: float | None = None
        for row in rows:
            row_name = row.name.strip("[]")
            if row.tid is None and row_name == bare:
                total = (total or 0.0) + row.cpu_s
            elif row.tid == row.pid and row_name in forms:
                total = (total or 0.0) + by_pid[row.pid]
        if total is not None:
            found[name] = total
    return found


# --- Settings -----------------------------------------------------------------

SETTINGS_NAMESPACES = ("global", "secure", "system")
_SETTINGS_MARKER_RE = re.compile(r"^===\s*(GLOBAL|SECURE|SYSTEM)\s*$")
_SETTING_LINE_RE = re.compile(r"^([A-Za-z0-9_.:\-]+)=(.*)$")
_SETTINGS_TABLE_RE = re.compile(r"^(\w+) SETTINGS \(user (\d+)\)$")
_SETTING_ROW_RE = re.compile(r"^_id:\S* name:(\S+)(?: pkg:\S*)? value:(.*)$")
# Fields that follow the value in a dumpsys settings row (AOSP SettingsState).
_SETTING_ROW_TAILS = (" default:", " tag:")


@dataclass
class Settings:
    """Global, secure and system settings with their line indexes.

    Built from ``settings list`` (``===SECURE`` and ``===SYSTEM`` markers,
    the first block global) or from the user-0 tables of ``dumpsys settings``.
    Without markers or tables every key lands in ``global`` and namespaced
    lookups search all of them.
    """

    text: Text
    values: dict[str, dict[str, tuple[str, int]]]
    namespaced: bool
    skipped: int = 0

    def get(self, key: str, namespace: str = "") -> tuple[str, int] | None:
        """Return ``(value, line index)``; ``""`` searches global, secure, system."""
        if namespace and self.namespaced:
            return self.values.get(namespace, {}).get(key)
        for ns in SETTINGS_NAMESPACES:
            if key in self.values[ns]:
                return self.values[ns][key]
        return None

    def value(self, key: str, namespace: str = "") -> str | None:
        """Return the value of ``key``, or None if it is absent or ``null``."""
        found = self.get(key, namespace)
        if found is None or found[0] == "null":
            return None
        return found[0]

    def evidence(self, key: str, namespace: str = "") -> list[Evidence]:
        """Return a citation of the line holding ``key``, if present."""
        found = self.get(key, namespace)
        return [self.text.evidence(found[1])] if found else []

    def items(self, namespace: str) -> dict[str, str]:
        """Return ``{key: value}`` of one namespace."""
        return {k: v for k, (v, _) in self.values.get(namespace, {}).items()}


def _setting_row_value(raw: str) -> str:
    for tail in _SETTING_ROW_TAILS:
        raw = raw.split(tail, 1)[0]
    return raw.strip()


def parse_settings(text: Text) -> Settings:
    """Parse ``settings list`` output or the ``dumpsys settings`` tables.

    Multi-line values (JSON) leave continuation lines, which are counted in
    ``skipped``. Tables of other users and the config table are ignored.
    """
    values: dict[str, dict[str, tuple[str, int]]] = {
        ns: {} for ns in SETTINGS_NAMESPACES
    }
    namespace: str | None = "global"
    namespaced = False
    skipped = 0
    for i, line in enumerate(text.lines):
        stripped = line.strip()
        if m := _SETTINGS_MARKER_RE.match(stripped):
            namespace, namespaced = m[1].lower(), True
        elif m := _SETTINGS_TABLE_RE.match(stripped):
            ns = m[1].lower()
            namespace = ns if m[2] == "0" and ns in values else None
            namespaced = True
        elif m := _SETTING_ROW_RE.match(line):
            if namespace is not None:
                values[namespace].setdefault(m[1], (_setting_row_value(m[2]), i))
        elif m := _SETTING_LINE_RE.match(line):
            if namespace is not None:
                values[namespace].setdefault(m[1], (m[2].strip(), i))
        elif stripped and namespace is not None:
            skipped += 1
    return Settings(text, values, namespaced, skipped)


def load_settings(ctx: Context) -> Settings | None:
    """Return the parsed settings (live list, else the bugreport dump), or None."""

    def build() -> Settings | None:
        text = ctx.sources.get("settings") or ctx.sources.get("settings_dump")
        return parse_settings(text) if text else None

    return ctx.sources.memo("settings", build)


# --- Event log ----------------------------------------------------------------

# battery_status payload: status, health, present, plugged, technology.
_BATTERY_PLUGGED_FIELD = 3


@dataclass
class Transition:
    """A screen or power state from the event log: ``on`` is screen on or plugged."""

    ts: datetime
    on: bool
    ref: str
    line: str


@dataclass
class EventLog:
    """The parsed event log (``logcat -b events``), oldest first."""

    text: Text | None = None
    lines: list[LogLine] = field(default_factory=list)

    def ref(self, line: LogLine) -> str:
        """Return the ``origin:line`` citation of a parsed line."""
        origin = self.text.origin if self.text else "?"
        return f"{origin}:{line.lineno}"

    def by_tag(self, tag: str) -> list[LogLine]:
        """Return the lines with event tag ``tag``."""
        return [line for line in self.lines if line.tag == tag]

    def span(self) -> tuple[datetime, datetime] | None:
        """Return the times of the first and the last parsed line."""
        return (self.lines[0].ts, self.lines[-1].ts) if self.lines else None

    def _transition(self, line: LogLine, on: bool) -> Transition:
        text = self.text
        source = text.lines[line.lineno - text.first_line] if text else ""
        return Transition(line.ts, on, self.ref(line), source.strip())

    def screen_transitions(self) -> list[Transition]:
        """Return every ``screen_toggled`` event (``on``: the screen turned on)."""
        return [
            self._transition(line, line.message.strip() == "1")
            for line in self.by_tag("screen_toggled")
            if line.message.strip() in {"0", "1"}
        ]

    def battery_states(self) -> list[Transition]:
        """Return every ``battery_status`` event (``on``: on external power)."""
        found = []
        for line in self.by_tag("battery_status"):
            fields = line.message.strip().strip("[]").split(",")
            try:
                plugged = int(fields[_BATTERY_PLUGGED_FIELD]) > 0
            except (IndexError, ValueError):
                continue
            found.append(self._transition(line, plugged))
        return found

    def power_transitions(self) -> list[Transition]:
        """Return the plug-ins (``on``) and unplugs among ``battery_status`` events."""
        changes: list[Transition] = []
        previous: bool | None = None
        for state in self.battery_states():
            if previous is not None and state.on != previous:
                changes.append(state)
            previous = state.on
        return changes


def load_event_log(ctx: Context) -> EventLog:
    """Return the parsed ``logcat_events`` dump; empty when it is missing."""

    def build() -> EventLog:
        text = ctx.sources.get("logcat_events")
        if text is None:
            return EventLog()
        reference = ctx.windows.log_reference()
        lines = list(iter_logcat(text.text, reference, text.first_line))
        lines.sort(key=lambda line: line.ts)
        return EventLog(text, lines)

    return ctx.sources.memo("event_log", build)
