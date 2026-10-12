"""Battery history and since-charge drain: when the phone slept, woke and drained.

batterystats prints the same data in three shapes, and this module reads all
of them:

- the checkin CSV (``dumpsys batterystats -c`` or the bugreport's CHECKIN
  BATTERYSTATS section). Its ``9,h,`` rows are the event history with
  millisecond deltas and a string pool (``9,hsp,``); its ``bt``, ``dc``, ``m``
  and ``pws`` rows hold the since-charge totals;
- the full text dump, whose "Battery History" block is the same history in
  readable form and whose "Daily stats" hold about ten days of level steps;
- the ``--charged`` summary with the counter-based discharge split.

The history is a list of state changes: ``+running``/``-running`` is the SoC
leaving and entering suspend, ``+screen``, ``+plugged``, ``device_idle=full``,
``wake_reason=0:"41 WLAN_CE_2"`` and so on. Replaying it gives exact
screen-off spans, resumes and awake time. Those are measured values; the mAh
figures beside them come from the fuel gauge and, on many gauges, are whole
steps of 1 % of the learned capacity.
"""

from __future__ import annotations

import bisect
import csv
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise
from operator import itemgetter
from typing import TYPE_CHECKING, Any, NamedTuple

from .batterystats import load_since_charge
from .common import fmt_duration, parse_decimal, parse_duration_ms, pct, per_hour
from .model import Context, Evidence, Finding, Result, SkipError, analyzer, link

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from .batterystats import SinceCharge
    from .source import Text

# A wake reason on a later record still belongs to the resume when it is
# stamped within this many ms of it (batterystats sometimes writes the reason
# as a separate record with the same timestamp).
REASON_ATTACH_MS = 1

# Below this much screen-off time on battery, rates and shares are too noisy
# for findings (a few wakes or one 1 % gauge step dominate).
MIN_SCREEN_OFF_FOR_FINDINGS_S = 1800

# Screen-off awake share: a phone that suspends properly is awake a few % of
# the screen-off time. Above 10 % something keeps waking it; above 30 % it
# hardly sleeps.
AWAKE_SHARE_SUSPICIOUS_PCT = 10.0
AWAKE_SHARE_SEVERE_PCT = 30.0
# Resumes per screen-off hour: 180/h is one every 20 s, far above the few
# alarms and pushes per minute a quiet phone needs.
WAKE_STORM_PER_H = 180.0
# Ten resumes a minute make a wake storm severe even at a low awake share.
WAKE_STORM_HIGH_PER_H = 600.0
# One wake reason behind this share of resumes means a single trigger source.
DOMINANT_REASON_SHARE_PCT = 80.0
# A healthy resume handles its event and suspends again well within a second;
# a longer median awake time per resume is worth a sentence in the summary.
SLOW_RESUSPEND_MEDIAN_S = 1.0
# Awake time without any Android wakelock above this share of awake time is
# kernel or driver work that per-app battery statistics cannot show.
KERNEL_AWAKE_SHARE_PCT = 50.0

# Lag scan for periodic resumes: lags from 1 s to 25 s in 50 ms steps with a
# 50 ms tolerance, wide enough for keepalives up to ~12 s with a harmonic.
LAG_MIN_MS = 1000
LAG_MAX_MS = 25_000
LAG_STEP_MS = 50
LAG_TOL_MS = 50
# Fewer resumes than this give a noisy lag spectrum.
MIN_RESUMES_FOR_PERIODICITY = 300
# A lag whose share of resumes with an earlier neighbour exceeds the median
# share by this many percentage points marks a periodic sender.
PERIODIC_EXCESS_PP = 10.0
# Harmonics count as supporting a period when their excess reaches this
# fraction of the fundamental's excess.
HARMONIC_SUPPORT_RATIO = 0.5
# Stability bins for the periodic share.
PERIODICITY_BIN_MS = 20 * 60_000
# Harmonics checked when measuring the share of resumes on a period's grid.
GRID_HARMONICS = 4

# Idle drain in %/h of the learned capacity. A suspending phone in Doze uses
# well under 1 %/h; the research behind this skill treated ~2 %/h screen-off as
# excessive. These are general expectations, not device measurements.
IDLE_DRAIN_MEDIUM_PCT_PER_H = 1.0
IDLE_DRAIN_HIGH_PCT_PER_H = 2.0
# General healthy deep-idle drain range quoted in reports (not measured).
HEALTHY_IDLE_MAH_PER_H = "10-20"
# The displayed level lags the counter in Doze; flag when the counter-based
# screen-off drain is this many times the level-based one and at least
# LEVEL_SKEW_MIN_STEPS gauge steps apart.
LEVEL_HIDES_DRAIN_RATIO = 1.5
LEVEL_SKEW_MIN_STEPS = 2

# State of health (learned / design capacity): below 80 % a battery counts as
# worn and replacement is the usual advice; below 70 % runtime loss is severe.
SOH_WORN_PCT = 80.0
SOH_SEVERE_PCT = 70.0
# A cycle count below this share of the cycles the device age implies means
# the counter was reset or the pack was replaced.
CYCLE_COUNT_IMPLAUSIBLE_RATIO = 0.5
# Fewer days than this make a cycles-per-day projection meaningless.
MIN_DAYS_FOR_CYCLE_CHECK = 30
# Placeholder install dates that do not reflect when the device was set up.
PLACEHOLDER_INSTALL_YEARS = frozenset({1970, 2008, 2009})

# Gauge quantization: when every charge counter value is a whole % of the
# learned capacity, mAh figures carry +-1 step. A screen-off test should be
# long enough that one step is under this share of the expected drain.
QUANTIZATION_MAX_SHARE = 0.25
# Share of charge samples that must be whole-% values to call the counter
# SOC-derived, and the minimum number of samples.
SOC_DERIVED_MIN_SHARE = 0.9
SOC_DERIVED_MIN_SAMPLES = 5

# Daily steps: a 1 % discharge step faster than this at or below
# LOW_LEVEL_PCT moves ~1 % of capacity in seconds, which no phone load does:
# it is the voltage collapsing near cutoff.
FAST_STEP_S = 60
LOW_LEVEL_PCT = 12
# Days with at least this many fast low-level steps show collapse.
COLLAPSE_MIN_FAST_STEPS = 3
# Deep discharge: the level reached this or less.
DEEP_DISCHARGE_PCT = 2
# Days with deep discharges before the habit is worth a finding.
DEEP_DISCHARGE_MIN_DAYS = 3
# A level rebound of at most this many points after reaching a low level is
# the gauge recovering after a shutdown, not a charge.
REBOUND_MAX_POINTS = 10

# Battery saver drain stats: cells shorter than this give absurd mAh/h rates.
DRAIN_STATS_MIN_MINUTES = 5

# Previous charge period: a screen-off rate this many times the current one
# means the current window is not representative.
PREVIOUS_RATE_RATIO = 2.0
# Mobile radio active above this share of battery time with the screen mostly
# off means apps keep the cellular connection busy.
MOBILE_RADIO_SHARE_PCT = 20.0
# Kernel wakelocks that, held this long, mean the phone did not suspend.
SUSPEND_BLOCKER_MIN_MS = 30 * 60_000
SUSPEND_BLOCKERS = ("PowerManager.SuspendLockout",)

_MS_PER_H = 3_600_000
_FULL = 100

_WINDOW_PREVIOUS = "previous_charge"


# ---------------------------------------------------------------------------
# History records


class Token(NamedTuple):
    """One state change or event of a history record, in text-dump names."""

    sign: str  # "+", "-" or "" for a value
    name: str  # "running", "screen", "wake_reason", "device_idle", "charge"
    value: str | None = None  # "full", "41 WLAN_CE_2", "2794"
    uid: str | None = None


@dataclass
class Record:
    """One history record: a time offset, the battery level and its changes."""

    index: int  # line index in the source text
    t_ms: int  # ms since the first record
    level: int | None = None
    tokens: tuple[Token, ...] = ()
    command: str = ""  # RESET, TIME, START, SHUTDOWN or OVERFLOW
    clock: datetime | None = None  # local wall time carried by RESET/TIME


@dataclass
class History:
    """A parsed battery history with its wall-clock anchors."""

    text: Text
    fmt: str  # "checkin" or "text"
    records: list[Record]
    clock_source: str
    continuation_lines: int = 0
    unparsed_lines: int = 0
    backward_steps: int = 0
    max_backward_ms: int = 0
    anchors: list[tuple[int, int, datetime]] = field(default_factory=list)

    def wall(self, pos: int) -> datetime | None:
        """Return the local wall time of record ``pos`` from the nearest anchor."""
        if not self.anchors:
            return None
        i = bisect.bisect_right([a[0] for a in self.anchors], pos) - 1
        _, t_anchor, clock = self.anchors[max(i, 0)]
        return clock + timedelta(milliseconds=self.records[pos].t_ms - t_anchor)

    def evidence(self, pos: int) -> Evidence:
        """Cite record ``pos``."""
        return self.text.evidence(self.records[pos].index)


# Checkin codes, from AOSP BatteryStats HISTORY_STATE(2)_DESCRIPTIONS and
# HISTORY_EVENT_CHECKIN_NAMES, mapped to the names of the text dump.
_CHECKIN_NAMES = {
    "r": "running",
    "w": "wake_lock",
    "s": "sensor",
    "g": "gps",
    "Wl": "wifi_full_lock",
    "Ws": "wifi_scan",
    "Wm": "wifi_multicast",
    "Wr": "wifi_radio",
    "Pr": "mobile_radio",
    "Psc": "phone_scanning",
    "a": "audio",
    "S": "screen",
    "BP": "plugged",
    "Sd": "screen_doze",
    "Pcn": "data_conn",
    "Pst": "phone_state",
    "Pss": "phone_signal_strength",
    "Sb": "brightness",
    "ps": "power_save",
    "v": "video",
    "Ww": "wifi_running",
    "W": "wifi",
    "fl": "flashlight",
    "di": "device_idle",
    "ch": "charging",
    "Ud": "usb_data",
    "Pcl": "phone_in_call",
    "b": "bluetooth",
    "Wss": "wifi_signal_strength",
    "Wsp": "wifi_suppl",
    "ca": "camera",
    "bles": "ble_scan",
    "Chtp": "cellular_high_tx_power",
    "Gss": "gps_signal_quality",
    "nrs": "nr_state",
    "Bs": "status",
    "Bh": "health",
    "Bp": "plug",
    "Bt": "temp",
    "Bv": "volt",
    "Bcc": "charge",
    "Mrc": "modemRailChargemAh",
    "Wrc": "wifiRailChargemAh",
    "wr": "wake_reason",
    "Enl": "null",
    "Epr": "proc",
    "Efg": "fg",
    "Etp": "top",
    "Esy": "sync",
    "Ewl": "wake_lock_in",
    "Ejb": "job",
    "Eur": "user",
    "Euf": "userfg",
    "Ecn": "conn",
    "Eac": "active",
    "Epi": "pkginst",
    "Epu": "pkgunin",
    "Eal": "alarm",
    "Est": "stats",
    "Eai": "pkginactive",
    "Eaa": "pkgactive",
    "Etw": "tmpwhitelist",
    "Esw": "screenwake",
    "Ewa": "wakeupap",
    "Elw": "longwake",
    "Eec": "est_capacity",
    "Esc": "state",
}
_CHECKIN_VALUES = {
    "status": {
        "?": "unknown",
        "c": "charging",
        "d": "discharging",
        "n": "not-charging",
        "f": "full",
    },
    "health": {
        "?": "unknown",
        "g": "good",
        "h": "overheat",
        "d": "dead",
        "v": "over-voltage",
        "f": "failure",
        "c": "cold",
    },
    "plug": {"n": "none", "a": "ac", "u": "usb", "w": "wireless"},
    "phone_signal_strength": dict(
        enumerate(("none", "poor", "moderate", "good", "great")),
    ),
    "brightness": dict(enumerate(("dark", "dim", "medium", "light", "bright"))),
    "wifi_suppl": {
        "inv": "invalid",
        "dsc": "disconnected",
        "dis": "interface_disabled",
        "inact": "inactive",
        "scan": "scanning",
        "auth": "authenticating",
        "ascing": "associating",
        "asced": "associated",
        "4-way": "4-way_handshake",
        "group": "group_handshake",
        "compl": "completed",
        "dorm": "dormant",
        "uninit": "uninitialized",
    },
}
# Checkin tokens whose value is an index into the 9,hsp string pool.
_POOLED = frozenset({"wake_lock", "wake_reason"}) | {
    name for code, name in _CHECKIN_NAMES.items() if code.startswith("E")
}
_CHECKIN_TOKEN_RE = re.compile(r"^([+-]?)([A-Za-z]+)(?:=(.*))?$")
_CHECKIN_POOL_RE = re.compile(r'^\d+,hsp,(\d+),(-?\d+),"(.*)"$')
_CHECKIN_HISTORY_RE = re.compile(r"^\d+,h,(.*)$")
_CHECKIN_DETAIL_PREFIXES = ("Dcpu=", "Dpst=")

_TEXT_HISTORY_RE = re.compile(r"^Battery History \(")
_TEXT_RECORD_RE = re.compile(
    r"^\s+(?:(?P<sign>[+-])(?P<dur>(?:\d+d)?(?:\d+h)?(?:\d+m)?(?:\d+s)?(?:\d+ms)?)"
    r"|0)\s+\(\d+\)\s+(?P<rest>.*)$",
)
_TEXT_COMMAND_RE = re.compile(
    r"^(?P<cmd>RESET:TIME|TIME|START|SHUTDOWN|\*OVERFLOW\*)"
    r"(?::\s*(?P<clock>\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d))?",
)
_TEXT_LEVEL_RE = re.compile(r"^(?P<level>\d{1,3})(?:\s+(?P<tokens>.*))?$")
_TEXT_TOKEN_RE = re.compile(
    r'(?P<sign>[+-]?)(?P<name>[A-Za-z_]\w*)(?:=(?:(?P<uid>-?\w+):(?="))?'
    r'(?P<value>"[^"]*"|\S+))?',
)


def _command_name(raw: str) -> str:
    """Map ``RESET:TIME`` or ``*OVERFLOW*`` to RESET, TIME, START, SHUTDOWN..."""
    if raw.startswith("RESET"):
        return "RESET"
    return raw.strip("*")


class _CheckinParser:
    """State of one pass over checkin rows: string pool, time and level."""

    def __init__(self, text: Text, clock: LocalClock) -> None:
        self.history = History(text, "checkin", [], clock.source)
        self.local = clock.local
        self.pool: dict[str, tuple[str, str]] = {}
        self.t = 0
        self.prev_t: int | None = None
        self.level: int | None = None

    def line(self, index: int, line: str) -> None:
        if m := _CHECKIN_POOL_RE.match(line):
            tag = m[3].replace('\\"', '"').replace("\\\\", "\\")
            self.pool[m[1]] = (m[2], tag)
            return
        if m := _CHECKIN_HISTORY_RE.match(line):
            self.record(index, m[1])

    def record(self, index: int, body: str) -> None:
        history = self.history
        head, _, rest = body.partition(",")
        delta_text, _, command = head.partition(":")
        if rest.startswith(_CHECKIN_DETAIL_PREFIXES):
            history.continuation_lines += 1
            return
        try:
            self.t += int(delta_text)
        except ValueError:
            history.unparsed_lines += 1
            return
        _note_step(history, self.prev_t, self.t)
        self.prev_t = self.t
        record = Record(index=index, t_ms=self.t)
        if command:
            parts = command.split(":")
            record.command = _command_name(parts[0])
            if record.command in {"RESET", "TIME"} and parts[-1].isdigit():
                record.clock = self.local(int(parts[-1]) / 1000)
                if record.clock is not None:
                    history.anchors.append((len(history.records), self.t, record.clock))
        else:
            record.tokens = tuple(self.tokens(rest))
            record.level = self.level
        history.records.append(record)

    def tokens(self, rest: str) -> Iterator[Token]:
        for piece in rest.split(",") if rest else ():
            token, new_level = _checkin_token(piece, self.pool)
            if new_level is not None:
                self.level = new_level
            elif token is not None:
                yield token
            else:
                self.history.unparsed_lines += 1


def parse_checkin_history(text: Text, clock: LocalClock) -> History | None:
    """Parse the ``9,h,`` rows of checkin output into a :class:`History`.

    Each row is ``9,h,<delta ms>[,token...]``; ``<delta>:RESET:TIME:<epoch ms>``
    and ``<delta>:TIME:<epoch ms>`` anchor the wall clock, ``:START``,
    ``:SHUTDOWN`` and ``:*OVERFLOW*`` mark reboots and lost records. Pooled
    tokens (``w=``, ``wr=``, events) index the ``9,hsp,<idx>,<uid>,"<tag>"``
    string pool.
    """
    parser = _CheckinParser(text, clock)
    for index, line in enumerate(text.lines):
        parser.line(index, line)
    return parser.history if parser.history.records else None


def _checkin_token(
    piece: str,
    pool: dict[str, tuple[str, str]],
) -> tuple[Token | None, int | None]:
    """Decode one checkin history token; return (token, new level)."""
    m = _CHECKIN_TOKEN_RE.match(piece)
    if not m:
        return None, None
    sign, code, value = m[1], m[2], m[3]
    if code == "Bl":
        return None, int(value) if value and value.isdigit() else None
    name = _CHECKIN_NAMES.get(code, code)
    uid = None
    if value is not None and name in _POOLED and value in pool:
        uid, value = pool[value]
    elif value is not None and name in _CHECKIN_VALUES:
        table: dict[Any, str] = _CHECKIN_VALUES[name]
        key: Any = int(value) if value.isdigit() and name in _NUMERIC_CODED else value
        value = table.get(key, value)
    return Token(sign, name, value, uid), None


_NUMERIC_CODED = frozenset({"phone_signal_strength", "brightness"})


def parse_text_history(text: Text) -> History | None:
    """Parse the "Battery History" block of the full batterystats text dump.

    Records look like ``+1h05m05s381ms (2) 097 +running wake_reason=0:"..."``
    with a cumulative offset; ``RESET:TIME: 2026-01-15-07-21-20`` and
    ``TIME: ...`` lines carry local wall time. Indented lines that are not
    records (``Details: cpu=...``) are counted and skipped.
    """
    start = next(
        (i for i, line in enumerate(text.lines) if _TEXT_HISTORY_RE.match(line)),
        None,
    )
    if start is None:
        return None
    history = History(text, "text", [], "local wall time printed in the dump")
    prev_t: int | None = None
    level: int | None = None
    for index in range(start + 1, len(text.lines)):
        line = text.lines[index]
        if not line.strip():
            continue
        if not line[0].isspace():
            break
        m = _TEXT_RECORD_RE.match(line)
        if not m:
            history.continuation_lines += 1
            continue
        try:
            t = parse_duration_ms(m["sign"] + m["dur"]) if m["sign"] else 0
        except ValueError:
            history.unparsed_lines += 1
            continue
        _note_step(history, prev_t, t)
        prev_t = t
        record = Record(index=index, t_ms=t)
        rest = m["rest"]
        if cm := _TEXT_COMMAND_RE.match(rest):
            record.command = _command_name(cm["cmd"])
            if cm["clock"]:
                record.clock = datetime.strptime(cm["clock"], "%Y-%m-%d-%H-%M-%S")
                history.anchors.append((len(history.records), t, record.clock))
            history.records.append(record)
            continue
        lm = _TEXT_LEVEL_RE.match(rest)
        if not lm:
            history.unparsed_lines += 1
            continue
        level = int(lm["level"])
        record.level = level
        record.tokens = tuple(_text_tokens(lm["tokens"] or ""))
        history.records.append(record)
    return history if history.records else None


def _text_tokens(rest: str) -> Iterator[Token]:
    for m in _TEXT_TOKEN_RE.finditer(rest):
        value = m["value"]
        if value is not None and value.startswith('"'):
            value = value[1:-1]
        yield Token(m["sign"], m["name"], value, m["uid"])


def _note_step(history: History, prev_t: int | None, t: int) -> None:
    """Count backward time steps; batterystats timestamps are not monotonic."""
    if prev_t is not None and t < prev_t:
        history.backward_steps += 1
        history.max_backward_ms = max(history.max_backward_ms, prev_t - t)


# ---------------------------------------------------------------------------
# Wall clock and per-run loaders


class LocalClock(NamedTuple):
    """Converts Unix seconds to the phone's naive local time; ``source`` says how."""

    local: Callable[[float], datetime | None]
    source: str


# Derived UTC offsets are rounded to this granularity.
_OFFSET_STEP_S = 15 * 60
# A derived offset must land this close to a whole step to be trusted.
_OFFSET_SLACK_S = 60


def local_clock(ctx: Context) -> LocalClock:
    """Return the phone's epoch-to-local-time conversion and its source.

    The time zone and capture offset come from ``ctx.windows``; without them
    the offset is derived from the checkin start clock, else times are UTC.
    """
    windows = ctx.windows
    if windows.zone is not None:
        return LocalClock(
            windows.local_from_epoch, f"time zone {windows.zone} (getprop)"
        )
    if windows.offset() is not None:
        return LocalClock(windows.local_from_epoch, f"UTC offset {windows.utc_offset}")
    derived = _derived_offset(ctx)
    zone = UTC if derived is None else timezone(derived)

    def local(epoch_s: float) -> datetime | None:
        try:
            return datetime.fromtimestamp(epoch_s, tz=zone).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None

    if derived is None:
        return LocalClock(local, "UTC (no time zone found; epoch times shown in UTC)")
    return LocalClock(local, "UTC offset derived from the since-charge start time")


def _derived_offset(ctx: Context) -> timedelta | None:
    """Compare the checkin start clock (epoch) with the printed local start."""
    start = ctx.windows.since_charge_start
    rows = checkin_rows(ctx).get("bt", [])
    if start is None or not rows:
        return None
    epoch_ms = _int(rows[0][1], BT_START_CLOCK)
    try:
        utc = datetime.fromtimestamp((epoch_ms or 0) / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    if not epoch_ms:
        return None
    utc = utc.replace(tzinfo=None)
    diff = (start - utc).total_seconds()
    rounded = round(diff / _OFFSET_STEP_S) * _OFFSET_STEP_S
    if abs(diff - rounded) <= _OFFSET_SLACK_S:
        return timedelta(seconds=rounded)
    return None


def load_history(ctx: Context) -> History | None:
    """Return the battery history: checkin rows first, the text dump second."""

    def build() -> History | None:
        checkin = ctx.sources.get("batterystats_checkin")
        if checkin is not None and (
            history := parse_checkin_history(checkin, local_clock(ctx))
        ):
            return history
        text = ctx.sources.get("batterystats")
        return parse_text_history(text) if text is not None else None

    return ctx.sources.memo("battery_history", build)


# ---------------------------------------------------------------------------
# Timeline: replay the history into spans, resumes and time integrals


@dataclass
class Resume:
    """The SoC leaving suspend (``+running``) with the screen off on battery."""

    pos: int
    t_ms: int
    reason: str | None = None
    awake_ms: int | None = None  # until the next -running in the same span
    asleep_before_ms: int | None = None  # since the previous -running


@dataclass
class Span:
    """A stretch with the screen off and the phone on battery."""

    start_pos: int
    t0: int
    level0: int | None
    end_pos: int = -1
    level1: int | None = None
    ended_by: str = ""
    total_ms: int = 0
    awake_ms: int = 0
    wakelock_ms: int = 0
    kernel_awake_ms: int = 0  # running without any Android wakelock
    idle_full_ms: int = 0
    idle_light_ms: int = 0
    radio_ms: int = 0
    doze_ms: int = 0  # screen in doze (always-on display)
    resumes: list[Resume] = field(default_factory=list)
    aborts: Counter[str] = field(default_factory=Counter)


_CLASSES = (
    "plugged",
    "screen_on",
    "screen_off_idle_off",
    "screen_off_idle_light",
    "screen_off_idle_full",
)


@dataclass
class Timeline:
    """Everything derived from one replay of the history."""

    history: History
    spans: list[Span] = field(default_factory=list)
    battery_ms: int = 0
    plug_ins: list[int] = field(default_factory=list)  # record positions
    unplugs: list[int] = field(default_factory=list)
    charges: list[tuple[int, int, int | None, bool]] = field(default_factory=list)
    markers: list[tuple[int, str]] = field(default_factory=list)
    # class -> [total ms, running ms, wakelock ms, +running count]
    classes: dict[str, list[int]] = field(
        default_factory=lambda: {c: [0, 0, 0, 0] for c in _CLASSES},
    )
    # local hour -> [screen-off ms, awake ms, deep idle ms, resumes]
    hours: dict[datetime, list[int]] = field(default_factory=dict)
    plugged_at_end: bool = False
    has_reset: bool = False

    @property
    def resumes(self) -> list[Resume]:
        """All screen-off resumes on battery, in history order."""
        return [r for s in self.spans for r in s.resumes]


# batterystats counts screen doze (always-on display) as screen off: its
# screen-off time base runs whenever the display is not in an "on" state
# (AOSP BatteryStatsImpl.noteScreenStateLocked, Display.isOnState), and doze
# sets only the screen_doze flag, never screen.
def _screen_off_on_battery(flags: set[str]) -> bool:
    return not flags & {"plugged", "screen"}


def _class_of(flags: set[str], values: dict[str, str]) -> str:
    if "plugged" in flags:
        return "plugged"
    if "screen" in flags:
        return "screen_on"
    idle = values.get("device_idle", "off")
    return f"screen_off_idle_{idle if idle in {'light', 'full'} else 'off'}"


def _split_hours(start: datetime, ms: int) -> Iterator[tuple[datetime, int]]:
    """Split ``ms`` starting at ``start`` at local hour boundaries."""
    while ms > 0:
        hour = start.replace(minute=0, second=0, microsecond=0)
        room = int((hour + timedelta(hours=1) - start).total_seconds() * 1000)
        part = min(ms, max(room, 1))
        yield hour, part
        start += timedelta(milliseconds=part)
        ms -= part


def _add_to_span(span: Span, flags: set[str], idle: str | None, dt: int) -> None:
    """Add ``dt`` ms in state ``flags``/``idle`` to the span's integrals."""
    running = "running" in flags
    wakelock = "wake_lock" in flags
    span.total_ms += dt
    span.awake_ms += dt if running else 0
    span.kernel_awake_ms += dt if running and not wakelock else 0
    span.wakelock_ms += dt if wakelock else 0
    span.idle_full_ms += dt if idle == "full" else 0
    span.idle_light_ms += dt if idle == "light" else 0
    span.radio_ms += dt if "mobile_radio" in flags else 0
    span.doze_ms += dt if "screen_doze" in flags else 0


class _Replay:
    """Mutable state of one pass over the history records."""

    def __init__(self, history: History) -> None:
        self.tl = Timeline(history)
        self.flags: set[str] = set()
        self.values: dict[str, str] = {}
        self.known = False  # True once a full-state record has been applied
        self.level: int | None = None
        self.span: Span | None = None
        self.last_resume: Resume | None = None
        self.run_resume: Resume | None = None
        self.last_down: int | None = None
        self.anchor: tuple[int, datetime] | None = None
        self.charge: int | None = None

    def wall(self, t: int) -> datetime | None:
        if self.anchor is None:
            return None
        return self.anchor[1] + timedelta(milliseconds=t - self.anchor[0])

    def accumulate(self, t0: int, dt: int) -> None:
        """Add the interval starting at ``t0`` to the integrals of the state."""
        flags = self.flags
        running = "running" in flags
        cls = self.tl.classes[_class_of(flags, self.values)]
        cls[0] += dt
        cls[1] += dt if running else 0
        cls[2] += dt if "wake_lock" in flags else 0
        if "plugged" not in flags:
            self.tl.battery_ms += dt
        if self.span is None:
            return
        idle = self.values.get("device_idle")
        _add_to_span(self.span, flags, idle, dt)
        start = self.wall(t0)
        if start is None or dt <= 0:
            return
        for hour, part in _split_hours(start, dt):
            row = self.tl.hours.setdefault(hour, [0, 0, 0, 0])
            row[0] += part
            row[1] += part if running else 0
            row[2] += part if idle == "full" else 0

    def open_span(self, pos: int, t: int) -> None:
        self.span = Span(start_pos=pos, t0=t, level0=self.level)
        self.run_resume = None
        self.last_down = None

    def close_span(self, pos: int, reason: str) -> None:
        span = self.span
        if span is None:
            return
        span.end_pos, span.level1, span.ended_by = pos, self.level, reason
        self.tl.spans.append(span)
        self.span = None
        self.run_resume = None
        self.last_down = None

    def command(self, pos: int, record: Record) -> None:
        self.tl.markers.append((pos, record.command))
        if record.command == "RESET":
            self.tl.has_reset = True
        if record.command in {"RESET", "START", "SHUTDOWN"}:
            self.close_span(pos, record.command.lower())
        if record.command in {"RESET", "START"}:
            # The printer restarts from an empty state: the next record
            # carries the full state again.
            self.flags.clear()
            self.values.clear()
            self.known = False

    def apply(self, pos: int, record: Record) -> None:
        """Apply one data record."""
        flags = self.flags
        running_before = "running" in flags
        plugged_before = "plugged" in flags
        in_span_before = self.known and _screen_off_on_battery(flags)
        # The record's own level goes with its charge sample.
        if record.level is not None:
            self.level = record.level
        reasons = self.apply_tokens(pos, record)
        # The first record after RESET/START restates the whole state: its
        # +running is not a resume.
        resumed = (
            self.known
            and not running_before
            and "running" in flags
            and any(tok.sign == "+" and tok.name == "running" for tok in record.tokens)
        )
        was_known, self.known = self.known, True
        in_span_after = _screen_off_on_battery(flags)
        plugged_after = "plugged" in flags
        t = record.t_ms
        if was_known and plugged_after != plugged_before:
            (self.tl.plug_ins if plugged_after else self.tl.unplugs).append(pos)
        if in_span_before and not in_span_after:
            self.close_span(pos, "plug" if plugged_after else "screen")
        elif in_span_after and (not in_span_before or self.span is None):
            self.open_span(pos, t)
        self.note_wake(pos, t, resumed=resumed, reasons=reasons)
        if running_before and "running" not in flags:
            self.note_sleep(t, in_span_before=in_span_before)

    def apply_tokens(self, pos: int, record: Record) -> list[str]:
        """Apply the state changes of ``record``; return its wake reasons."""
        reasons: list[str] = []
        for token in record.tokens:
            if token.sign == "+":
                self.flags.add(token.name)
            elif token.sign == "-":
                self.flags.discard(token.name)
            elif token.value is not None:
                self.values[token.name] = token.value
            if token.name == "wake_reason" and token.value:
                reasons.append(token.value)
            elif token.name == "charge" and not token.sign and token.value:
                self.note_charge(pos, token.value)
        return reasons

    def note_sleep(self, t: int, *, in_span_before: bool) -> None:
        """Close the current awake run at a ``-running`` record."""
        if self.span is not None and in_span_before:
            if self.run_resume is not None:
                self.run_resume.awake_ms = t - self.run_resume.t_ms
            self.last_down = t
        self.run_resume = None

    def note_wake(self, pos: int, t: int, *, resumed: bool, reasons: list[str]) -> None:
        span = self.span
        cls = self.tl.classes[_class_of(self.flags, self.values)]
        cls[3] += 1 if resumed else 0
        if span is None:
            if resumed:
                self.run_resume = None
            return
        real = [r for r in reasons if not r.startswith("Abort")]
        span.aborts.update(r for r in reasons if r.startswith("Abort"))
        if resumed:
            resume = Resume(pos, t, real[0] if real else None)
            if self.last_down is not None:
                resume.asleep_before_ms = t - self.last_down
            span.resumes.append(resume)
            self.last_resume = self.run_resume = resume
            wall = self.wall(t)
            if wall is not None:
                hour = wall.replace(minute=0, second=0, microsecond=0)
                self.tl.hours.setdefault(hour, [0, 0, 0, 0])[3] += 1
        elif (
            real
            and (last := self.last_resume) is not None
            and last.reason is None
            and abs(t - last.t_ms) <= REASON_ATTACH_MS
        ):
            last.reason = real[0]

    def note_charge(self, pos: int, value: str) -> None:
        try:
            charge = int(value)
        except ValueError:
            return
        if charge != self.charge:
            self.charge = charge
            self.tl.charges.append((pos, charge, self.level, self.span is not None))


def build_timeline(history: History) -> Timeline:
    """Replay ``history`` in record order into spans, resumes and integrals.

    Intervals use the state in force after the previous record, in file order;
    the occasional backward time step makes an interval negative, which keeps
    the sums exact (they telescope to last minus first time).
    """
    replay = _Replay(history)
    prev_t: int | None = None
    for pos, record in enumerate(history.records):
        t = record.t_ms
        if replay.known and prev_t is not None and t != prev_t:
            replay.accumulate(prev_t, t - prev_t)
        prev_t = t
        if record.clock is not None:
            replay.anchor = (t, record.clock)
        if record.command:
            replay.command(pos, record)
        else:
            replay.apply(pos, record)
    if replay.span is not None and history.records:
        last = len(history.records) - 1
        replay.close_span(last, "end")
    replay.tl.plugged_at_end = replay.known and "plugged" in replay.flags
    return replay.tl


def load_timeline(ctx: Context) -> Timeline | None:
    """Return the timeline of the battery history (built once per run), or None."""

    def build() -> Timeline | None:
        history = load_history(ctx)
        return build_timeline(history) if history else None

    return ctx.sources.memo("battery_timeline", build)


def _require_timeline(ctx: Context) -> Timeline:
    timeline = load_timeline(ctx)
    if timeline is None:
        msg = "no battery history (batterystats checkin rows or text history)"
        raise SkipError(msg)
    return timeline


# ---------------------------------------------------------------------------
# Small helpers


def _r(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _quantile(sorted_values: list[float], q: float) -> float | None:
    """Nearest-rank quantile of an already sorted list."""
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def _iso(stamp: datetime | None) -> str | None:
    return stamp.isoformat(sep=" ", timespec="seconds") if stamp else None


# ---------------------------------------------------------------------------
# Checkin rows and the since-charge text summary

_CHECKIN_ROW_RE = re.compile(r"^\d+,(-?\d+),([il]),([A-Za-z]+),")
_PER_UID_TYPES = frozenset({"pwi", "nt", "cpu", "wl", "pr", "uid"})


def checkin_rows(
    ctx: Context,
    key: str = "batterystats_checkin",
) -> dict[str, list[tuple[int, list[str]]]]:
    """Return ``{row type: [(line index, fields)]}`` for the checkin rows of ``key``.

    Fields exclude the version, UID, category and type columns; the UID is
    prepended as the first field for per-UID types such as ``pwi`` or ``nt``.
    Quoted names (``kwl``, ``wr``) may contain commas, so rows go through csv.
    Empty when ``key`` is missing; parsed once per run.
    """

    def build() -> dict[str, list[tuple[int, list[str]]]]:
        rows: dict[str, list[tuple[int, list[str]]]] = {}
        text = ctx.sources.get(key)
        for index, line in enumerate(text.lines if text else ()):
            m = _CHECKIN_ROW_RE.match(line)
            if not m:
                continue
            fields = next(csv.reader([line]))[4:]
            if m[3] in _PER_UID_TYPES:
                fields = [m[1], *fields]
            rows.setdefault(m[3], []).append((index, fields))
        return rows

    return ctx.sources.memo(f"checkin_rows:{key}", build)


def _int(fields: list[str], i: int) -> int | None:
    try:
        return int(fields[i])
    except (IndexError, ValueError):
        return None


def _float(fields: list[str], i: int) -> float | None:
    try:
        return float(fields[i])
    except (IndexError, ValueError):
        return None


@dataclass
class CheckinPeriod:
    """The since-charge totals of one checkin dump (bt, dc, m, pws rows)."""

    text: Text
    rows: dict[str, list[tuple[int, list[str]]]]

    def row(self, kind: str) -> tuple[int, list[str]] | None:
        """Return the first row of ``kind`` (the device-wide one)."""
        found = self.rows.get(kind)
        return found[0] if found else None

    def value(self, kind: str, i: int) -> int | None:
        """Return integer field ``i`` of row ``kind``."""
        row = self.row(kind)
        return _int(row[1], i) if row else None


# bt = [startCount, batteryRealtime, batteryUptime, totalRealtime, totalUptime,
#  startClockTime, screenOffRealtime, screenOffUptime, estimatedCapacity mAh,
#  minLearned uAh, maxLearned uAh, screenDoze]  (all times in ms)
BT_ON_BATTERY, BT_ON_BATTERY_UP, BT_TOTAL_REALTIME = 1, 2, 3
BT_START_CLOCK, BT_SCREEN_OFF, BT_SCREEN_OFF_UP = 5, 6, 7
BT_ESTIMATED, BT_MIN_LEARNED, BT_MAX_LEARNED, BT_SCREEN_DOZE = 8, 9, 10, 11
# dc = [low %, high %, screenOn %, screenOff %, mAh, screenOff mAh,
#  screenDoze %, screenDoze mAh, lightDoze mAh, deepDoze mAh]
DC_LOW, DC_HIGH, DC_SCREEN_ON_PCT, DC_SCREEN_OFF_PCT = 0, 1, 2, 3
DC_MAH, DC_SCREEN_OFF_MAH, DC_DOZE_PCT, DC_DOZE_MAH = 4, 5, 6, 7
DC_LIGHT_MAH, DC_DEEP_MAH = 8, 9
# m = [screenOn, phoneOn, fullWakelock, partialWakelock, mobileRadioActive,
#  mobileRadioActiveAdjusted, interactive, powerSaveEnabled,
#  connectivityChanges, idleModeFull, idleModeFullCount, deviceIdlingFull,
#  deviceIdlingFullCount, mobileRadioActiveCount, mobileRadioActiveUnknown,
#  idleModeLight, count, deviceIdlingLight, count, longestLight, longestFull]
M_SCREEN_ON, M_PARTIAL_WL, M_RADIO_ACTIVE, M_POWER_SAVE = 0, 3, 4, 7
M_CONN_CHANGES, M_IDLE_FULL, M_DEVICE_IDLING_FULL = 8, 9, 11
M_RADIO_COUNT, M_DEVICE_IDLING_LIGHT = 13, 17
# pws = [capacity, computed drain, min drain, max drain]
PWS_CAPACITY, PWS_COMPUTED, PWS_MIN, PWS_MAX = 0, 1, 2, 3


# Since-charge summary labels (batterystats.SinceCharge headers) by value name.
_SC_MAH = {
    "discharge_mah": "Discharge",
    "screen_off_mah": "Screen off discharge",
    "screen_doze_mah": "Screen doze discharge",
    "screen_on_mah": "Screen on discharge",
    "light_doze_mah": "Device light doze discharge",
    "deep_doze_mah": "Device deep doze discharge",
}
_SC_COUNTS = {
    "level_lower": "Amount discharged (lower bound)",
    "level_upper": "Amount discharged (upper bound)",
    "level_screen_on": "Amount discharged while screen on",
    "level_screen_off": "Amount discharged while screen off",
    "connectivity_changes": "Connectivity changes",
}
_SC_TIMES = {
    "on_battery": "Time on battery",
    "screen_off": "Time on battery screen off",
    "screen_doze": "Time on battery screen doze",
    "power_save": "Power save mode enabled",
    "device_full_idling": "Device full idling",
    "device_light_idling": "Device light idling",
    "idle_mode_full": "Idle mode full time",
}
_SCREEN_ON = "Screen on"
_LEADING_INT_RE = re.compile(r"^(\d+)")
_TIMES_COUNT_RE = re.compile(r"\)\s+(\d+)x")


def _header_int(since: SinceCharge, label: str) -> int | None:
    """Return the leading integer of a line such as ``Connectivity changes: 12``."""
    found = since.header(label)
    m = _LEADING_INT_RE.match(found[0]) if found else None
    return int(m[1]) if m else None


def load_checkin_period(
    ctx: Context, key: str = "batterystats_checkin"
) -> CheckinPeriod | None:
    """Return the checkin totals of ``key`` if it has a ``bt`` row."""
    text = ctx.sources.get(key)
    rows = checkin_rows(ctx, key)
    return CheckinPeriod(text, rows) if text and "bt" in rows else None


# ---------------------------------------------------------------------------
# Capacity facts shared by several analyzers

_HAL_PATTERNS = {
    "full_charge_uah": re.compile(
        r"(?:^Full charge: |batteryFullCharge(?:Uah)?\s*[=:]\s*)(\d+)",
    ),
    "design_uah": re.compile(r"batteryFullChargeDesignCapacityUah\s*[=:]\s*(\d+)"),
    "cycle_count": re.compile(r"(?:^cycle count: |batteryCycleCount\s*[=:]\s*)(\d+)"),
    "charge_counter_uah": re.compile(
        r"(?:^charge counter: |batteryChargeCounter(?:Uah)?\s*[=:]\s*)(\d+)",
    ),
    "level": re.compile(r"(?:^level: |batteryLevel\s*[=:]\s*)(\d+)"),
    "health": re.compile(r"batteryHealth\s*[=:]\s*(\w+)"),
}
_POWER_PROFILE_CAPACITY_RE = re.compile(r"battery\.capacity\W+([\d.]+)")
_HEALTHD_RE = re.compile(r"healthd: battery l=(\d+) .*?fc=(\d+) cc=(\d+)")
_BATTERY_COUNTER_RE = re.compile(r"^\s+Charge counter: (\d+)")
_BATTERY_LEVEL_RE = re.compile(r"^\s+level: (\d+)")
_FIRST_INSTALL_RE = re.compile(r"firstInstallTime=(\d{4})-(\d\d)-(\d\d)")


@dataclass
class CapacityFacts:
    """Learned and design capacity, cycle count and where each came from."""

    learned_mah: float | None = None
    learned_source: str = ""
    design_mah: float | None = None
    design_source: str = ""
    hal_design_mah: float | None = None
    profile_design_mah: float | None = None
    cycle_count: int | None = None
    cycle_source: str = ""
    hal_health: str | None = None
    min_learned_mah: float | None = None
    max_learned_mah: float | None = None
    estimated_mah: float | None = None
    live_counter_uah: int | None = None
    live_level: int | None = None
    live_source: str = ""
    evidence: list[Evidence] = field(default_factory=list)


def _hal_values(text: Text) -> dict[str, tuple[str, int]]:
    found: dict[str, tuple[str, int]] = {}
    for index, line in enumerate(text.lines):
        for key, regex in _HAL_PATTERNS.items():
            if key not in found and (m := regex.search(line.strip())):
                found[key] = (m[1], index)
    return found


def _build_capacity(ctx: Context) -> CapacityFacts:
    facts = CapacityFacts()
    hal = ctx.sources.get("health_hal") or ctx.sources.get("health_aidl")
    if hal is not None:
        _capacity_from_hal(facts, hal)
    since = load_since_charge(ctx)
    if since is not None:
        _capacity_from_since_charge(facts, since)
    period = load_checkin_period(ctx)
    if period is not None:
        _capacity_from_checkin(facts, period)
    _capacity_design(ctx, facts)
    if facts.learned_mah is None or facts.cycle_count is None:
        _capacity_from_dmesg(ctx, facts)
    if facts.live_counter_uah is None:
        _capacity_from_battery(ctx, facts)
    return facts


def _capacity_design(ctx: Context, facts: CapacityFacts) -> None:
    """Prefer the power profile's nominal capacity, else the HAL design value."""
    profile = ctx.sources.get("power_profile")
    if profile is not None:
        for i, m in profile.find(_POWER_PROFILE_CAPACITY_RE):
            facts.profile_design_mah = float(m[1])
            facts.evidence.append(profile.evidence(i))
            break
    if facts.profile_design_mah:
        facts.design_mah = facts.profile_design_mah
        facts.design_source = "power profile battery.capacity"
    elif facts.hal_design_mah:
        facts.design_mah = facts.hal_design_mah
        facts.design_source = "health HAL design capacity"


def _capacity_from_battery(ctx: Context, facts: CapacityFacts) -> None:
    """Read the live charge counter and level from ``dumpsys battery``."""
    battery = ctx.sources.get("battery")
    if battery is None:
        return
    counters = battery.find(_BATTERY_COUNTER_RE)
    levels = battery.find(_BATTERY_LEVEL_RE)
    if counters and levels:
        facts.live_counter_uah = int(counters[0][1][1])
        facts.live_level = int(levels[0][1][1])
        facts.live_source = "dumpsys battery"
        facts.evidence.append(battery.evidence(counters[0][0]))


def _capacity_from_hal(facts: CapacityFacts, hal: Text) -> None:
    values = _hal_values(hal)
    if "full_charge_uah" in values:
        raw, index = values["full_charge_uah"]
        facts.learned_mah = int(raw) / 1000
        facts.learned_source = "health HAL full charge"
        facts.evidence.append(hal.evidence(index))
    if "design_uah" in values:
        raw, index = values["design_uah"]
        facts.hal_design_mah = int(raw) / 1000
        facts.evidence.append(Evidence(hal.ref(index), f"design capacity {raw} uAh"))
    if "cycle_count" in values:
        raw, index = values["cycle_count"]
        facts.cycle_count = int(raw)
        facts.cycle_source = "health HAL"
        facts.evidence.append(hal.evidence(index))
    if "health" in values:
        facts.hal_health = values["health"][0]
    if "charge_counter_uah" in values and "level" in values:
        facts.live_counter_uah = int(values["charge_counter_uah"][0])
        facts.live_level = int(values["level"][0])
        facts.live_source = "health HAL"


def _capacity_from_since_charge(facts: CapacityFacts, since: SinceCharge) -> None:
    label = "Last learned battery capacity"
    if (learned := since.mah(label)) and facts.learned_mah is None:
        facts.learned_mah = learned
        facts.learned_source = "batterystats last learned capacity"
        facts.evidence += since.evidence(label)
    for label, attr in (
        ("Min learned battery capacity", "min_learned_mah"),
        ("Max learned battery capacity", "max_learned_mah"),
        ("Estimated battery capacity", "estimated_mah"),
    ):
        value = since.mah(label)
        if value is not None and getattr(facts, attr) is None:
            setattr(facts, attr, value)


def _capacity_from_checkin(facts: CapacityFacts, period: CheckinPeriod) -> None:
    max_learned = period.value("bt", BT_MAX_LEARNED)
    min_learned = period.value("bt", BT_MIN_LEARNED)
    if facts.learned_mah is None and max_learned:
        facts.learned_mah = max_learned / 1000
        facts.learned_source = "checkin max learned capacity"
    if facts.min_learned_mah is None and min_learned:
        facts.min_learned_mah = min_learned / 1000
    if facts.max_learned_mah is None and max_learned:
        facts.max_learned_mah = max_learned / 1000
    if facts.estimated_mah is None:
        estimated = period.value("bt", BT_ESTIMATED)
        facts.estimated_mah = float(estimated) if estimated else None


def _capacity_from_dmesg(ctx: Context, facts: CapacityFacts) -> None:
    dmesg = ctx.sources.get("dmesg")
    if dmesg is None:
        return
    for i, m in dmesg.find(_HEALTHD_RE):
        if facts.learned_mah is None and int(m[2]):
            facts.learned_mah = int(m[2]) / 1000
            facts.learned_source = "kernel healthd line (fc=)"
            facts.evidence.append(dmesg.evidence(i))
        if facts.cycle_count is None:
            facts.cycle_count = int(m[3])
            facts.cycle_source = "kernel healthd line (cc=)"
        return


def load_capacity(ctx: Context) -> CapacityFacts:
    """Return the capacity facts, gathered once per run."""
    return ctx.sources.memo("battery_capacity", lambda: _build_capacity(ctx))


# ---------------------------------------------------------------------------
# The battery_history analyzer


@analyzer("battery_history")
def battery_history(ctx: Context) -> Result:
    """Parse the history, check it against the summary and set ``plugged_at``."""
    timeline = _require_timeline(ctx)
    history = timeline.history
    result = Result("battery_history", window="since_charge")
    records = history.records
    screen_off_ms = sum(s.total_ms for s in timeline.spans)
    first_wall = history.wall(0)
    last_pos = len(records) - 1
    commands = Counter(cmd for _, cmd in timeline.markers)
    result.metrics = {
        "format": history.fmt,
        "source": history.text.origin,
        "records": sum(1 for r in records if not r.command),
        "continuation_lines": history.continuation_lines,
        "unparsed_lines": history.unparsed_lines,
        "backward_time_steps": history.backward_steps,
        "max_backward_step_ms": history.max_backward_ms,
        "has_reset": timeline.has_reset,
        "history_start": _iso(first_wall),
        "history_end": _iso(history.wall(last_pos)),
        "history_span_s": _r((records[-1].t_ms - records[0].t_ms) / 1000),
        "time_anchors": len(history.anchors),
        "clock_source": history.clock_source,
        "on_battery_s": _r(timeline.battery_ms / 1000),
        "screen_off_on_battery_s": _r(screen_off_ms / 1000),
        "screen_off_spans": len(timeline.spans),
        "plug_ins": len(timeline.plug_ins),
        "unplugs": len(timeline.unplugs),
        "plugged_at_end": timeline.plugged_at_end,
        "charge_samples": len(timeline.charges),
        "starts": commands.get("START", 0),
        "shutdowns": commands.get("SHUTDOWN", 0),
        "overflows": commands.get("OVERFLOW", 0),
    }
    _crosscheck(ctx, timeline, result, screen_off_ms)
    _set_plugged_at(ctx, timeline, result)
    result.add_table(
        "screen_off_spans", [_span_row(history, s) for s in timeline.spans]
    )
    result.add_table(
        "markers",
        [
            {
                "event": cmd,
                "time": _iso(history.wall(pos)),
                "ref": history.text.ref(records[pos].index),
            }
            for pos, cmd in timeline.markers
            if cmd != "TIME"
        ],
    )
    result.add_table(
        "charge_series",
        [
            {
                "time": _iso(history.wall(pos)),
                "charge_mah": charge,
                "level": level,
                "screen_off_on_battery": off,
                "ref": history.text.ref(records[pos].index),
            }
            for pos, charge, level, off in timeline.charges
        ],
    )
    if history.continuation_lines:
        result.notes.append(
            f"Skipped {history.continuation_lines} continuation lines "
            "(Details/proc stat rows) inside the history.",
        )
    if history.unparsed_lines:
        result.notes.append(f"Could not parse {history.unparsed_lines} history lines.")
    if history.backward_steps:
        result.notes.append(
            f"{history.backward_steps} records step back in time (largest "
            f"{history.max_backward_ms} ms); intervals are taken in file order.",
        )
    _history_quality_findings(timeline, result)
    return result


def _span_row(history: History, span: Span) -> dict[str, Any]:
    return {
        "start": _iso(history.wall(span.start_pos)),
        "end": _iso(history.wall(span.end_pos)),
        "duration_min": _r(span.total_ms / 60_000),
        "level_start": span.level0,
        "level_end": span.level1,
        "awake_pct": pct(span.awake_ms, span.total_ms),
        "resumes": len(span.resumes),
        "resumes_per_h": per_hour(len(span.resumes), span.total_ms / 1000),
        "deep_idle_min": _r(span.idle_full_ms / 60_000),
        "ended_by": span.ended_by,
        "ref": history.text.ref(history.records[span.start_pos].index),
    }


# Agreement between history replay and the summary counters, in seconds.
_CROSSCHECK_TOLERANCE_S = 60


def _crosscheck(
    ctx: Context,
    timeline: Timeline,
    result: Result,
    screen_off_ms: int,
) -> None:
    windows = ctx.windows
    for metric, mine, theirs in (
        ("on_battery", timeline.battery_ms / 1000, windows.on_battery_s),
        (
            "screen_off_on_battery",
            screen_off_ms / 1000,
            windows.screen_off_on_battery_s,
        ),
    ):
        if theirs is None:
            continue
        diff = mine - theirs
        result.metrics[f"{metric}_vs_summary_s"] = _r(diff)
        if abs(diff) > _CROSSCHECK_TOLERANCE_S:
            result.notes.append(
                f"History {metric.replace('_', ' ')} time differs from the "
                f"batterystats summary by {diff:+.0f} s; the history may start "
                "late, contain a reboot, or come from a different capture time.",
            )


def _set_plugged_at(ctx: Context, timeline: Timeline, result: Result) -> None:
    """Fill ``ctx.windows.plugged_at`` when the history ends plugged in."""
    if not timeline.plugged_at_end or not timeline.plug_ins:
        return
    if ctx.windows.on_battery_at_capture:
        return
    pos = timeline.plug_ins[-1]
    stamp = timeline.history.wall(pos)
    result.metrics["plugged_at"] = _iso(stamp)
    if stamp is not None and ctx.windows.plugged_at is None:
        ctx.windows.plugged_at = stamp
        result.notes.append(
            f"Set windows.plugged_at to {_iso(stamp)} from the history plug-in record.",
        )


def _history_quality_findings(timeline: Timeline, result: Result) -> None:
    history = timeline.history
    if not timeline.has_reset:
        result.findings.append(
            Finding(
                id="battery_history.starts_after_reset",
                title="Battery history starts after the last charge",
                symptom="info",
                severity="info",
                basis="measured",
                window="since_charge",
                summary=(
                    "The history has no RESET record: its buffer begins part way "
                    "through the period, so history-based totals cover only "
                    f"the last {fmt_duration(timeline.battery_ms / 1000)} on battery."
                ),
                evidence=[history.evidence(0)],
                recommendation=(
                    "Use the since-charge summary for totals; collect sooner after "
                    "unplugging when the history is needed for the whole period."
                ),
            ),
        )
    overflows = [pos for pos, cmd in timeline.markers if cmd == "OVERFLOW"]
    if overflows:
        result.findings.append(
            Finding(
                id="battery_history.overflow",
                title="Battery history overflowed and lost records",
                symptom="info",
                severity="info",
                basis="measured",
                window="since_charge",
                summary=(
                    f"The history has {len(overflows)} *OVERFLOW* markers; counts "
                    "derived from it are lower bounds."
                ),
                evidence=[history.evidence(p) for p in overflows[:3]],
                recommendation="Treat history-derived counts as lower bounds.",
            ),
        )


# ---------------------------------------------------------------------------
# The standby_wake analyzer


# Wake reason table label for resumes without a recorded reason.
_NO_REASON = "(none on record)"


@dataclass
class _Standby:
    """Aggregated screen-off on-battery statistics."""

    total_ms: int
    awake_ms: int
    wakelock_ms: int
    kernel_ms: int
    idle_full_ms: int
    idle_light_ms: int
    radio_ms: int
    doze_ms: int
    resumes: list[Resume]
    intervals_s: list[float]
    awake_s: list[float]
    asleep_s: list[float]
    reasons: Counter[str]
    aborts: Counter[str]


def _standby_stats(timeline: Timeline) -> _Standby:
    spans = timeline.spans
    intervals: list[float] = []
    for span in spans:
        times = sorted(r.t_ms for r in span.resumes)
        intervals += [(b - a) / 1000 for a, b in pairwise(times)]
    resumes = timeline.resumes
    aborts: Counter[str] = Counter()
    for span in spans:
        aborts.update(span.aborts)
    return _Standby(
        total_ms=sum(s.total_ms for s in spans),
        awake_ms=sum(s.awake_ms for s in spans),
        wakelock_ms=sum(s.wakelock_ms for s in spans),
        kernel_ms=sum(s.kernel_awake_ms for s in spans),
        idle_full_ms=sum(s.idle_full_ms for s in spans),
        idle_light_ms=sum(s.idle_light_ms for s in spans),
        radio_ms=sum(s.radio_ms for s in spans),
        doze_ms=sum(s.doze_ms for s in spans),
        resumes=resumes,
        intervals_s=sorted(intervals),
        awake_s=sorted(r.awake_ms / 1000 for r in resumes if r.awake_ms is not None),
        asleep_s=sorted(
            r.asleep_before_ms / 1000 for r in resumes if r.asleep_before_ms is not None
        ),
        reasons=Counter(r.reason or _NO_REASON for r in resumes),
        aborts=aborts,
    )


_INTERVAL_BINS_S = (0, 1, 2, 3, 5, 8, 10, 15, 20, 25, 30, 45, 60)


@analyzer("standby_wake", after=("windows", "battery_history"))
def standby_wake(ctx: Context) -> Result:
    """Measure screen-off awake share, resumes, wake reasons and Doze states."""
    timeline = _require_timeline(ctx)
    if not timeline.spans:
        msg = "no screen-off time on battery in the battery history"
        raise SkipError(msg)
    stats = _standby_stats(timeline)
    result = Result("standby_wake", window="screen_off_on_battery")
    n = len(stats.resumes)
    total = stats.total_ms
    top_reason, top_count = (
        stats.reasons.most_common(1)[0] if stats.reasons else (None, 0)
    )
    result.metrics = {
        "screen_off_on_battery_s": _r(total / 1000),
        "screen_off_spans": len(timeline.spans),
        "awake_s": _r(stats.awake_ms / 1000),
        "awake_share_pct": pct(stats.awake_ms, total),
        "resumes": n,
        "resumes_per_h": per_hour(n, total / 1000),
        "resume_interval_mean_s": _r(statistics.fmean(stats.intervals_s), 3)
        if stats.intervals_s
        else None,
        "resume_interval_median_s": _r(_quantile(stats.intervals_s, 0.5), 3),
        "resume_interval_p10_s": _r(_quantile(stats.intervals_s, 0.1), 3),
        "resume_interval_p90_s": _r(_quantile(stats.intervals_s, 0.9), 3),
        "awake_per_resume_mean_s": _r(statistics.fmean(stats.awake_s), 3)
        if stats.awake_s
        else None,
        "awake_per_resume_median_s": _r(_quantile(stats.awake_s, 0.5), 3),
        "asleep_between_resumes_median_s": _r(_quantile(stats.asleep_s, 0.5), 3),
        "asleep_between_resumes_mean_s": _r(statistics.fmean(stats.asleep_s), 3)
        if stats.asleep_s
        else None,
        "top_wake_reason": top_reason,
        "top_wake_reason_share_pct": pct(top_count, n),
        "deep_idle_s": _r(stats.idle_full_ms / 1000),
        "deep_idle_share_pct": pct(stats.idle_full_ms, total),
        "light_idle_s": _r(stats.idle_light_ms / 1000),
        "wakelock_held_s": _r(stats.wakelock_ms / 1000),
        "awake_without_wakelock_s": _r(stats.kernel_ms / 1000),
        "awake_without_wakelock_share_pct": pct(stats.kernel_ms, stats.awake_ms),
        "mobile_radio_on_s": _r(stats.radio_ms / 1000),
        "screen_doze_s": _r(stats.doze_ms / 1000),
        "suspend_aborts_in_history": sum(stats.aborts.values()),
        "suspend_aborts_per_resume": _r(sum(stats.aborts.values()) / n, 2)
        if n
        else None,
    }
    longest = max(timeline.spans, key=lambda s: s.total_ms)
    result.metrics |= {
        "longest_span_s": _r(longest.total_ms / 1000),
        "longest_span_awake_share_pct": pct(longest.awake_ms, longest.total_ms),
        "longest_span_resumes_per_h": per_hour(
            len(longest.resumes),
            longest.total_ms / 1000,
        ),
    }
    since = load_since_charge(ctx)
    off = since.duration_s(_SC_TIMES["screen_off"]) if since else None
    if off and off[1] is not None:
        result.metrics["summary_screen_off_awake_share_pct"] = pct(off[1], off[0])
    _standby_tables(timeline, stats, result)
    if timeline.history.clock_source.startswith("UTC ("):
        result.notes.append("No time zone found: the hours table is in UTC.")
    result.notes.append(
        "Resumes are '+running' records with the screen off on battery; a wake "
        "reason on a record stamped within 1 ms of the resume is attached to it. "
        "Screen doze (always-on display) counts as screen off, as in batterystats. "
        "Deep idle is screen-off time in device_idle=full state. Awake per "
        "resume runs from a resume to the next '-running' in the same span; "
        "suspend aborts are 'Abort:' wake reasons recorded in the history.",
    )
    if total >= MIN_SCREEN_OFF_FOR_FINDINGS_S * 1000:
        _standby_findings(ctx, timeline, stats, result)
    else:
        result.notes.append(
            f"Only {fmt_duration(total / 1000)} of screen-off time on battery: too "
            "short for findings.",
        )
    return result


def _standby_tables(timeline: Timeline, stats: _Standby, result: Result) -> None:
    n = len(stats.resumes)
    history = timeline.history
    result.add_table(
        "wake_reasons",
        [
            {"reason": reason, "resumes": count, "share_pct": pct(count, n)}
            for reason, count in stats.reasons.most_common()
        ],
    )
    result.add_table(
        "suspend_aborts",
        [{"reason": r, "count": c} for r, c in stats.aborts.most_common()],
    )
    spans = sorted(timeline.spans, key=lambda s: s.total_ms, reverse=True)
    result.add_table("spans", [_span_row(history, s) for s in spans])
    result.tables["doze_states"] = [
        {
            "state": name,
            "minutes": _r(total / 60_000),
            "awake_min": _r(running / 60_000),
            "awake_pct": pct(running, total),
            "wakelock_min": _r(wakelock / 60_000),
            "resumes": count,
        }
        for name, (total, running, wakelock, count) in timeline.classes.items()
        if total
    ]
    hours = sorted(timeline.hours.items(), key=lambda kv: kv[1][3], reverse=True)
    hour_rows = [
        {
            "hour": _iso(hour),
            "screen_off_min": _r(off / 60_000),
            "awake_pct": pct(awake, off),
            "deep_idle_min": _r(idle / 60_000),
            "resumes": count,
            "resumes_per_h": per_hour(count, off / 1000),
        }
        for hour, (off, awake, idle, count) in hours
        if off
    ]
    result.add_table("hours", hour_rows)
    result.tables["hours"].sort(key=lambda row: row["hour"] or "")
    edges = [*_INTERVAL_BINS_S, float("inf")]
    counts = [0] * (len(edges) - 1)
    for value in stats.intervals_s:
        counts[min(bisect.bisect_right(edges, value) - 1, len(counts) - 1)] += 1
    result.tables["resume_interval_histogram"] = [
        {"from_s": lo, "to_s": None if hi == float("inf") else hi, "count": c}
        for (lo, hi), c in zip(pairwise(edges), counts, strict=True)
    ]


def _standby_findings(
    ctx: Context,
    timeline: Timeline,
    stats: _Standby,
    result: Result,
) -> None:
    m = result.metrics
    share = m["awake_share_pct"] or 0.0
    rate = m["resumes_per_h"] or 0.0
    if share < AWAKE_SHARE_SUSPICIOUS_PCT and rate < WAKE_STORM_PER_H:
        return
    history = timeline.history
    longest = max(timeline.spans, key=lambda s: s.total_ms)
    evidence = [history.evidence(longest.start_pos)]
    sample = next((r for r in longest.resumes if r.reason), None)
    if sample is not None:
        evidence.append(history.evidence(sample.pos))
    if since := load_since_charge(ctx):
        evidence += since.evidence(_SC_TIMES["screen_off"])
    _awake_finding(stats, result, evidence)


def _awake_parts(stats: _Standby, m: dict[str, Any]) -> list[str]:
    """Sentences of the awake-share summary: rate, top reason, per-resume cost."""
    share = m["awake_share_pct"]
    parts = [
        (
            f"In {fmt_duration(stats.total_ms / 1000)} of screen-off time on battery "
            f"the SoC was awake {fmt_duration(stats.awake_ms / 1000)} ({share}%) and "
            f"resumed from suspend {len(stats.resumes)} times ({m['resumes_per_h']}/h, "
            f"median gap {m['resume_interval_median_s']} s)."
        ),
    ]
    reason = m["top_wake_reason"]
    if reason and reason != _NO_REASON:
        parts.append(
            f"{m['top_wake_reason_share_pct']}% of these resumes carry wake reason "
            f"'{reason}'; the name suggests {_irq_hint(reason)}.",
        )
    if (m["awake_per_resume_median_s"] or 0) >= SLOW_RESUSPEND_MEDIAN_S:
        parts.append(
            f"Each resume kept the SoC awake a median {m['awake_per_resume_median_s']} "
            f"s (mean {m['awake_per_resume_mean_s']} s) before it slept again.",
        )
    if (m["awake_without_wakelock_share_pct"] or 0) >= KERNEL_AWAKE_SHARE_PCT:
        parts.append(
            f"Android wakelocks covered only {_r(stats.wakelock_ms / 60_000)} of "
            f"the {_r(stats.awake_ms / 60_000)} awake minutes, so most awake time "
            "is kernel or driver work that per-app battery statistics do not show.",
        )
    if (m["deep_idle_share_pct"] or 0) >= DOMINANT_REASON_SHARE_PCT / 2:
        parts.append(
            f"Doze was in deep idle for {m['deep_idle_share_pct']}% of that time, "
            "so Doze works; it does not stop these wakes.",
        )
    return parts


def _awake_finding(stats: _Standby, result: Result, evidence: list[Evidence]) -> None:
    m = result.metrics
    share = m["awake_share_pct"] or 0.0
    rate = m["resumes_per_h"] or 0.0
    severe = share >= AWAKE_SHARE_SEVERE_PCT or rate >= WAKE_STORM_HIGH_PER_H
    title = (
        f"Screen off on battery, the SoC was awake {share}% of the time"
        if share >= AWAKE_SHARE_SUSPICIOUS_PCT
        else f"Screen off on battery, the SoC resumed {rate:.0f} times per hour"
    )
    result.findings.append(
        Finding(
            id="standby_wake.awake_share",
            title=title,
            symptom="battery",
            severity="high" if severe else "medium",
            basis="measured",
            window="screen_off_on_battery",
            summary=" ".join(_awake_parts(stats, m)),
            metrics={
                k: m[k]
                for k in (
                    "screen_off_on_battery_s",
                    "awake_share_pct",
                    "resumes",
                    "resumes_per_h",
                    "top_wake_reason",
                    "top_wake_reason_share_pct",
                    "awake_per_resume_median_s",
                    "awake_without_wakelock_share_pct",
                    "deep_idle_share_pct",
                )
            },
            evidence=evidence,
            recommendation=(
                "Find what triggers the wakes: the top wake reason names the "
                "interrupt. For a Wi-Fi interrupt, look for apps and peers that keep "
                "sending packets to the phone: VPNs with peer heartbeats, "
                "companion-device and sync apps with keepalives, and multicast "
                "traffic let in while an app holds a Wi-Fi multicast lock. Battery "
                "saver and Doze do not stop network packets to VPN or "
                "foreground-service apps. After each change (Wi-Fi off, or the "
                "suspected app stopped), repeat a screen-off test on battery of at "
                "least 2 h and compare the awake share and resumes per hour."
            ),
            followups=[
                "Check wake_periodicity for a fixed period (keepalive or heartbeat).",
                (
                    "Check per-UID network packets while the screen was off and the "
                    "Wi-Fi multicast lock time (wifi_multicast)."
                ),
                "Check wakeup_reasons for aborted suspend attempts after each wake.",
            ],
        ),
    )


# Hints for common wake reason (IRQ) names; matched case-insensitively.
_IRQ_HINTS = (
    (("wlan", "wifi", "_ce_", "cnss", "icnss"), "Wi-Fi: incoming network packets"),
    (("ipcc", "glink", "modem", "smp2p", "rmnet", "ipa"), "modem or data path"),
    (("alarm", "rtc"), "a timer or alarm"),
    (("uart", "bt", "bluetooth"), "Bluetooth"),
    (("pon", "kpdpwr", "gpio_keys", "key"), "a key press"),
    (("typec", "usb", "pd_", "charger"), "the USB/charger port"),
    (("sensor", "ssc", "slpi"), "a sensor hub"),
)


def _irq_hint(reason: str) -> str:
    lowered = reason.lower()
    for needles, hint in _IRQ_HINTS:
        if any(needle in lowered for needle in needles):
            return hint
    return "an interrupt that needs the device's IRQ map to identify"


# ---------------------------------------------------------------------------
# The wake_periodicity analyzer


def _lag_spectrum(groups: list[list[int]]) -> tuple[list[int], list[float]]:
    """Share of resumes with an earlier resume at each lag (one-sided)."""
    lags = list(range(LAG_MIN_MS, LAG_MAX_MS + 1, LAG_STEP_MS))
    hits = [0] * len(lags)
    total = 0
    for times in groups:
        total += len(times)
        for j, t in enumerate(times):
            seen: set[int] = set()
            i = j - 1
            while i >= 0 and t - times[i] <= LAG_MAX_MS + LAG_TOL_MS:
                d = t - times[i]
                lo = max(0, -(-(d - LAG_TOL_MS - LAG_MIN_MS) // LAG_STEP_MS))
                hi = min(len(lags) - 1, (d + LAG_TOL_MS - LAG_MIN_MS) // LAG_STEP_MS)
                seen.update(range(lo, hi + 1))
                i -= 1
            for k in seen:
                hits[k] += 1
    shares = [100 * h / total if total else 0.0 for h in hits]
    return lags, shares


def _grid_share(groups: list[list[int]], period_ms: float, offset_ms: float) -> float:
    """Share of resumes with a neighbour at ``k*period + offset`` (two-sided)."""
    targets = [k * period_ms + offset_ms for k in range(1, GRID_HARMONICS + 1)]
    hit = total = 0
    for times in groups:
        total += len(times)
        for t in times:
            for target in targets:
                for sign in (-1, 1):
                    want = t + sign * target
                    i = bisect.bisect_left(times, want - LAG_TOL_MS)
                    if i < len(times) and times[i] <= want + LAG_TOL_MS:
                        hit += 1
                        break
                else:
                    continue
                break
    return 100 * hit / total if total else 0.0


def _find_period(lags: list[int], shares: list[float]) -> tuple[int, list[int]] | None:
    """Pick the shortest strong peak whose harmonics are also elevated."""
    baseline = statistics.median(shares)
    peaks = [
        i
        for i in range(1, len(shares) - 1)
        if shares[i] - baseline >= PERIODIC_EXCESS_PP
        and shares[i] >= shares[i - 1]
        and shares[i] >= shares[i + 1]
    ]
    for i in peaks:
        excess = shares[i] - baseline
        harmonics = []
        for k in range(2, GRID_HARMONICS + 1):
            j = round((k * lags[i] - LAG_MIN_MS) / LAG_STEP_MS)
            if j >= len(shares):
                break
            # The grid point of the fundamental is up to half a step off the
            # true period, so the k-th harmonic may sit k half-steps away.
            window = shares[max(0, j - k) : j + k + 1]
            if max(window) - baseline >= HARMONIC_SUPPORT_RATIO * excess:
                harmonics.append(k)
        if harmonics or 2 * lags[i] > LAG_MAX_MS:
            return i, harmonics
    return None


def _peak_table(
    lags: list[int],
    shares: list[float],
    baseline: float,
) -> list[dict[str, Any]]:
    """Local maxima of the lag spectrum, strongest first."""
    peaks = sorted(
        (
            i
            for i in range(1, len(shares) - 1)
            if shares[i] >= shares[i - 1] and shares[i] > shares[i + 1]
        ),
        key=shares.__getitem__,
        reverse=True,
    )
    return [
        {
            "lag_s": lags[i] / 1000,
            "share_pct": _r(shares[i]),
            "excess_pp": _r(shares[i] - baseline),
        }
        for i in peaks
    ]


@analyzer("wake_periodicity", after=("windows", "battery_history", "standby_wake"))
def wake_periodicity(ctx: Context) -> Result:
    """Look for a strictly periodic sender behind the screen-off resumes."""
    timeline = _require_timeline(ctx)
    groups = [sorted(r.t_ms for r in s.resumes) for s in timeline.spans]
    groups = [g for g in groups if g]
    n = sum(len(g) for g in groups)
    if n < MIN_RESUMES_FOR_PERIODICITY:
        msg = f"only {n} screen-off resumes; need {MIN_RESUMES_FOR_PERIODICITY}"
        raise SkipError(msg)
    lags, shares = _lag_spectrum(groups)
    baseline = statistics.median(shares)
    result = Result("wake_periodicity", window="screen_off_on_battery")
    result.metrics = {
        "resumes": n,
        "lag_tolerance_ms": LAG_TOL_MS,
        "baseline_share_pct": _r(baseline),
    }
    result.add_table("lag_peaks", _peak_table(lags, shares, baseline))
    result.notes.append(
        "Share at a lag = resumes that have an earlier resume in the same "
        f"screen-off span exactly that far back (+-{LAG_TOL_MS} ms); baseline is "
        "the median share over all lags from 1 to 25 s.",
    )
    found = _find_period(lags, shares)
    if found is None:
        result.metrics["period_s"] = None
        return result
    i, harmonics = found
    period = _refine_period(groups, lags[i])
    grid = _grid_share(groups, period, 0.0)
    control = _grid_share(groups, period, period / 2)
    bins = _periodicity_bins(timeline, period)
    result.metrics |= {
        "period_s": _r(period / 1000, 4),
        "peak_lag_s": lags[i] / 1000,
        "share_at_period_pct": _r(shares[i]),
        "excess_at_period_pp": _r(shares[i] - baseline),
        "harmonics": [round(k * period / 1000, 2) for k in harmonics],
        "harmonic_shares": _harmonic_shares(lags, shares, period),
        "grid_share_pct": _r(grid),
        "control_grid_share_pct": _r(control),
        "grid_excess_pp": _r(grid - control),
        "bin_share_min_pct": _r(min(b["share_pct"] for b in bins)) if bins else None,
        "bin_share_max_pct": _r(max(b["share_pct"] for b in bins)) if bins else None,
    }
    result.add_table("bins", bins)
    _periodicity_finding(timeline, result)
    return result


def _refine_period(groups: list[list[int]], lag_ms: int) -> float:
    """Refine the period from pair differences near k x period, k = 1, 2, 4.

    Each pass takes the median difference near the next harmonic and divides
    by k, so the estimate converges from the coarse grid point.
    """
    period = float(lag_ms)
    for k in (1, 2, GRID_HARMONICS):
        target = k * period
        if target > LAG_MAX_MS:
            break
        diffs = []
        for times in groups:
            for j, t in enumerate(times):
                lo = bisect.bisect_left(times, t + target - 2 * LAG_TOL_MS, j + 1)
                hi = bisect.bisect_right(times, t + target + 2 * LAG_TOL_MS, j + 1)
                diffs += [times[x] - t for x in range(lo, hi)]
        if diffs:
            period = statistics.median(diffs) / k
    return period


def _harmonic_shares(
    lags: list[int],
    shares: list[float],
    period: float,
) -> list[dict[str, float | None]]:
    """Share at the grid point nearest each harmonic of ``period``."""
    rows = []
    for k in range(1, GRID_HARMONICS + 1):
        j = round((k * period - LAG_MIN_MS) / LAG_STEP_MS)
        if 0 <= j < len(shares):
            rows.append({"lag_s": lags[j] / 1000, "share_pct": _r(shares[j])})
    return rows


def _periodicity_bins(timeline: Timeline, period: float) -> list[dict[str, Any]]:
    """Grid share per 20-minute bin of screen-off time, in history time."""
    bins: dict[int, list[list[int]]] = {}
    for span in timeline.spans:
        for r in span.resumes:
            bins.setdefault(r.t_ms // PERIODICITY_BIN_MS, [[]])[0].append(r.t_ms)
    rows = []
    history = timeline.history
    origin = history.records[0].t_ms
    for key in sorted(bins):
        times = sorted(bins[key][0])
        if len(times) < MIN_RESUMES_FOR_PERIODICITY // 10:
            continue
        rows.append(
            {
                "bin_start_offset_min": round(
                    (key * PERIODICITY_BIN_MS - origin) / 60_000
                ),
                "resumes": len(times),
                "share_pct": _r(_grid_share([times], period, 0.0)),
            },
        )
    return rows


def _periodicity_finding(timeline: Timeline, result: Result) -> None:
    m = result.metrics
    if (m["excess_at_period_pp"] or 0) < PERIODIC_EXCESS_PP:
        return
    period = m["period_s"]
    harmonics = ", ".join(f"{h:g} s" for h in m["harmonics"]) or "none in range"
    history = timeline.history
    first = next((r for s in timeline.spans for r in s.resumes), None)
    result.findings.append(
        Finding(
            id="wake_periodicity.periodic_sender",
            title=f"Screen-off wakes repeat every {period:.2f} s",
            symptom="battery",
            severity="medium",
            basis="inferred",
            window="screen_off_on_battery",
            summary=(
                f"{m['share_at_period_pct']}% of screen-off resumes have another "
                f"resume {m['peak_lag_s']:.2f} +- {LAG_TOL_MS / 1000:.2f} s earlier "
                f"(refined period {period:.3f} s), against a "
                f"{m['baseline_share_pct']}% baseline at other lags; harmonics: "
                f"{harmonics}. {m['grid_share_pct']}% of resumes sit on this grid "
                f"versus {m['control_grid_share_pct']}% on a half-period-shifted "
                "control grid. A strict period points at a timer-driven sender "
                "(keepalive or heartbeat); the excess share is a rough upper bound "
                "of the resumes it causes, because other packets would wake the "
                "phone in the freed gaps."
            ),
            metrics={
                k: m[k]
                for k in (
                    "period_s",
                    "share_at_period_pct",
                    "baseline_share_pct",
                    "grid_share_pct",
                    "control_grid_share_pct",
                    "bin_share_min_pct",
                    "bin_share_max_pct",
                )
            },
            evidence=[history.evidence(first.pos)] if first else [],
            recommendation=(
                "Look for apps or network peers with a matching timer: VPN peer "
                "heartbeats (some mesh VPNs ping active peers every few seconds), "
                "companion or desktop-link apps with ~10 s TCP keepalives, and "
                "push or chat apps. Stop the suspect for an hour of screen-off on "
                "battery and compare resumes per hour."
            ),
            followups=[
                "Match the period with per-UID packet counts while screen off.",
                "Capture traffic on the peer that talks to the phone.",
            ],
        ),
    )


# ---------------------------------------------------------------------------
# The discharge_accounting analyzer


@dataclass
class _Discharge:
    """Since-charge discharge figures, from the text summary or checkin."""

    values: dict[str, float | None]
    evidence: list[Evidence]
    source: str


def _discharge_from_text(since: SinceCharge) -> _Discharge | None:
    """Read the counter discharge split; None when the summary has none of it."""
    v: dict[str, float | None] = {}
    for key, label in _SC_MAH.items():
        if (mah := since.mah(label)) is not None:
            v[key] = mah
    for key, label in _SC_COUNTS.items():
        if (count := _header_int(since, label)) is not None:
            v[key] = float(count)
    for key, label in _SC_TIMES.items():
        if found := since.duration_s(label):
            v[f"{key}_s"] = found[0]
            if found[1] is not None:
                v[f"{key}_uptime_s"] = found[1]
    screen_on = since.header(_SCREEN_ON)
    if screen_on and (m := _TIMES_COUNT_RE.search(screen_on[0])):
        v["screen_on_count"] = float(m[1])
    if (model := since.power) and model.computed_drain is not None:
        v["computed_drain_mah"] = model.computed_drain
        v["actual_drain_low_mah"] = model.actual_drain_min
        v["actual_drain_high_mah"] = model.actual_drain_max
    if not v:
        return None
    labels = (
        _SC_MAH["discharge_mah"],
        _SC_MAH["screen_off_mah"],
        _SC_MAH["deep_doze_mah"],
        _SC_TIMES["on_battery"],
        _SC_TIMES["screen_off"],
    )
    evidence = [e for label in labels for e in since.evidence(label)]
    return _Discharge(v, evidence, since.text.origin)


def _discharge_from_checkin(period: CheckinPeriod) -> _Discharge:
    v: dict[str, float | None] = {}
    ev: list[Evidence] = []
    if bt := period.row("bt"):
        index, f = bt
        ev.append(period.text.evidence(index))
        for key, i in (
            ("on_battery_s", BT_ON_BATTERY),
            ("on_battery_uptime_s", BT_ON_BATTERY_UP),
            ("screen_off_s", BT_SCREEN_OFF),
            ("screen_off_uptime_s", BT_SCREEN_OFF_UP),
            ("screen_doze_s", BT_SCREEN_DOZE),
        ):
            value = _int(f, i)
            v[key] = value / 1000 if value is not None else None
    if dc := period.row("dc"):
        index, f = dc
        ev.append(period.text.evidence(index))
        for key, i in (
            ("level_lower", DC_LOW),
            ("level_upper", DC_HIGH),
            ("level_screen_on", DC_SCREEN_ON_PCT),
            ("level_screen_off", DC_SCREEN_OFF_PCT),
            ("discharge_mah", DC_MAH),
            ("screen_off_mah", DC_SCREEN_OFF_MAH),
            ("screen_doze_mah", DC_DOZE_MAH),
            ("light_doze_mah", DC_LIGHT_MAH),
            ("deep_doze_mah", DC_DEEP_MAH),
        ):
            value = _int(f, i)
            v[key] = float(value) if value is not None else None
        # Doze is part of screen off (AOSP BatteryStats: screen-on discharge
        # = discharge - screen-off discharge).
        if v.get("discharge_mah") is not None and v.get("screen_off_mah") is not None:
            v["screen_on_mah"] = (v["discharge_mah"] or 0) - (v["screen_off_mah"] or 0)
    if m := period.row("m"):
        _, f = m
        for key, i in (
            ("screen_on_s", M_SCREEN_ON),
            ("power_save_s", M_POWER_SAVE),
            ("device_full_idling_s", M_DEVICE_IDLING_FULL),
            ("device_light_idling_s", M_DEVICE_IDLING_LIGHT),
            ("idle_mode_full_s", M_IDLE_FULL),
        ):
            value = _int(f, i)
            v[key] = value / 1000 if value is not None else None
        changes = _int(f, M_CONN_CHANGES)
        v["connectivity_changes"] = float(changes) if changes is not None else None
    if pws := period.row("pws"):
        _, f = pws
        v["computed_drain_mah"] = _float(f, PWS_COMPUTED)
        v["actual_drain_low_mah"] = _float(f, PWS_MIN)
        v["actual_drain_high_mah"] = _float(f, PWS_MAX)
    return _Discharge(v, ev, period.text.origin)


@analyzer("discharge_accounting")
def discharge_accounting(ctx: Context) -> Result:
    """Split the since-charge discharge into screen on, screen off and Doze."""
    since = load_since_charge(ctx)
    period = load_checkin_period(ctx)
    primary = _discharge_from_text(since) if since else None
    secondary = _discharge_from_checkin(period) if period else None
    data = primary or secondary
    if data is None:
        msg = "no since-charge summary (batterystats --charged or -c)"
        raise SkipError(msg)
    values = dict(data.values)
    result = Result("discharge_accounting", window="on_battery")
    if primary and secondary:
        for key, value in secondary.values.items():
            values.setdefault(key, value)
        _compare_sources(primary, secondary, result)
    result.metrics = _discharge_metrics(
        values,
        data.source,
        load_capacity(ctx).learned_mah,
    )
    result.notes.append(
        "mAh figures are fuel-gauge counter values (measured); on gauges that "
        "report whole % of the learned capacity each carries +-1 step "
        "(see gauge_quantization). Screen off includes screen doze, as in "
        "batterystats. The deep-Doze rate divides by 'Idle mode full time' "
        "(deep idle, when its counter runs), else by 'Device full idling'.",
    )
    _discharge_findings(data, result)
    return result


def _discharge_metrics(
    v: dict[str, float | None],
    source: str,
    capacity: float | None,
) -> dict[str, Any]:
    """Turn raw since-charge values into durations, mAh, rates and shares."""
    on_s = v.get("on_battery_s")
    off_s = v.get("screen_off_s")
    screen_on_s = None
    if on_s is not None:
        # Screen off already includes screen doze (batterystats time bases).
        screen_on_s = on_s - (off_s or 0)
        screen_on_s = screen_on_s if screen_on_s >= 0 else None
    # The deep-doze counter runs in deep idle ('Idle mode full time'), which
    # leaves out the maintenance windows inside 'Device full idling'.
    deep_s = v.get("idle_mode_full_s") or v.get("device_full_idling_s")
    metrics: dict[str, Any] = {
        "source": source,
        "on_battery_s": _r(on_s),
        "screen_off_s": _r(off_s),
        "screen_on_s": _r(screen_on_s),
        "awake_share_pct": pct(v.get("on_battery_uptime_s") or 0, on_s or 0),
        "screen_off_awake_share_pct": pct(
            v.get("screen_off_uptime_s") or 0,
            off_s or 0,
        ),
        "discharge_mah": v.get("discharge_mah"),
        "screen_on_mah": v.get("screen_on_mah"),
        "screen_off_mah": v.get("screen_off_mah"),
        "screen_doze_mah": v.get("screen_doze_mah"),
        "light_doze_mah": v.get("light_doze_mah"),
        "deep_doze_mah": v.get("deep_doze_mah"),
        "discharge_mah_per_h": per_hour(v.get("discharge_mah"), on_s),
        "screen_on_mah_per_h": per_hour(v.get("screen_on_mah"), screen_on_s),
        "screen_off_mah_per_h": per_hour(v.get("screen_off_mah"), off_s),
        "deep_doze_mah_per_h": per_hour(v.get("deep_doze_mah"), deep_s),
        "device_full_idling_s": _r(v.get("device_full_idling_s")),
        "idle_mode_full_s": _r(v.get("idle_mode_full_s")),
        "power_save_share_pct": pct(v.get("power_save_s") or 0, on_s or 0),
        "screen_on_count": v.get("screen_on_count"),
        "connectivity_changes": v.get("connectivity_changes"),
        "level_discharged_lower": v.get("level_lower"),
        "level_discharged_upper": v.get("level_upper"),
        "level_screen_on": v.get("level_screen_on"),
        "level_screen_off": v.get("level_screen_off"),
        "computed_drain_mah": v.get("computed_drain_mah"),
        "actual_drain_low_mah": v.get("actual_drain_low_mah"),
        "actual_drain_high_mah": v.get("actual_drain_high_mah"),
        "learned_capacity_mah": capacity,
    }
    if capacity:
        step = capacity / _FULL
        metrics["gauge_step_mah"] = _r(step, 2)
        for key in ("discharge", "screen_off", "screen_on", "deep_doze"):
            rate = metrics.get(f"{key}_mah_per_h")
            metrics[f"{key}_pct_per_h"] = _r(100 * rate / capacity, 2) if rate else None
        if v.get("level_screen_off") is not None:
            level_mah = (v["level_screen_off"] or 0) * step
            metrics["level_screen_off_mah"] = _r(level_mah)
            metrics["level_screen_off_mah_per_h"] = per_hour(level_mah, off_s)
    return metrics


def _compare_sources(
    primary: _Discharge, secondary: _Discharge, result: Result
) -> None:
    a = primary.values.get("discharge_mah")
    b = secondary.values.get("discharge_mah")
    if a is not None and b is not None and a != b:
        result.notes.append(
            f"The text summary says {a:.0f} mAh discharged and the checkin rows "
            f"{b:.0f} mAh; the dumps were taken at different times.",
        )


def _discharge_findings(data: _Discharge, result: Result) -> None:
    m = result.metrics
    off_s = m.get("screen_off_s") or 0
    pct = m.get("screen_off_pct_per_h")
    if pct is None or off_s < MIN_SCREEN_OFF_FOR_FINDINGS_S:
        return
    step = m.get("gauge_step_mah") or 0
    if pct >= IDLE_DRAIN_MEDIUM_PCT_PER_H:
        low = per_hour(max((m["screen_off_mah"] or 0) - step, 0), off_s)
        high = per_hour((m["screen_off_mah"] or 0) + step, off_s)
        deep = m.get("deep_doze_mah_per_h")
        summary = (
            f"With the screen off the battery lost {m['screen_off_mah']:.0f} mAh in "
            f"{fmt_duration(off_s)}: {m['screen_off_mah_per_h']} mAh/h ({pct} %/h of "
            f"the learned capacity; {low}-{high} mAh/h with one gauge step either "
            "way)."
        )
        if deep is not None:
            deep_s = m["idle_mode_full_s"] or m["device_full_idling_s"]
            summary += f" In deep Doze it was {deep} mAh/h over {fmt_duration(deep_s)}."
        summary += (
            f" A suspending phone typically idles at {HEALTHY_IDLE_MAH_PER_H} mAh/h "
            "(general expectation, not measured on this device)."
        )
        if off_s < 2 * 3600:
            summary += " The window is under 2 h, so gauge steps make this rough."
        result.findings.append(
            Finding(
                id="discharge_accounting.standby_drain",
                title=(
                    f"Screen-off drain is {pct} %/h ({m['screen_off_mah_per_h']} mAh/h)"
                ),
                symptom="battery",
                severity="high" if pct >= IDLE_DRAIN_HIGH_PCT_PER_H else "medium",
                basis="measured",
                window="screen_off_on_battery",
                summary=summary,
                metrics={
                    k: m.get(k)
                    for k in (
                        "screen_off_mah",
                        "screen_off_s",
                        "screen_off_mah_per_h",
                        "screen_off_pct_per_h",
                        "deep_doze_mah_per_h",
                        "screen_off_awake_share_pct",
                        "gauge_step_mah",
                    )
                },
                evidence=data.evidence[:4],
                recommendation=(
                    "Judge fixes by counter-based screen-off mAh/h and the awake "
                    "share, not by the per-app list in Settings > Battery, which "
                    "prices suspend and awake-idle time at almost nothing."
                ),
                followups=[
                    "Check standby_wake for the awake share and wake reasons.",
                    "Repeat a screen-off test of at least 2 h after each change.",
                ],
            ),
        )
    _level_skew_finding(data, result)


def _level_skew_finding(data: _Discharge, result: Result) -> None:
    m = result.metrics
    counter = m.get("screen_off_mah")
    level = m.get("level_screen_off_mah")
    step = m.get("gauge_step_mah")
    if counter is None or level is None or not step:
        return
    if counter < LEVEL_HIDES_DRAIN_RATIO * level or counter - level < (
        LEVEL_SKEW_MIN_STEPS * step
    ):
        return
    on = m.get("level_screen_on")
    with_on = f" and {on:.0f} with it on" if on is not None else ""
    result.findings.append(
        Finding(
            id="discharge_accounting.level_hides_idle_drain",
            title="The battery % hides screen-off drain until the screen comes on",
            symptom="battery",
            severity="low",
            basis="measured",
            window="on_battery",
            summary=(
                f"The gauge counter puts {counter:.0f} mAh in screen-off time, but "
                f"the displayed level fell only {m['level_screen_off']:.0f} points "
                f"with the screen off (~{level:.0f} mAh){with_on}. The level lags in "
                "Doze and catches up after wake, so idle drain looks like drain "
                "during use."
            ),
            metrics={
                "screen_off_mah": counter,
                "level_screen_off_mah": level,
                "level_screen_on": on,
                "level_screen_off": m["level_screen_off"],
            },
            evidence=data.evidence[:3],
            recommendation=(
                "Judge standby drain from counter-based figures or from %/h over "
                "a long screen-off window measured from the first screen-on after "
                "it, not from how fast the % drops while using the phone."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# The daily_steps analyzer


@dataclass
class _Step:
    number: int
    duration_s: float
    level: int
    flags: str
    index: int


@dataclass
class _Day:
    label: str
    start: datetime | None
    end: datetime | None
    index: int
    discharge: list[_Step] = field(default_factory=list)
    charge: list[_Step] = field(default_factory=list)
    summaries: dict[str, tuple[float, int]] = field(default_factory=dict)


_DAILY_RE = re.compile(r"^Daily stats:")
_STAMP_RE = r"(\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d)"
_DAILY_FROM_RE = re.compile(rf"^\s+Daily from {_STAMP_RE} to {_STAMP_RE}:")
_DAILY_CURRENT_RE = re.compile(
    r"^\s+Current start time: (\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d)"
)
_STEP_LIST_RE = re.compile(
    r"^\s+(?:Current daily )?(discharge|charge) step durations:",
    re.IGNORECASE,
)
_STEP_RE = re.compile(r"^\s+#(\d+): \+(\S+) to (\d+)(?: \(([^)]*)\))?")
_STEP_SUMMARY_RE = re.compile(
    r"^\s+(Discharge|Charge) (.+?) time: (.+?)\s+\(from (\d+) steps\)",
)
_STAMP = "%Y-%m-%d-%H-%M-%S"


def parse_daily(text: Text) -> list[_Day]:
    """Parse "Daily stats": the current day first, then older days, newest first."""
    lines = text.lines
    start = next((i for i, line in enumerate(lines) if _DAILY_RE.match(line)), None)
    if start is None:
        return []
    days: list[_Day] = []
    kind = ""
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line[0].isspace():
            break
        if m := _DAILY_CURRENT_RE.match(line):
            days.append(_Day("current", datetime.strptime(m[1], _STAMP), None, index))
        elif m := _DAILY_FROM_RE.match(line):
            begin, end = (datetime.strptime(x, _STAMP) for x in (m[1], m[2]))
            days.append(_Day(begin.date().isoformat(), begin, end, index))
        elif days:
            kind = _daily_line(days[-1], kind, line, index)
    return days


def _daily_line(day: _Day, kind: str, line: str, index: int) -> str:
    """Add a step or summary line to ``day``; return the current step kind."""
    if m := _STEP_LIST_RE.match(line):
        return m[1].lower()
    if (m := _STEP_RE.match(line)) and (ms := _duration_or_none(m[2])) is not None:
        step = _Step(int(m[1]), ms / 1000, int(m[3]), m[4] or "", index)
        (day.discharge if kind == "discharge" else day.charge).append(step)
    elif (m := _STEP_SUMMARY_RE.match(line)) and (
        ms := _duration_or_none(m[3])
    ) is not None:
        day.summaries[f"{m[1].lower()} {m[2]}"] = (ms / _MS_PER_H, int(m[4]))
    return kind


def _duration_or_none(text: str) -> int | None:
    try:
        return parse_duration_ms(text)
    except ValueError:
        return None


def _day_row(day: _Day) -> dict[str, Any]:
    steps = day.discharge  # newest first
    fast_low = [
        s for s in steps if s.level <= LOW_LEVEL_PCT and s.duration_s < FAST_STEP_S
    ]
    rebounds = [
        (older.level, newer.level)
        for newer, older in pairwise(steps)
        if newer.level > older.level
        and older.level <= LOW_LEVEL_PCT
        and newer.level - older.level <= REBOUND_MAX_POINTS
    ]
    summary = day.summaries
    return {
        "day": day.label,
        "start": _iso(day.start),
        "end": _iso(day.end),
        "discharge_steps": len(steps),
        "charge_steps": len(day.charge),
        "min_level": min((s.level for s in steps), default=None),
        "total_h": _r(summary.get("discharge total", (None,))[0], 2),
        "screen_off_idle_h": _r(
            summary.get("discharge screen off device idle", (None,))[0],
            2,
        ),
        "screen_on_saver_h": _r(
            summary.get("discharge screen on power save", (None,))[0],
            2,
        ),
        "fast_low_steps": len(fast_low),
        "low_level_rebounds": len(rebounds),
    }


def _summary_hours(days: list[_Day], key: str) -> list[float]:
    """Unrounded extrapolated hours of summary row ``key`` on the days that have it."""
    return [d.summaries[key][0] for d in days if d.summaries.get(key, (0,))[0]]


@analyzer("daily_steps", requires=("batterystats",))
def daily_steps(ctx: Context) -> Result:
    """Summarise about ten days of level steps from "Daily stats"."""
    text = ctx.sources.get("batterystats")
    if text is None:
        msg = "no batterystats text dump"
        raise SkipError(msg)
    days = parse_daily(text)
    full = [d for d in days if d.label != "current"]
    if not full:
        msg = "no 'Daily stats' day blocks in batterystats"
        raise SkipError(msg)
    result = Result("daily_steps", window="daily")
    rows = [_day_row(d) for d in full]
    capacity = load_capacity(ctx).learned_mah
    totals = _summary_hours(full, "discharge total")
    idle = _summary_hours(full, "discharge screen off device idle")
    saver = _summary_hours(full, "discharge screen on power save")
    steps = sum(r["discharge_steps"] for r in rows)
    span_days = _days_covered(full)
    median_idle = statistics.median(idle) if idle else None
    result.metrics = {
        "days": len(full),
        "days_covered": _r(span_days, 2),
        "median_total_h": _r(statistics.median(totals), 2) if totals else None,
        "median_total_days": len(totals),
        "median_screen_off_idle_h": _r(median_idle, 2),
        "median_screen_off_idle_days": len(idle),
        "median_screen_on_saver_h": _r(statistics.median(saver), 2) if saver else None,
        "median_screen_on_saver_days": len(saver),
        "discharge_steps": steps,
        "charge_steps": sum(r["charge_steps"] for r in rows),
        "cycles_per_day": _r(steps / _FULL / span_days, 2) if span_days else None,
        "deep_discharge_days": sum(
            1
            for r in rows
            if r["min_level"] is not None and r["min_level"] <= DEEP_DISCHARGE_PCT
        ),
        "fast_low_steps": sum(r["fast_low_steps"] for r in rows),
        "learned_capacity_mah": capacity,
    }
    if capacity and totals:
        result.metrics["median_total_mah_per_h"] = _r(
            capacity / statistics.median(totals),
        )
    if capacity and median_idle:
        result.metrics["median_screen_off_idle_mah_per_h"] = _r(capacity / median_idle)
    if median_idle:
        result.metrics["median_screen_off_idle_pct_per_h"] = _r(_FULL / median_idle, 2)
    current = next((d for d in days if d.label == "current"), None)
    if current and (cur := current.summaries.get("discharge screen off device idle")):
        result.metrics["current_day_screen_off_idle_h"] = _r(cur[0], 2)
        result.metrics["current_day_screen_off_idle_steps"] = cur[1]
    result.add_table("days", rows)
    result.notes.append(
        "Step times are the displayed level, which lags the gauge in Doze; full-"
        "charge times are Android's extrapolations to a 100 % swing. Medians "
        "cover only the days that have each row.",
    )
    _daily_findings(text, full, rows, result)
    return result


def _days_covered(days: list[_Day]) -> float:
    starts = [d.start for d in days if d.start]
    ends = [d.end for d in days if d.end]
    if not starts or not ends:
        return float(len(days))
    return (max(ends) - min(starts)).total_seconds() / 86400


def _daily_findings(
    text: Text,
    days: list[_Day],
    rows: list[dict[str, Any]],
    result: Result,
) -> None:
    m = result.metrics
    pct = m.get("median_screen_off_idle_pct_per_h")
    if pct is not None and pct >= IDLE_DRAIN_MEDIUM_PCT_PER_H:
        idle_rows = [r for r in rows if r["screen_off_idle_h"]]
        result.findings.append(
            Finding(
                id="daily_steps.idle_drain",
                title=f"Over {m['median_screen_off_idle_days']} days, screen-off idle "
                f"drain was about {pct} %/h",
                symptom="battery",
                severity="high" if pct >= IDLE_DRAIN_HIGH_PCT_PER_H else "medium",
                basis="measured",
                window="daily",
                summary=(
                    "Android's daily step history extrapolates a full charge to "
                    f"last a median {m['median_screen_off_idle_h']} h in screen-off "
                    f"Doze ({pct} %/h; range "
                    f"{min(r['screen_off_idle_h'] for r in idle_rows)}-"
                    f"{max(r['screen_off_idle_h'] for r in idle_rows)} h over "
                    f"{len(idle_rows)} days). These are level-based figures, which "
                    "lag in Doze, so the real idle drain was probably higher."
                ),
                metrics={
                    k: m.get(k)
                    for k in (
                        "median_screen_off_idle_h",
                        "median_screen_off_idle_pct_per_h",
                        "median_screen_off_idle_mah_per_h",
                        "median_total_h",
                    )
                },
                evidence=[text.evidence(days[0].index)],
                recommendation=(
                    "The drain is chronic, not a one-day event: find the standby "
                    "wake source (standby_wake) and re-check the daily figures a "
                    "few days after a fix."
                ),
            ),
        )
    collapse_days = [r for r in rows if r["fast_low_steps"] >= COLLAPSE_MIN_FAST_STEPS]
    deep_days = [
        r
        for r in rows
        if r["min_level"] is not None and r["min_level"] <= DEEP_DISCHARGE_PCT
    ]
    if collapse_days:
        worst = max(collapse_days, key=itemgetter("fast_low_steps"))
        day = next(d for d in days if d.label == worst["day"])
        fast = [
            s
            for s in day.discharge
            if s.level <= LOW_LEVEL_PCT and s.duration_s < FAST_STEP_S
        ]
        result.findings.append(
            Finding(
                id="daily_steps.low_level_collapse",
                title="Near empty, the battery level collapses in seconds per %",
                symptom="battery",
                severity="medium",
                basis="inferred",
                window="daily",
                summary=(
                    f"On {len(collapse_days)} day(s) the level fell 1 % in under "
                    f"{FAST_STEP_S} s at or below {LOW_LEVEL_PCT} % (worst "
                    f"{worst['day']}: {worst['fast_low_steps']} such steps). Moving "
                    "1 % of capacity that fast is not real charge flow; the voltage "
                    "sags under load near cutoff, typical of a worn cell. The level "
                    f"reached {DEEP_DISCHARGE_PCT} % or less on {len(deep_days)} days."
                ),
                metrics={
                    "collapse_days": len(collapse_days),
                    "fast_low_steps": m["fast_low_steps"],
                    "deep_discharge_days": len(deep_days),
                },
                evidence=[text.evidence(s.index) for s in fast[:3]],
                recommendation=(
                    "Recharge at 15-20 % instead of running toward 0 %, especially "
                    "under heavy load or in the cold; check battery wear "
                    "(battery_capacity) and low-battery shutdowns."
                ),
            ),
        )
    elif len(deep_days) >= DEEP_DISCHARGE_MIN_DAYS:
        result.findings.append(
            Finding(
                id="daily_steps.deep_discharges",
                title=f"The battery ran down to {DEEP_DISCHARGE_PCT} % or less on "
                f"{len(deep_days)} days",
                symptom="battery",
                severity="low",
                basis="measured",
                window="daily",
                summary=(
                    "Frequent deep discharges add wear and risk unexpected "
                    "shutdowns on an aged cell."
                ),
                metrics={"deep_discharge_days": len(deep_days)},
                evidence=[text.evidence(days[0].index)],
                recommendation="Recharge at 15-20 % where practical.",
            ),
        )


# ---------------------------------------------------------------------------
# The battery_capacity analyzer


@analyzer("battery_capacity", after=("windows", "daily_steps"))
def battery_capacity(ctx: Context) -> Result:
    """Compare learned with design capacity and sanity-check the cycle count."""
    facts = load_capacity(ctx)
    if facts.learned_mah is None and facts.cycle_count is None:
        msg = "no learned capacity or cycle count (health HAL, batterystats, dmesg)"
        raise SkipError(msg)
    result = Result("battery_capacity", window="snapshot")
    soh = (
        _r(100 * facts.learned_mah / facts.design_mah)
        if facts.learned_mah and facts.design_mah
        else None
    )
    result.metrics = {
        "learned_capacity_mah": facts.learned_mah,
        "learned_source": facts.learned_source,
        "design_capacity_mah": facts.design_mah,
        "design_source": facts.design_source,
        "hal_design_capacity_mah": facts.hal_design_mah,
        "power_profile_capacity_mah": facts.profile_design_mah,
        "state_of_health_pct": soh,
        "capacity_lost_mah": _r(facts.design_mah - facts.learned_mah, 0)
        if soh is not None and facts.design_mah and facts.learned_mah
        else None,
        "new_pack_runtime_factor": _r(facts.design_mah / facts.learned_mah, 2)
        if soh is not None and facts.design_mah and facts.learned_mah
        else None,
        "cycle_count": facts.cycle_count,
        "cycle_source": facts.cycle_source,
        "hal_health": facts.hal_health,
        "min_learned_mah": facts.min_learned_mah,
        "max_learned_mah": facts.max_learned_mah,
        "estimated_capacity_mah": facts.estimated_mah,
    }
    if facts.hal_design_mah and facts.learned_mah:
        result.metrics["state_of_health_vs_hal_design_pct"] = _r(
            100 * facts.learned_mah / facts.hal_design_mah,
        )
    result.notes += [
        (
            "batterystats 'learned capacity' and the HAL 'Full charge' are the same "
            "gauge value, not two independent measurements."
        ),
        (
            "'Estimated battery capacity' is the charge counter divided by the level "
            "at reset, not a capacity measurement."
        ),
        (
            "HAL health GOOD only rules out overheat, cold, over-voltage and failure; "
            "it says nothing about capacity."
        ),
    ]
    if facts.design_mah is None:
        result.notes.append(
            "No design capacity: collect 'dumpsys batterystats --power-profile' or "
            "a bugreport with the health HAL dump.",
        )
    _cycle_check(ctx, facts, result)
    _capacity_finding(facts, result)
    return result


def _cycle_check(ctx: Context, facts: CapacityFacts, result: Result) -> None:
    """Compare the cycle count with device age and observed cycles per day."""
    package = ctx.sources.get("package")
    if package is None or facts.cycle_count is None:
        return
    first = None
    for line in package.lines:
        m = _FIRST_INSTALL_RE.search(line)
        if m and int(m[1]) not in PLACEHOLDER_INSTALL_YEARS:
            stamp = datetime(int(m[1]), int(m[2]), int(m[3]))
            first = stamp if first is None or stamp < first else first
    reference = ctx.windows.dump_time
    if first is None or reference is None:
        return
    age_days = (reference - first).days
    result.metrics["device_age_days_lower_bound"] = age_days
    daily = ctx.results.get("daily_steps")
    per_day = daily.metrics.get("cycles_per_day") if daily else None
    if not per_day or age_days < MIN_DAYS_FOR_CYCLE_CHECK:
        return
    expected = age_days * per_day
    result.metrics["cycles_expected_at_current_use"] = round(expected)
    if facts.cycle_count < CYCLE_COUNT_IMPLAUSIBLE_RATIO * expected:
        result.findings.append(
            Finding(
                id="battery_capacity.cycle_count_reset",
                title="The cycle count is far too low for the device's age",
                symptom="info",
                severity="info",
                basis="inferred",
                window="snapshot",
                summary=(
                    f"The gauge reports {facts.cycle_count} cycles, but apps were "
                    f"first installed {age_days} days ago and the phone now uses "
                    f"about {per_day} cycles/day (~{round(expected)} expected). The "
                    "counter was reset or the battery pack was replaced; do not "
                    "compare it with a cycles-to-80 % rating."
                ),
                metrics={
                    "cycle_count": facts.cycle_count,
                    "device_age_days_lower_bound": age_days,
                    "cycles_per_day": per_day,
                },
                evidence=facts.evidence[:3],
                recommendation=(
                    "Ask whether the battery was replaced; if so, wear this fast "
                    "since the swap points at charging habits or heat."
                ),
            ),
        )


def _capacity_finding(facts: CapacityFacts, result: Result) -> None:
    m = result.metrics
    soh = m["state_of_health_pct"]
    if soh is None or soh >= SOH_WORN_PCT:
        return
    learned_note = ""
    if facts.min_learned_mah and facts.max_learned_mah:
        learned_note = (
            f" The gauge's learned value ranged {facts.min_learned_mah:.0f}-"
            f"{facts.max_learned_mah:.0f} mAh this period."
        )
    cycles = f", cycle count {facts.cycle_count}" if facts.cycle_count else ""
    result.findings.append(
        Finding(
            id="battery_capacity.worn",
            title=f"The battery holds {soh}% of its design capacity",
            symptom="battery",
            severity="high" if soh < SOH_SEVERE_PCT else "medium",
            basis="measured",
            window="snapshot",
            summary=(
                f"Learned full-charge capacity is {facts.learned_mah:.0f} mAh "
                f"({facts.learned_source}) against {facts.design_mah:.0f} mAh design "
                f"({facts.design_source}){cycles}: about "
                f"{m['capacity_lost_mah']:.0f} mAh lost, so a new pack would last "
                f"{m['new_pack_runtime_factor']}x as long at the same drain rate."
                f"{learned_note} Wear shortens runtime; it does not raise the drain "
                "rate in mAh/h."
            ),
            metrics={
                k: m.get(k)
                for k in (
                    "learned_capacity_mah",
                    "design_capacity_mah",
                    "state_of_health_pct",
                    "cycle_count",
                    "new_pack_runtime_factor",
                )
            },
            evidence=facts.evidence[:4],
            recommendation=(
                "Replace the battery if the runtime matters (on many phones it is "
                "user-replaceable). Afterwards the gauge needs a few full cycles to "
                "re-learn; compare the learned capacity in a later collection. Fix "
                "high drain rates separately."
            ),
            followups=[
                "Check daily_steps for level collapse near empty.",
                "Check low_battery_shutdowns.",
            ],
        ),
    )


# ---------------------------------------------------------------------------
# The gauge_quantization analyzer


@analyzer(
    "gauge_quantization",
    after=("windows", "battery_history", "discharge_accounting", "battery_capacity"),
)
def gauge_quantization(ctx: Context) -> Result:
    """Test whether mAh figures are whole % steps; measure level skew."""
    capacity = load_capacity(ctx)
    learned = capacity.learned_mah
    timeline = load_timeline(ctx)
    charges = timeline.charges if timeline else []
    if not learned or (not charges and capacity.live_counter_uah is None):
        msg = "needs a learned capacity and charge counter samples"
        raise SkipError(msg)
    result = Result("gauge_quantization", window="on_battery")
    step = learned / _FULL
    whole = [c for _, c, _, _ in charges if _is_whole_percent(c, learned)]
    soc_derived = len(charges) >= SOC_DERIVED_MIN_SAMPLES and (
        len(whole) >= SOC_DERIVED_MIN_SHARE * len(charges)
    )
    result.metrics = {
        "learned_capacity_mah": learned,
        "step_mah": _r(step, 2),
        "charge_samples": len(charges),
        "whole_percent_samples": len(whole),
        "soc_derived_counter": soc_derived,
    }
    discharge = ctx.results.get("discharge_accounting")
    rate = discharge.metrics.get("screen_off_mah_per_h") if discharge else None
    if rate:
        result.metrics["min_screen_off_test_h"] = _r(
            step / (QUANTIZATION_MAX_SHARE * rate),
            2,
        )
    if timeline is not None:
        _history_skew(timeline, learned, result)
        _clean_window(timeline, step, result)
    if capacity.live_counter_uah is not None and capacity.live_level is not None:
        soc = 100 * capacity.live_counter_uah / 1000 / learned
        result.metrics["live_level"] = capacity.live_level
        result.metrics["live_counter_soc_pct"] = _r(soc)
        result.metrics["live_level_skew_points"] = _r(capacity.live_level - soc)
        result.metrics["live_source"] = capacity.live_source
    if soc_derived:
        _quantization_finding(timeline, result)
    return result


def _is_whole_percent(charge_mah: int, learned: float) -> bool:
    p = round(100 * charge_mah / learned)
    exact = learned * p / _FULL
    return abs(charge_mah - exact) < 1


def _history_skew(timeline: Timeline, learned: float, result: Result) -> None:
    """Record the displayed level minus the counter SOC at screen-off samples."""
    skews_off = [
        level - 100 * charge / learned
        for _, charge, level, off in timeline.charges
        if level is not None and off
    ]
    if skews_off:
        result.metrics["screen_off_level_skew_max_points"] = _r(max(skews_off))
        result.metrics["screen_off_level_skew_min_points"] = _r(min(skews_off))


def _clean_window(timeline: Timeline, step: float, result: Result) -> None:
    """Rate between the first and last counter step inside the longest span."""
    best: tuple[float, int, int, float, float] | None = None
    history = timeline.history
    for span in timeline.spans:
        inside = [
            (pos, charge)
            for pos, charge, _, off in timeline.charges
            if off and span.start_pos < pos <= span.end_pos
        ]
        if len(inside) < SOC_DERIVED_MIN_SAMPLES // 2:
            continue
        (p0, c0), (p1, c1) = inside[0], inside[-1]
        hours = (history.records[p1].t_ms - history.records[p0].t_ms) / _MS_PER_H
        if hours > 0 and (best is None or hours > best[0]):
            best = (hours, p0, p1, float(c0 - c1), hours)
    if best is None:
        return
    hours, p0, p1, mah, _ = best
    result.metrics |= {
        "clean_window_start": _iso(history.wall(p0)),
        "clean_window_h": _r(hours, 2),
        "clean_window_mah": mah,
        "clean_window_mah_per_h": _r(mah / hours),
        "clean_window_mah_per_h_low": _r(max(mah - step, 0) / hours),
        "clean_window_mah_per_h_high": _r((mah + step) / hours),
    }
    result.notes.append(
        "The clean window runs between the first and last charge-counter change "
        "inside the longest screen-off span; the counter is polled every few "
        "minutes in Doze, so each end can lag by one poll.",
    )


def _quantization_finding(timeline: Timeline | None, result: Result) -> None:
    m = result.metrics
    evidence = []
    if timeline is not None:
        evidence = [timeline.history.evidence(pos) for pos, *_ in timeline.charges[:2]]
    test_h = m.get("min_screen_off_test_h")
    result.findings.append(
        Finding(
            id="gauge_quantization.soc_steps",
            title=f"batterystats mAh figures move in {m['step_mah']} mAh steps",
            symptom="info",
            severity="info",
            basis="measured",
            window="on_battery",
            summary=(
                f"{m['whole_percent_samples']} of {m['charge_samples']} charge counter "
                f"samples are whole percents of the {m['learned_capacity_mah']:.0f} "
                "mAh learned capacity, so the counter is the gauge's SOC times "
                f"capacity: every batterystats mAh figure is +-{m['step_mah']} mAh."
                + (
                    f" A screen-off A/B test needs at least {test_h} h to keep that "
                    "step under a quarter of the drain."
                    if test_h
                    else ""
                )
            ),
            metrics={
                k: m.get(k)
                for k in ("step_mah", "min_screen_off_test_h", "clean_window_mah_per_h")
            },
            evidence=evidence,
            recommendation=(
                "Quote mAh figures with +-1 step and compare drain over windows of "
                "at least the stated length."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# The low_battery_shutdowns analyzer

_GETPROP_LINE_RE = re.compile(r"^\[(?P<key>[^\]]+)\]: \[(?P<value>.*)$")
_BOOT_ENTRY_RE = re.compile(r"^(?P<reason>[^,]+(?:,[^,]+)*?),(?P<epoch>\d{9,})$")
_BOOT_KEYS = (
    "persist.sys.boot.reason.history",
    "ro.boot.bootreason",
    "sys.boot.reason",
    "sys.boot.reason.last",
)


def parse_getprop(text: Text) -> dict[str, tuple[str, int]]:
    """Parse ``[key]: [value]`` lines, joining values that span several lines."""
    props: dict[str, tuple[str, int]] = {}
    key: str | None = None
    parts: list[str] = []
    start = 0
    for index, line in enumerate(text.lines):
        if key is None:
            m = _GETPROP_LINE_RE.match(line)
            if not m:
                continue
            key, parts, start = m["key"], [m["value"]], index
        else:
            parts.append(line)
        if parts[-1].endswith("]"):
            parts[-1] = parts[-1][:-1]
            props[key] = ("\n".join(parts), start)
            key = None
    return props


def _classify_boot(reason: str) -> str:
    lowered = reason.lower()
    if "battery" in lowered:
        return "low battery"
    if "thermal" in lowered:
        return "thermal"
    if any(x in lowered for x in ("panic", "watchdog", "wdog", "crash", "hw_reset")):
        return "crash"
    if any(x in lowered for x in ("longkey", "longpress", "long_press")):
        return "forced"  # the user held the power key, usually on a hang
    if "userrequested" in lowered or lowered.startswith("reboot"):
        return "requested"
    return "other"


@analyzer("low_battery_shutdowns", after=("windows", "battery_history", "daily_steps"))
def low_battery_shutdowns(ctx: Context) -> Result:
    """List recent boot reasons and battery shutdowns with collapse evidence."""
    getprop = ctx.sources.get("getprop")
    props = parse_getprop(getprop) if getprop is not None else {}
    timeline = load_timeline(ctx)
    markers = (
        [(p, c) for p, c in timeline.markers if c in {"START", "SHUTDOWN"}]
        if timeline
        else []
    )
    if "persist.sys.boot.reason.history" not in props and not markers:
        msg = "no boot reason history (getprop) and no reboot markers in history"
        raise SkipError(msg)
    clock = local_clock(ctx)
    result = Result("low_battery_shutdowns", window="daily")
    events = []
    if entry := props.get("persist.sys.boot.reason.history"):
        value, index = entry
        for line in value.splitlines():
            if m := _BOOT_ENTRY_RE.match(line.strip()):
                stamp = clock.local(int(m["epoch"]))
                events.append(
                    {
                        "time": _iso(stamp),
                        "reason": m["reason"],
                        "kind": _classify_boot(m["reason"]),
                        "ref": getprop.ref(index) if getprop else "",
                    },
                )
    result.add_table("boots", events)
    if timeline is not None:
        history = timeline.history
        result.add_table(
            "history_markers",
            [
                {
                    "event": cmd,
                    "time": _iso(history.wall(pos)),
                    "ref": history.text.ref(history.records[pos].index),
                }
                for pos, cmd in markers
            ],
        )
    kinds = Counter(e["kind"] for e in events)
    result.metrics = {
        "boot_history_entries": len(events),
        "battery_shutdowns": kinds.get("low battery", 0),
        "thermal_shutdowns": kinds.get("thermal", 0),
        "crash_reboots": kinds.get("crash", 0),
        "history_shutdowns": sum(1 for _, c in markers if c == "SHUTDOWN"),
        "history_starts": sum(1 for _, c in markers if c == "START"),
        "clock_source": clock.source,
    }
    for key in _BOOT_KEYS[1:]:
        if key in props:
            result.metrics[key.replace(".", "_")] = props[key][0]
    _shutdown_findings(ctx, events, getprop, props, result)
    return result


def _collapse_for(ctx: Context, stamp: str | None) -> int | None:
    """Fast low-level steps on the daily_steps day containing ``stamp``."""
    daily = ctx.results.get("daily_steps")
    if daily is None or stamp is None:
        return None
    for row in daily.tables.get("days", []):
        if row.get("start") and row.get("end") and row["start"] <= stamp < row["end"]:
            return row.get("fast_low_steps")
    return None


def _shutdown_findings(
    ctx: Context,
    events: list[dict[str, Any]],
    getprop: Text | None,
    props: dict[str, tuple[str, int]],
    result: Result,
) -> None:
    battery = [e for e in events if e["kind"] == "low battery"]
    evidence = []
    if getprop is not None and "persist.sys.boot.reason.history" in props:
        evidence.append(
            getprop.evidence(props["persist.sys.boot.reason.history"][1]),
        )
    if battery:
        collapse = [_collapse_for(ctx, e["time"]) for e in battery]
        with_collapse = [c for c in collapse if c]
        times = ", ".join(e["time"] or "?" for e in battery[:5])
        summary = (
            f"The boot-reason history holds {len(battery)} low-battery shutdown(s): "
            f"{times}."
        )
        if with_collapse:
            summary += (
                f" The daily step history shows {max(with_collapse)} sub-minute "
                f"1 % steps at or below {LOW_LEVEL_PCT} % on that day: the level "
                "collapsed under load before the shutdown."
            )
        shutdowns = Finding(
            id="low_battery_shutdowns.battery_shutdowns",
            title=f"The phone shut down {len(battery)} time(s) for low battery",
            symptom="battery",
            severity="medium" if with_collapse else "low",
            basis="measured",
            window="daily",
            summary=summary,
            metrics={
                "battery_shutdowns": len(battery),
                "collapse_steps": max(with_collapse) if with_collapse else None,
            },
            evidence=evidence,
            recommendation=(
                "Recharge at 15-20 %; a worn cell cannot deliver its last "
                "~10 % under load. Check battery wear (battery_capacity)."
            ),
            followups=["Check daily_steps for the level before each shutdown."],
        )
        # The shutdown owns the collapse it cites; daily_steps adds the other days.
        collapse_finding = ctx.finding("daily_steps.low_level_collapse")
        if with_collapse and collapse_finding:
            link(shutdowns, collapse_finding)
        result.findings.append(shutdowns)
    crashes = [e for e in events if e["kind"] in {"crash", "thermal", "forced"}]
    if crashes:
        result.findings.append(
            Finding(
                id="low_battery_shutdowns.unexpected_reboots",
                title=f"{len(crashes)} unexpected reboot(s) or thermal shutdown(s)",
                symptom="both",
                severity="medium",
                basis="measured",
                window="daily",
                summary="; ".join(f"{e['time']} {e['reason']}" for e in crashes[:5]),
                metrics={"unexpected": len(crashes)},
                evidence=evidence,
                recommendation=(
                    "Look for kernel panics or watchdog resets in the last kernel "
                    "log and tombstones; for thermal shutdowns, check the thermal "
                    "status and what ran at the time."
                ),
            ),
        )


# ---------------------------------------------------------------------------
# The battery_saver_drain analyzer

_DRAIN_STATS_RE = re.compile(r"^\s*Drain stats:")
_DRAIN_ROW_RE = re.compile(
    r"^\s+(?:(?P<doze>NonDoze|Deep|Light)\s+)?(?P<intr>NonIntr|Intr):"
    r"\s+(?P<m_off>\d+)m\s+(?P<mah_off>\d+)mAh\(\s*(?P<pct_off>\d+)%\)"
    r"\s+(?P<rate_off>[\d,.]+)mAh/h"
    r"\s+(?P<m_on>\d+)m\s+(?P<mah_on>\d+)mAh\(\s*(?P<pct_on>\d+)%\)"
    r"\s+(?P<rate_on>[\d,.]+)mAh/h",
)
_SAVER_STATE_RE = re.compile(r"^\s*Battery Saver is currently: (\w+)")
_SAVER_TIMES_RE = re.compile(r"^\s*Times full enabled: (\d+)")


def _drain_rows(power: Text, start: int) -> tuple[list[dict[str, Any]], int]:
    """Parse the rows after "Drain stats:"; the Doze label is on every other row."""
    rows: list[dict[str, Any]] = []
    doze = ""
    skipped = 0
    for index in range(start + 1, min(start + 12, len(power.lines))):
        line = power.lines[index]
        m = _DRAIN_ROW_RE.match(line)
        if not m:
            if rows and not line.strip():
                break  # a blank line ends the table
            skipped += 1 if rows else 0
            continue
        doze = m["doze"] or doze
        for saver in ("off", "on"):
            minutes = int(m[f"m_{saver}"])
            rate = parse_decimal(m[f"rate_{saver}"])
            rows.append(
                {
                    "doze": doze,
                    "interactive": m["intr"] == "Intr",
                    "saver": saver,
                    "minutes": minutes,
                    "mah": int(m[f"mah_{saver}"]),
                    "level_pct": int(m[f"pct_{saver}"]),
                    "mah_per_h": _r(rate)
                    if minutes >= DRAIN_STATS_MIN_MINUTES
                    else None,
                    "ref": power.ref(index),
                },
            )
    return rows, skipped


@analyzer(
    "battery_saver_drain",
    requires=("power",),
    after=("windows", "discharge_accounting"),
)
def battery_saver_drain(ctx: Context) -> Result:
    """Read the since-boot drain table by Doze state, interaction and saver."""
    power = ctx.sources.get("power")
    if power is None:
        msg = "no dumpsys power"
        raise SkipError(msg)
    start = next((i for i, m in power.find(_DRAIN_STATS_RE)), None)
    if start is None:
        msg = "no 'Drain stats' table in dumpsys power"
        raise SkipError(msg)
    rows, skipped = _drain_rows(power, start)
    if not rows:
        msg = "the 'Drain stats' table has no parsable rows"
        raise SkipError(msg)
    result = Result("battery_saver_drain", window="since_boot")
    minutes = sum(r["minutes"] for r in rows)
    mah = sum(r["mah"] for r in rows)
    saver_minutes = sum(r["minutes"] for r in rows if r["saver"] == "on")
    result.metrics = {
        "minutes": minutes,
        "mah": mah,
        "mah_per_h": _r(60 * mah / minutes) if minutes else None,
        "saver_on_share_pct": pct(saver_minutes, minutes),
    }
    for _, m in power.find(_SAVER_STATE_RE):
        result.metrics["saver_currently"] = m[1]
        break
    for _, m in power.find(_SAVER_TIMES_RE):
        result.metrics["times_full_enabled"] = int(m[1])
        break
    _earlier_boot(ctx, minutes, mah, result)
    result.tables["drain"] = sorted(
        (r for r in rows if r["minutes"] or r["mah"]),
        key=itemgetter("mah"),
        reverse=True,
    )
    result.notes.append(
        "Totals are since boot. Rates for cells under "
        f"{DRAIN_STATS_MIN_MINUTES} min are omitted; use this table for context, "
        "not as the current standby rate.",
    )
    if skipped:
        result.notes.append(f"Skipped {skipped} unparsable drain-table lines.")
    return result


def _earlier_boot(ctx: Context, minutes: int, mah: int, result: Result) -> None:
    """Since-boot totals minus the since-charge totals: the earlier part of the boot."""
    discharge = ctx.results.get("discharge_accounting")
    boot = ctx.windows.boot_time
    start = ctx.windows.since_charge_start
    if discharge is None or boot is None or start is None or boot >= start:
        return
    on_s = discharge.metrics.get("on_battery_s")
    charge_mah = discharge.metrics.get("discharge_mah")
    if not on_s or charge_mah is None:
        return
    earlier_min = minutes - on_s / 60
    earlier_mah = mah - charge_mah
    if earlier_min <= DRAIN_STATS_MIN_MINUTES or earlier_mah < 0:
        return
    result.metrics |= {
        "before_charge_minutes": round(earlier_min),
        "before_charge_mah": earlier_mah,
        "before_charge_mah_per_h": _r(60 * earlier_mah / earlier_min),
    }
    result.notes.append(
        "before_charge_* = since-boot drain minus the since-charge discharge, "
        "i.e. on-battery time between boot and the last full charge (inferred).",
    )


# ---------------------------------------------------------------------------
# The previous_cycle analyzer


@analyzer(
    "previous_cycle",
    requires=("batterystats_checkin_previous",),
    after=("windows", "discharge_accounting"),
)
def previous_cycle(ctx: Context) -> Result:
    """Summarise the previous charge period from a saved ``--checkin`` dump."""
    period = load_checkin_period(ctx, "batterystats_checkin_previous")
    if period is None:
        msg = "the previous-period checkin file has no 'bt' row"
        raise SkipError(msg)
    discharge = _discharge_from_checkin(period)
    v = discharge.values
    on_s = v.get("on_battery_s")
    off_s = v.get("screen_off_s")
    total_realtime = period.value("bt", BT_TOTAL_REALTIME)
    result = Result("previous_cycle", window=_WINDOW_PREVIOUS)
    capacity = load_capacity(ctx).learned_mah
    level_off_mah = (
        (v.get("level_screen_off") or 0) * capacity / _FULL if capacity else None
    )
    radio_ms = period.value("m", M_RADIO_ACTIVE)
    result.metrics = {
        "on_battery_s": _r(on_s),
        "total_realtime_s": _r(total_realtime / 1000) if total_realtime else None,
        "awake_share_pct": pct(v.get("on_battery_uptime_s") or 0, on_s or 0),
        "screen_off_s": _r(off_s),
        "screen_off_awake_share_pct": pct(
            v.get("screen_off_uptime_s") or 0, off_s or 0
        ),
        "screen_on_s": _r(v.get("screen_on_s")),
        "discharge_mah": v.get("discharge_mah"),
        "screen_off_mah": v.get("screen_off_mah"),
        "deep_doze_mah": v.get("deep_doze_mah"),
        "discharge_mah_per_h": per_hour(v.get("discharge_mah"), on_s),
        "screen_off_mah_per_h": per_hour(v.get("screen_off_mah"), off_s),
        "level_screen_off_mah_per_h": per_hour(level_off_mah, off_s),
        "partial_wakelock_s": _r((period.value("m", M_PARTIAL_WL) or 0) / 1000),
        "mobile_radio_active_s": _r((radio_ms or 0) / 1000),
        "mobile_radio_active_count": period.value("m", M_RADIO_COUNT),
        "mobile_radio_share_pct": pct(radio_ms or 0, (on_s or 0) * 1000),
        "power_save_share_pct": pct(v.get("power_save_s") or 0, on_s or 0),
        "connectivity_changes": v.get("connectivity_changes"),
        "estimated_capacity_mah": period.value("bt", BT_ESTIMATED),
        "min_learned_mah": _r((period.value("bt", BT_MIN_LEARNED) or 0) / 1000, 0),
        "max_learned_mah": _r((period.value("bt", BT_MAX_LEARNED) or 0) / 1000, 0),
    }
    start = ctx.windows.since_charge_start
    if start is not None and total_realtime:
        result.metrics["period_start_estimate"] = _iso(
            start - timedelta(milliseconds=total_realtime),
        )
        result.notes.append(
            "period_start_estimate assumes the saved period ended when the "
            "current one began; startClockTime is re-stamped at each reboot.",
        )
    if (v.get("deep_doze_mah") or 0) > (v.get("screen_off_mah") or 0):
        result.notes.append(
            "Deep-doze discharge exceeds screen-off discharge in this period; its "
            "counters are partly inconsistent (often after a reboot).",
        )
    _previous_tables(ctx, period, result)
    current = ctx.results.get("discharge_accounting")
    cur_rate = current.metrics.get("screen_off_mah_per_h") if current else None
    prev_rate = result.metrics["screen_off_mah_per_h"]
    if cur_rate and prev_rate:
        result.metrics["screen_off_rate_vs_current"] = _r(prev_rate / cur_rate, 2)
    _previous_findings(discharge, result)
    return result


def _previous_tables(ctx: Context, period: CheckinPeriod, result: Result) -> None:
    components: dict[str, float] = {}
    uids: dict[str, float] = {}
    for _, f in period.rows.get("pwi", []):
        mah = _float(f, 2)
        if mah is None:
            continue
        target, key = (uids, f[0]) if f[1] == "uid" else (components, f[1])
        target[key] = target.get(key, 0.0) + mah
    result.tables["power_components"] = [
        {"component": c, "modelled_mah": _r(mah)}
        for c, mah in sorted(components.items(), key=itemgetter(1), reverse=True)[:12]
    ]
    result.add_table(
        "power_uids",
        [
            {
                "uid": uid,
                "name": ctx.packages.name(int(uid))
                if uid.lstrip("-").isdigit()
                else uid,
                "modelled_mah": _r(mah),
            }
            for uid, mah in sorted(uids.items(), key=itemgetter(1), reverse=True)
        ],
    )
    kwl = sorted(
        (
            {
                "name": f[0],
                "ms": _int(f, 1) or 0,
                "count": _int(f, 2),
                "ref": period.text.ref(i),
            }
            for i, f in period.rows.get("kwl", [])
        ),
        key=itemgetter("ms"),
        reverse=True,
    )
    result.add_table("kernel_wakelocks", kwl)
    wake = sorted(
        (
            {"reason": f[0], "count": _int(f, 2) or 0}
            for _, f in period.rows.get("wr", [])
        ),
        key=itemgetter("count"),
        reverse=True,
    )
    result.add_table("wake_reasons", wake)
    if wst := period.row("wst"):
        # wst = ms in Wi-Fi states: off, off scanning, on without networks,
        # on disconnected, connected (STA, P2P, STA+P2P), soft AP.
        _, f = wst
        result.metrics["wifi_on_disconnected_s"] = _r((_int(f, 3) or 0) / 1000)
        result.metrics["wifi_connected_s"] = _r(
            sum(_int(f, i) or 0 for i in (4, 5, 6)) / 1000,
        )
    if gmcd := period.row("gmcd"):
        _, f = gmcd
        result.metrics["modem_idle_s"] = _r((_int(f, 0) or 0) / 1000)
        result.metrics["modem_rx_s"] = _r((_int(f, 1) or 0) / 1000)
        result.metrics["modem_mah"] = _r(_float(f, 2))
    result.notes.append(
        "pwi values are batterystats power-model estimates (modelled), not metered.",
    )


def _previous_findings(discharge: _Discharge, result: Result) -> None:
    m = result.metrics
    ratio = m.get("screen_off_rate_vs_current")
    if ratio and ratio >= PREVIOUS_RATE_RATIO:
        result.findings.append(
            Finding(
                id="previous_cycle.heavier_period",
                title=f"The previous charge period drained {ratio}x faster with the "
                "screen off",
                symptom="battery",
                severity="medium",
                basis="measured",
                window=_WINDOW_PREVIOUS,
                summary=(
                    f"Before the last full charge the phone lost "
                    f"{m['screen_off_mah']:.0f} mAh in "
                    f"{fmt_duration(m['screen_off_s'] or 0)} of screen-off time "
                    f"({m['screen_off_mah_per_h']} mAh/h), {ratio}x the current "
                    "period's rate, with the SoC awake "
                    f"{m['screen_off_awake_share_pct']}% of screen-off time. The "
                    "current window is not representative of all usage."
                ),
                metrics={
                    k: m.get(k)
                    for k in (
                        "screen_off_mah_per_h",
                        "screen_off_rate_vs_current",
                        "screen_off_awake_share_pct",
                        "mobile_radio_share_pct",
                    )
                },
                evidence=discharge.evidence[:2],
                recommendation=(
                    "Compare where the phone was in each period (Wi-Fi at home "
                    "versus mobile data); diagnose both regimes."
                ),
            ),
        )
    if (m.get("mobile_radio_share_pct") or 0) >= MOBILE_RADIO_SHARE_PCT:
        result.findings.append(
            Finding(
                id="previous_cycle.mobile_radio_busy",
                title=f"Mobile radio active {m['mobile_radio_share_pct']}% of the "
                "previous period",
                symptom="battery",
                severity="medium",
                basis="measured",
                window=_WINDOW_PREVIOUS,
                summary=(
                    f"The cellular radio was in its active state for "
                    f"{fmt_duration(m['mobile_radio_active_s'] or 0)} over "
                    f"{m['mobile_radio_active_count']} activations in "
                    f"{fmt_duration(m['on_battery_s'] or 0)} on battery. Small, "
                    "frequent packets from always-connected apps keep the radio up."
                ),
                metrics={
                    k: m.get(k)
                    for k in (
                        "mobile_radio_active_s",
                        "mobile_radio_active_count",
                        "mobile_radio_share_pct",
                        "modem_rx_s",
                    )
                },
                evidence=discharge.evidence[:1],
                recommendation=(
                    "Find apps with steady mobile traffic (VPNs, chat, push, "
                    "companion apps) in the per-UID network data; restrict their "
                    "background data or keepalives when on mobile data."
                ),
            ),
        )
    for row in result.tables.get("kernel_wakelocks", []):
        if row["name"] in SUSPEND_BLOCKERS and row["ms"] >= SUSPEND_BLOCKER_MIN_MS:
            held = fmt_duration(row["ms"] / 1000)
            result.findings.append(
                Finding(
                    id="previous_cycle.suspend_blocked",
                    title=f"{row['name']} blocked suspend for {held}",
                    symptom="battery",
                    severity="high",
                    basis="measured",
                    window=_WINDOW_PREVIOUS,
                    summary=(
                        f"The kernel wakelock {row['name']} was held "
                        f"{held} in {row['count']} acquisition(s) "
                        "in the previous period, so the phone could not suspend "
                        "at all in that time."
                    ),
                    metrics={"ms": row["ms"], "count": row["count"]},
                    evidence=[Evidence(row["ref"], row["name"])],
                    recommendation=(
                        "This lock is held while a display stays on (for example a "
                        "car or cast projection display that did not close); check "
                        "the event log for display and projection changes in that "
                        "period."
                    ),
                    # The since-boot SuspendLockout row of the suspend service
                    # shows the same hold when the boot predates the charge.
                    related=["wakelocks.suspend_lockout_since_boot"],
                ),
            )
            break
