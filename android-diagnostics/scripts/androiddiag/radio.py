"""Radio and connectivity analyzers: modem, Wi-Fi roaming, IMS, traffic, scans, VPN.

These analyzers explain the radio side of battery drain:

- ``cellular_radio``: how long the modem was active and for how little data,
  coverage and transmit power, and which UIDs held the radio up.
- ``wifi_roaming``: re-associations and BSSID changes while the phone lay
  still, the firmware's roam triggers, and what the "Connectivity changes"
  counter really counted.
- ``ims_handover``: Wi-Fi calling moving the IMS connection between mobile and
  Wi-Fi after roams, and the mobile-radio time inside those windows.
- ``network_traffic``: packets per UID, network and time bucket; steady
  small-packet flows (keepalives) and large downloads on battery.
- ``background_scanning_sensors_location``: BLE scans, location requests and
  sensor listeners that keep radios or sensors busy in the background.
- ``vpn``: active VPNs; a mesh VPN keeps its peers' heartbeats flowing.

Network names, BSSIDs, IP and MAC addresses and carrier names never appear in
findings or tables: BSSIDs are counted or replaced by labels such as ``AP-3``.
Evidence excerpts are dump lines as they are; ``report.py --redact`` masks
addresses and names in the report.
"""

from __future__ import annotations

import operator
import re
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from itertools import pairwise
from statistics import median
from typing import TYPE_CHECKING, Any

from .battery_history import load_history
from .batterystats import PowerComponent, load_since_charge
from .common import (
    FIRST_APPLICATION_UID,
    PER_USER_RANGE,
    SYSTEM_UIDS,
    fmt_duration,
    iter_logcat,
    load_settings,
    parse_clock_s,
    parse_decimal,
    parse_duration_ms,
    parse_size_bytes,
    parse_uid,
    pct,
    uid_class,
)
from .model import Evidence, Finding, Result, SkipError, analyzer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .battery_history import History, Record, Token
    from .batterystats import SinceCharge
    from .model import Context, Severity
    from .source import Text

# ---------------------------------------------------------------------------
# Thresholds. Each says why it is where it is.

# Connected-mode LTE draws on the order of 100-200 mA against a few mA when
# camped, so a modem held active for a few percent of battery time already
# matters; a third of the time makes the modem a dominant consumer.
RADIO_ACTIVE_LOW_PCT = 3.0
RADIO_ACTIVE_MEDIUM_PCT = 10.0
RADIO_ACTIVE_HIGH_PCT = 30.0
# More than 10 s of radio-active time per packet means single small packets
# hold the radio connected through its inactivity tail (catalogue flag).
MSPP_TINY_TRAFFIC = 10_000
# ...and a UID must have held the radio at least this long to be named.
MSPP_MIN_ACTIVE_S = 60
# Below this many bytes per radio-active second the traffic is signalling or
# keepalives, not transfers.
SMALL_TRAFFIC_BYTES_PER_ACTIVE_S = 2048
# Poor or no signal for this share of battery time raises modem power.
POOR_SIGNAL_PCT = 20.0
# Searching for a network this share of battery time is expensive.
SCANNING_PCT = 5.0
# Top-power transmission this long, and this share of all TX time, points to
# a weak uplink rather than a few bursts.
HIGH_TX_MIN_S = 60
HIGH_TX_SHARE_PCT = 20.0

# A stationary phone should stay on one access point: analysts aimed for fewer
# than ~10 roams per night, and more than ~5 per hour in deep idle means AP
# steering or ping-pong at the edge of several access points.
ROAMS_PER_H_IDLE = 5.0
ROAMS_MIN_COUNT = 10
# Bursts are counted in a sliding two-minute window.
BURST_WINDOW_S = 120
# A probe wakelock this soon after an association belongs to that association.
IRM_MATCH_S = 1.0
# Wi-Fi switched on but not connected this long keeps scanning for networks.
WIFI_NO_NETWORK_PCT = 30.0
WIFI_NO_NETWORK_MIN_S = 3600
# The "Connectivity changes" counter is worth explaining only when it is big.
CONN_CHANGES_MIN = 50
# Share of connectivity events that must re-announce a connected network.
CONN_SAME_STATE_SHARE = 0.9
# A capability update follows the Wi-Fi change that caused it within this time.
CONN_FOLLOW_S = 2.0
# RSSI updates are polled with the screen on; above this share the Wi-Fi
# signal histogram describes screen-on conditions only.
RSSI_SCREEN_ON_SHARE = 0.9

# Short IMS stays on Wi-Fi, repeated, are a handover ping-pong.
IMS_CYCLES_MIN = 3
IMS_SHORT_DWELL_S = 300
# A roam this shortly before Wi-Fi is qualified for IMS counts as its trigger.
ROAM_TO_IWLAN_S = 60
# Window margins for assigning radio activations to handover windows; the
# verified diagnosis showed the share depends on them, so report all three.
IMS_MARGINS_S = (0, 15, 30)
# Above this share (at the widest margin) handovers drive the modem.
IMS_RADIO_SHARE_MEDIUM = 0.3
# The power model prints mAh with three significant digits, so the active-time
# cost it implies may exceed its mobile-radio total by rounding alone.
RADIO_SPLIT_TOLERANCE = 0.05

# Steady app traffic of more than ~1 packet/s each way around the clock can
# keep waking the SoC (catalogue flag); one received packet a minute on
# average is a keepalive worth listing.
STEADY_HIGH_PKTS_PER_S = 1.0
STEADY_LOW_PKTS_PER_S = 1 / 60
# Keepalives and heartbeats are small; bulk transfers average ~1.5 KB.
SMALL_PACKET_BYTES = 400
# A bucket must hold this many received packets to count as "present".
STEADY_MIN_BUCKET_PKTS = 10
# A single-bucket download this large on battery is worth a note.
LARGE_DOWNLOAD_BYTES = 100 * 1024**2
# A 40-byte TCP segment with no payload is a bare ACK or RST; allow options.
BARE_SEGMENT_MAX_BYTES = 60
BARE_SEGMENTS_MIN = 100
# VPN app's own packets per second that indicate constant peer chatter.
VPN_BUSY_PKTS_PER_S = 0.5
# Mesh VPNs route each peer by a host route; this many marks a mesh.
MESH_MIN_PEER_ROUTES = 3

# A BLE scan running this long is continuous rather than occasional.
BLE_LONG_SCAN_S = 3600
# GPS in the background this long since boot is a real cost.
LOCATION_BG_GPS_S = 600
# Location updates faster than this, in the background this long, are costly.
LOCATION_FAST_INTERVAL_S = 60
LOCATION_BG_FAST_S = 3600
# A wakeup sensor held this long in the background keeps waking the SoC.
SENSOR_BG_S = 3600

# ---------------------------------------------------------------------------
# Small shared helpers.

_DUR = r"(?:\d+d\s*)?(?:\d+h\s*)?(?:\d+m\s*)?(?:\d+s\s*)?\d+ms"
_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?"


def _ms(text: str) -> int:
    """Parse a duration that may be a bare ``0``, ``+0ms`` or ``@+6h0m0s0ms``."""
    s = text.strip().lstrip("@")
    return 0 if s.lstrip("+") in {"0", ""} else parse_duration_ms(s)


def _fmt(ts: datetime | None) -> str | None:
    """Format a device wall time for tables."""
    return ts.isoformat(sep=" ", timespec="seconds") if ts else None


def _hms(ts: datetime | None) -> str:
    """Format a device wall time as HH:MM:SS for summaries."""
    return ts.strftime("%H:%M:%S") if ts else "?"


def _uid_name(ctx: Context, uid: int) -> str:
    """Name a UID: the kernel and system UIDs by role, apps by package."""
    app_id = uid % PER_USER_RANGE
    if app_id == 0:
        return "kernel (UID 0)"
    if app_id < FIRST_APPLICATION_UID and app_id in SYSTEM_UIDS:
        return f"{SYSTEM_UIDS[app_id]} (UID {uid})"
    return ctx.packages.name(uid)


def _local(ctx: Context, epoch_s: float) -> datetime | None:
    """Return the phone's local wall time of a Unix time; UTC if the zone is unknown."""
    if (local := ctx.windows.local_from_epoch(epoch_s)) is not None:
        return local
    try:
        return datetime.fromtimestamp(epoch_s, tz=UTC).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _zone_known(ctx: Context) -> bool:
    """Return whether Unix times can be turned into the phone's local time."""
    return ctx.windows.zone is not None or ctx.windows.offset() is not None


def _in_spans(ts: datetime | None, spans: list[tuple[datetime, datetime]]) -> bool:
    """Return whether ``ts`` falls inside any of ``spans``."""
    return ts is not None and any(start <= ts < end for start, end in spans)


# ---------------------------------------------------------------------------
# Battery history: one replay of the parsed history (checkin rows or the text
# dump, see battery_history.load_history) collecting the radio-related events.

# The neighbour-probe wakelock that IpClient takes after each association.
_IRM_TAG = "IpReachabilityMonitor"


@dataclass
class _Mark:
    """A point event in the history, with the device state at that moment."""

    ms: int
    ts: datetime | None
    index: int
    screen_on: bool
    idle: str
    on_battery: bool
    value: str = ""


@dataclass
class _Activation:
    """One +mobile_radio ... -mobile_radio period."""

    start_ms: int
    end_ms: int
    ts: datetime | None
    index: int
    screen_on: bool
    on_battery: bool

    @property
    def seconds(self) -> float:
        """Duration in seconds."""
        return (self.end_ms - self.start_ms) / 1000


@dataclass
class _History:
    """Radio-related facts from the battery history (offsets in ms from reset)."""

    text: Text | None = None
    records: int = 0
    end_ms: int = 0
    anchors: list[tuple[int, datetime]] = field(default_factory=list)
    battery: list[tuple[int, int]] = field(default_factory=list)
    screen_off: list[tuple[int, int, int]] = field(default_factory=list)
    radio: list[_Activation] = field(default_factory=list)
    associations: list[_Mark] = field(default_factory=list)
    conn: list[_Mark] = field(default_factory=list)
    wifi_signal: list[_Mark] = field(default_factory=list)
    irm: list[_Mark] = field(default_factory=list)
    durations: Counter[str] = field(default_factory=Counter)
    high_tx_toggles: int = 0
    unparsed: int = 0
    overflow: bool = False
    # Readable excerpts of cited checkin rows (``9,h,0,+Pr`` -> ``+mobile_radio``).
    excerpts: dict[int, str] = field(default_factory=dict)

    def evidence(self, index: int) -> list[Evidence]:
        """Cite history line ``index``, if the history has a text."""
        if self.text is None:
            return []
        return [self.text.evidence(index, self.excerpts.get(index))]

    def wall(self, ms: int) -> datetime | None:
        """Convert a history offset to device wall time via the TIME anchors."""
        if not self.anchors:
            return None
        pos = bisect_right([a for a, _ in self.anchors], ms) - 1
        anchor_ms, anchor_wall = self.anchors[max(pos, 0)]
        return anchor_wall + timedelta(milliseconds=ms - anchor_ms)

    def battery_windows(self) -> list[tuple[datetime, datetime]]:
        """Return on-battery spans as wall times."""
        spans = [(self.wall(a), self.wall(b)) for a, b in self.battery]
        return [(a, b) for a, b in spans if a is not None and b is not None]


class _Replay:
    """Replay the history records once, tracking the radio-related state."""

    def __init__(self, history: History, fallback_start: datetime | None) -> None:
        anchors = [(t_ms, clock) for _, t_ms, clock in history.anchors]
        if not anchors and fallback_start is not None:
            anchors = [(0, fallback_start)]
        self.h = _History(
            history.text,
            len(history.records),
            anchors=anchors,
            unparsed=history.unparsed_lines,
        )
        self.checkin = history.fmt == "checkin"
        self.record: Record | None = None
        self.plugged = False
        self.screen_on = False
        self.idle = "off"
        self.signal = ""
        self.scanning = False
        self.prev_ms = 0
        self.batt_start = 0
        self.off_start: tuple[int, int] | None = None
        self.radio_open: _Activation | None = None
        self.flags: dict[str, Callable[[bool, int, int], None]] = {
            "plugged": self._plugged,
            "screen": self._screen,
            "mobile_radio": self._radio,
            "phone_scanning": self._scanning,
            "cellular_high_tx_power": self._high_tx,
        }
        self.states: dict[str, Callable[[str, int, int], None]] = {
            "device_idle": self._idle,
            "wifi_suppl": self._suppl,
            "wifi_signal_strength": self._wifi_signal,
            "phone_signal_strength": self._phone_signal,
        }

    def run(self, history: History) -> _History:
        """Apply every record and return the collected facts."""
        for record in history.records:
            self._advance(record.t_ms)
            if record.command:
                self.h.overflow = self.h.overflow or record.command == "OVERFLOW"
                continue
            # Events carry the state before the changes of their own record.
            ms, index = record.t_ms, record.index
            self.record = record
            self.h.conn += [
                self._mark(ms, index, f"{t.uid}:{t.value}")
                for t in record.tokens
                if t.name == "conn" and t.uid is not None and t.value is not None
            ]
            if any(_is_probe(t) for t in record.tokens):
                self.h.irm.append(self._mark(ms, index))
            for token in record.tokens:
                self._token(token, ms, index)
        self._finish()
        return self.h

    def _token(self, token: Token, ms: int, index: int) -> None:
        if token.sign and (handler := self.flags.get(token.name)):
            handler(token.sign == "+", ms, index)
        elif (
            not token.sign
            and token.value is not None
            and (state := self.states.get(token.name))
        ):
            state(token.value, ms, index)

    def _mark(self, ms: int, index: int, value: str = "") -> _Mark:
        self._keep_excerpt(index, ms)
        return _Mark(
            ms,
            self.h.wall(ms),
            index,
            self.screen_on,
            self.idle,
            not self.plugged,
            value,
        )

    def _keep_excerpt(self, index: int, ms: int) -> None:
        """Decode a checkin row that may be cited into text-dump names."""
        if self.checkin and self.record and index not in self.h.excerpts:
            tokens = " ".join(map(_token_text, self.record.tokens))
            self.h.excerpts[index] = f"{_hms(self.h.wall(ms))} {tokens}"

    def _advance(self, ms: int) -> None:
        delta = ms - self.prev_ms
        self.prev_ms = max(ms, self.prev_ms)
        if delta <= 0 or self.plugged:
            return
        d = self.h.durations
        d["battery"] += delta
        d["screen_off"] += 0 if self.screen_on else delta
        d[f"idle_{self.idle}"] += delta
        if self.radio_open:
            d["radio"] += delta
            d["radio_screen_off"] += 0 if self.screen_on else delta
        d["phone_scanning"] += delta if self.scanning else 0
        if self.signal:
            d[f"signal_{self.signal}"] += delta

    def _plugged(self, on: bool, ms: int, index: int) -> None:
        if on and not self.plugged:
            if ms > self.batt_start:
                self.h.battery.append((self.batt_start, ms))
            self._close_off(ms)
        elif not on and self.plugged:
            self.batt_start = ms
            if not self.screen_on:
                self.off_start = (ms, index)
        self.plugged = on

    def _screen(self, on: bool, ms: int, index: int) -> None:
        if on:
            self._close_off(ms)
        elif self.screen_on and not self.plugged:
            self.off_start = (ms, index)
        self.screen_on = on

    def _close_off(self, ms: int) -> None:
        if self.off_start and ms > self.off_start[0]:
            self.h.screen_off.append((self.off_start[0], ms, self.off_start[1]))
        self.off_start = None

    def _radio(self, on: bool, ms: int, index: int) -> None:
        if on and self.radio_open is None:
            self._keep_excerpt(index, ms)
            self.radio_open = _Activation(
                ms,
                ms,
                self.h.wall(ms),
                index,
                self.screen_on,
                not self.plugged,
            )
        elif not on and self.radio_open is not None:
            self.radio_open.end_ms = ms
            self.h.radio.append(self.radio_open)
            self.radio_open = None

    def _scanning(self, on: bool, _ms: int, _index: int) -> None:
        self.scanning = on

    def _high_tx(self, on: bool, _ms: int, _index: int) -> None:
        if on and not self.plugged:
            self.h.high_tx_toggles += 1

    def _idle(self, value: str, _ms: int, _index: int) -> None:
        self.idle = value

    def _suppl(self, value: str, ms: int, index: int) -> None:
        if value == "associated":
            self.h.associations.append(self._mark(ms, index))

    def _wifi_signal(self, value: str, ms: int, index: int) -> None:
        self.h.wifi_signal.append(self._mark(ms, index, value))

    def _phone_signal(self, value: str, _ms: int, _index: int) -> None:
        self.signal = value

    def _finish(self) -> None:
        self.h.end_ms = self.prev_ms
        if self.radio_open is not None:
            self.radio_open.end_ms = self.prev_ms
            self.h.radio.append(self.radio_open)
        if not self.plugged:
            if self.prev_ms > self.batt_start:
                self.h.battery.append((self.batt_start, self.prev_ms))
            self._close_off(self.prev_ms)


def _token_text(token: Token) -> str:
    """Write a history token the way the text dump prints it."""
    if token.value is None:
        return f"{token.sign}{token.name}"
    value = f'{token.uid}:"{token.value}"' if token.uid else token.value
    return f"{token.sign}{token.name}={value}"


def _is_probe(token: Token) -> bool:
    """Return whether ``token`` acquires the IpClient neighbour-probe wakelock."""
    return (
        token.sign == "+"
        and token.name == "wake_lock"
        and (token.value or "").startswith(_IRM_TAG)
    )


def _history(ctx: Context) -> _History:
    """Replay the battery history once per run, or return an empty history."""

    def build() -> _History:
        history = load_history(ctx)
        if history is None:
            return _History()
        return _Replay(history, ctx.windows.since_charge_start).run(history)

    return ctx.sources.memo("radio_history", build)


def _battery_spans(ctx: Context, hist: _History) -> list[tuple[datetime, datetime]]:
    """On-battery wall-time spans: from the history, else from ``ctx.windows``."""
    if spans := hist.battery_windows():
        return spans
    span = ctx.windows.battery_span()
    return [span] if span else []


# ---------------------------------------------------------------------------
# batterystats "since last charge": summary block, power model, per-UID lines.


@dataclass
class _Val:
    """One summary value: a duration with share and count, or a number."""

    index: int
    ms: int | None = None
    pct: float | None = None
    count: int | None = None
    value: float | None = None


@dataclass
class _Uid:
    """Per-UID radio facts from the since-charge UID blocks."""

    net: dict[str, int] = field(default_factory=dict)
    net_index: dict[str, int] = field(default_factory=dict)
    radio_ms: int = 0
    radio_count: int = 0
    mspp: int | None = None
    ble_ms: int = 0
    ble_count: int = 0
    ble_results: int | None = None
    ble_running: bool = False
    ble_index: int | None = None
    sensors: list[tuple[str, int, int, int]] = field(default_factory=list)


_SUM_HEADER_RE = re.compile(r"^(?P<ind>\s*)(?P<label>\S[^:]*):\s*$")
_SUM_DUR_RE = re.compile(
    rf"^(?P<ind>\s*)(?P<label>\S[^:]*?):?\s+(?P<dur>{_DUR})\s*"
    r"(?:\((?P<pct>[\d.,]+)%\))?\s*(?:(?P<n>\d+)x)?\s*$",
)
_SUM_MAH_RE = re.compile(r"^(?P<ind>\s*)(?P<label>\S[^:]*): (?P<v>[\d.,]+)\s*mAh\s*$")
_SUM_SIZE_RE = re.compile(
    r"^(?P<ind>\s*)(?P<label>\S[^:]*): (?P<v>[\d.,]+\s*[KMG]?B)\s*$"
)
_SUM_INT_RE = re.compile(r"^(?P<ind>\s*)(?P<label>\S[^:]*): (?P<v>\d+)\s*$")
_MSPP_RE = re.compile(
    r"^\s+Uid (?P<uid>\S+): (?P<mspp>\d+) \((?P<pkts>\d+) packets over "
    r"(?P<dur>.+?)\) (?P<n>\d+)x",
)
_UID_HEADER_RE = re.compile(r"^  (?P<uid>\d+|u\d+[ais]\d+):$")
_NET_RE = re.compile(
    r"^\s+(?P<kind>Wi-Fi|Mobile) network: (?P<rxb>[\d.,]+\s*[KMG]?B) received, "
    r"(?P<txb>[\d.,]+\s*[KMG]?B) sent \(packets (?P<rxp>\d+) received, "
    r"(?P<txp>\d+) sent\)",
)
_RADIO_ACTIVE_RE = re.compile(
    rf"^\s+Mobile radio active: (?P<dur>{_DUR}) \((?P<pct>[\d.,]+)%\) "
    r"(?P<n>\d+)x @ (?P<mspp>\d+) mspp",
)
_BLE_RE = re.compile(
    rf"^\s+Bluetooth Scan \(total actual realtime\): (?P<dur>{_DUR})\s+"
    r"\((?P<n>\d+) times\)(?P<running> \(currently running\))?",
)
_BLE_RESULTS_RE = re.compile(r"^\s+Bluetooth Scan Results: (?P<n>\d+)")
_SENSOR_RE = re.compile(
    rf"^\s+Sensor (?P<h>\S+): (?:(?P<blamed>{_DUR}) blamed realtime, )?"
    rf"(?P<real>{_DUR}) realtime \((?P<n>\d+) times\)"
    rf"(?:, (?P<bg>{_DUR}) background \((?P<bgn>\d+) times\))?",
)
# Sections of the block: the summary runs up to the power model; of the
# sections after it only the per-app ms-per-packet list is read here.
_MODE_MARKERS = {
    "Estimated power use (mAh):": "other",
    "Per-app mobile ms per packet:": "mspp",
    "All kernel wake locks:": "other",
    "All partial wake locks:": "other",
    "All wakeup reasons:": "other",
}


class _Charged:
    """The radio view of the since-charge block (see ``load_since_charge``).

    The shared parse gives the power model, the kernel wakelocks and the UID
    blocks; this adds the indented summary (cellular and Wi-Fi statistics) as
    label paths, the per-app ms-per-packet list and each UID's radio lines.
    """

    def __init__(self, since: SinceCharge) -> None:
        self.since = since
        self.text = since.text
        self.entries: list[tuple[tuple[str, ...], _Val]] = []
        self.mspp: dict[int, tuple[int, int, int]] = {}
        self.uids: dict[int, _Uid] = {}
        self._stack: list[tuple[int, str]] = []
        self.unparsed = 0
        mode = "summary"
        for i, line in since.lines():
            if (marker := _MODE_MARKERS.get(line.strip())) is not None:
                mode = marker
            elif _UID_HEADER_RE.match(line):
                mode = "other"
            elif mode != "other":
                handler = self._summary if mode == "summary" else self._mspp
                self._parse(handler, i, line)
        for uid, lines in since.uid_blocks.items():
            handler = partial(_uid_line, self.uids.setdefault(uid, _Uid()))
            for i, line in lines:
                self._parse(handler, i, line)

    def _parse(self, handler: Callable[[int, str], None], i: int, line: str) -> None:
        """Apply ``handler``; count lines whose values do not parse."""
        try:
            handler(i, line)
        except ValueError:
            self.unparsed += 1

    # -- lookups --------------------------------------------------------------
    def leaf(self, label: str) -> _Val | None:
        """Return the first summary value whose own label is ``label``."""
        return next((v for path, v in self.entries if path[-1] == label), None)

    def children(self, header: str) -> list[tuple[str, _Val]]:
        """Return ``(label, value)`` for summary values directly under ``header``."""
        return [
            (path[-1], v)
            for path, v in self.entries
            if len(path) > 1 and path[-2] == header
        ]

    def component(self, name: str) -> PowerComponent | None:
        """Return a power-model component on battery, if present.

        Android 15+ repeats the components per power state after the
        ``Global`` lines, which also count time on the charger: then the
        ``on battery`` states are summed, without a duration.
        """
        power = self.since.power
        found = power.global_components.get(name) if power else None
        if power is None or found is None:
            return None
        states = [
            comps[name]
            for label, comps in power.state_components.items()
            if label.split(",", 1)[0].strip() == "on battery" and name in comps
        ]
        if not states:
            return found
        # Rounded to undo float noise in sums of three-digit values.
        mah = round(sum(c.mah for c in states), 6)
        apps = round(sum(c.apps_mah for c in states), 6)
        return PowerComponent(name, mah, apps, None, found.index)

    # -- line handlers ---------------------------------------------------------
    def _path(self, indent: int, label: str) -> tuple[str, ...]:
        while self._stack and self._stack[-1][0] >= indent:
            self._stack.pop()
        return (*(name for _, name in self._stack), label.strip())

    def _summary(self, i: int, line: str) -> None:
        if m := _SUM_DUR_RE.match(line):
            pct = parse_decimal(m["pct"]) if m["pct"] else None
            n = int(m["n"]) if m["n"] else None
            val = _Val(i, ms=parse_duration_ms(m["dur"]), pct=pct, count=n)
        elif m := _SUM_MAH_RE.match(line):
            val = _Val(i, value=parse_decimal(m["v"]))
        elif m := _SUM_SIZE_RE.match(line):
            val = _Val(i, value=parse_size_bytes(m["v"]))
        elif m := _SUM_INT_RE.match(line):
            val = _Val(i, value=int(m["v"]))
        elif m := _SUM_HEADER_RE.match(line):
            path = self._path(len(m["ind"]), m["label"])
            self._stack.append((len(m["ind"]), path[-1]))
            return
        else:
            return
        self.entries.append((self._path(len(m["ind"]), m["label"]), val))

    def _mspp(self, i: int, line: str) -> None:
        if m := _MSPP_RE.match(line):
            self.mspp[parse_uid(m["uid"])] = (int(m["mspp"]), int(m["pkts"]), i)


def _uid_line(u: _Uid, i: int, line: str) -> None:
    """Fold one line of a since-charge UID block into ``u``."""
    if m := _NET_RE.match(line):
        kind = "wifi" if m["kind"] == "Wi-Fi" else "mobile"
        u.net[f"{kind}_rx_bytes"] = parse_size_bytes(m["rxb"])
        u.net[f"{kind}_tx_bytes"] = parse_size_bytes(m["txb"])
        u.net[f"{kind}_rx_pkts"] = int(m["rxp"])
        u.net[f"{kind}_tx_pkts"] = int(m["txp"])
        u.net_index[kind] = i
    elif m := _RADIO_ACTIVE_RE.match(line):
        u.radio_ms, u.radio_count = parse_duration_ms(m["dur"]), int(m["n"])
        u.mspp = int(m["mspp"])
    elif m := _BLE_RE.match(line):
        u.ble_ms, u.ble_count = parse_duration_ms(m["dur"]), int(m["n"])
        u.ble_running, u.ble_index = bool(m["running"]), i
    elif m := _BLE_RESULTS_RE.match(line):
        u.ble_results = int(m["n"])
    elif m := _SENSOR_RE.match(line):
        bg = parse_duration_ms(m["bg"]) if m["bg"] else 0
        u.sensors.append((m["h"], parse_duration_ms(m["real"]), bg, i))


def _charged(ctx: Context) -> _Charged | None:
    """Return the radio view of the since-charge statistics, or None if absent."""

    def build() -> _Charged | None:
        since = load_since_charge(ctx)
        return _Charged(since) if since else None

    return ctx.sources.memo("radio_since_charge", build)


def _on_battery_s(ctx: Context, hist: _History | None = None) -> float | None:
    """Seconds on battery since the last charge, from windows or the history."""
    if ctx.windows.on_battery_s:
        return ctx.windows.on_battery_s
    if hist is not None and hist.durations["battery"]:
        return hist.durations["battery"] / 1000
    return None


def _parse_notes(result: Result, hist: _History, stats: _Charged | None) -> None:
    """Note skipped lines and an overflowed history (counts become lower bounds)."""
    if hist.unparsed:
        result.notes.append(
            f"Battery history: {hist.unparsed} unreadable lines skipped."
        )
    if hist.overflow:
        result.notes.append(
            "The battery history overflowed: event counts are lower bounds.",
        )
    if stats and stats.unparsed:
        result.notes.append(
            f"batterystats: {stats.unparsed} lines with unreadable values skipped.",
        )


# ---------------------------------------------------------------------------
# netstats: per-UID traffic buckets (shared by several analyzers).

_IDENT_RE = re.compile(
    r"^\s+ident=\[(?P<ident>.*)\] uid=(?P<uid>-?\d+) set=(?P<set>\w+) tag=(?P<tag>\w+)",
)
_IFACE_RE = re.compile(r"^\s+iface=(?P<iface>\S+) ident=\[(?P<ident>.*)\]")
_BUCKET_DUR_RE = re.compile(r"bucketDuration=(?P<s>\d+)")
_BUCKET_RE = re.compile(
    r"^\s+st=(?P<st>\d+) rb=(?P<rb>\d+) rp=(?P<rp>\d+) tb=(?P<tb>\d+) tp=(?P<tp>\d+)",
)
_TYPE_RE = re.compile(r"\btype=(?P<t>-?\d+)")
_NET_TYPES = {0: "mobile", 1: "wifi", 17: "vpn", 7: "bluetooth", 9: "ethernet"}


def _net_kind(ident: str) -> str:
    """Classify a netstats ident: wifi, vpn, mobile or mobile_unmetered.

    An unmetered, non-default mobile ident is a special-purpose connection,
    typically the IMS one used for VoLTE and Wi-Fi calling.
    """
    m = _TYPE_RE.search(ident)
    kind = _NET_TYPES.get(int(m["t"]) if m else -1, "other")
    if (
        kind == "mobile"
        and "metered=false" in ident
        and "defaultNetwork=false" in ident
    ):
        return "mobile_unmetered"
    return kind


@dataclass
class _NetStats:
    """The ``UID stats`` section of ``dumpsys netstats``, summed over sets."""

    text: Text
    bucket_s: int = 0
    cells: dict[tuple[str, int, int], list[int]] = field(default_factory=dict)
    first_index: dict[tuple[str, int], int] = field(default_factory=dict)
    ifaces: list[tuple[str, str]] = field(default_factory=list)


def _parse_netstats(text: Text) -> _NetStats:
    """Parse active interfaces and per-UID bucket rows (UID stats only)."""
    stats = _NetStats(text)
    section, key = "", None
    for i, line in enumerate(text.lines):
        stripped = line.strip()
        if stripped.endswith(":") and not line.startswith(" "):
            section = stripped
        elif section == "Active interfaces:" and (m := _IFACE_RE.match(line)):
            stats.ifaces.append((m["iface"], _net_kind(m["ident"])))
        elif section != "UID stats:":
            continue
        elif m := _IDENT_RE.match(line):
            uid = int(m["uid"])
            key = (_net_kind(m["ident"]), uid) if uid >= 0 else None
            if key:
                stats.first_index.setdefault(key, i)
        elif m := _BUCKET_DUR_RE.search(line):
            stats.bucket_s = stats.bucket_s or int(m["s"])
        elif key and (m := _BUCKET_RE.match(line)):
            cell = stats.cells.setdefault((*key, int(m["st"])), [0, 0, 0, 0])
            for j, name in enumerate(("rb", "rp", "tb", "tp")):
                cell[j] += int(m[name])
    return stats


def _netstats(ctx: Context) -> _NetStats | None:
    """Return the parsed netstats dump (once per run), or None if absent."""

    def build() -> _NetStats | None:
        text = ctx.sources.get("netstats")
        return _parse_netstats(text) if text else None

    return ctx.sources.memo("radio_netstats", build)


def _buckets_in(
    ctx: Context,
    net: _NetStats,
    spans: list[tuple[datetime, datetime]],
) -> list[int]:
    """Return bucket start epochs that overlap any on-battery span."""
    width = timedelta(seconds=net.bucket_s or 7200)
    used = []
    for st in sorted({st for _, _, st in net.cells}):
        local = _local(ctx, st)
        if local and any(local < end and local + width > start for start, end in spans):
            used.append(st)
    return used


# ---------------------------------------------------------------------------
# cellular_radio

_LEVELS = ("none", "poor", "moderate", "good", "great")
_BACKGROUND_REQUEST_RE = re.compile(r"NetworkRequest \[ (?P<kind>[A-Z_]+) id=")
_NAI_RE = re.compile(
    r"^\s*NetworkAgentInfo\{network\{(?P<net>\d+)\}.*?ni\{(?P<type>[A-Z_]+)"
    r"(?:\[(?P<sub>[^\]]*)\])? (?P<state>[A-Z_]+) extra: (?P<extra>[^}]*)\}"
    r"(?P<rest>.*)$",
)


def _level_shares(entries: list[tuple[str, _Val]]) -> dict[str, float]:
    """Map signal-level labels such as 'good (-108dBm to -98dBm)' to percent."""
    return {
        label.split()[0]: v.pct
        for label, v in entries
        if v.pct is not None and label.split()[0] in _LEVELS
    }


def _cell_counters(stats: _Charged, result: Result) -> None:
    """Modem time split, TX power, coverage, RAT and data from the summary."""
    m = result.metrics
    active = stats.leaf("Cellular kernel active time") or stats.leaf(
        "Mobile radio active time",
    )
    if active and active.ms is not None:
        m["radio_active_s"] = round(active.ms / 1000, 1)
        m["radio_active_pct"] = active.pct
        if active.count is not None:
            m["radio_active_count"] = active.count
    if (unknown := stats.leaf("Mobile radio active unknown time")) and unknown.ms:
        m["radio_active_unknown_s"] = round(unknown.ms / 1000, 1)
    for label in ("Sleep", "Idle", "Rx"):
        if (v := stats.leaf(f"Cellular {label} time")) and v.pct is not None:
            m[f"modem_{label.lower()}_pct"] = v.pct
    tx = {label: v.ms or 0 for label, v in stats.children("Cellular Tx time")}
    if tx:
        m["modem_tx_s"] = round(sum(tx.values()) / 1000, 1)
        m["modem_tx_by_level_s"] = {k: round(v / 1000, 1) for k, v in tx.items()}
    levels = _level_shares(
        stats.children("Cellular Rx signal strength (RSRP)")
        or stats.children("Phone signal levels"),
    )
    if levels:
        m["signal_level_pct"] = levels
    rats = stats.children("Cellular Radio Access Technology") or stats.children(
        "Radio types",
    )
    if rats:
        m["rat_pct"] = {label: v.pct for label, v in rats if v.pct is not None}
    if (scan := stats.leaf("Signal scanning time")) and scan.ms is not None:
        m["signal_scanning_s"] = round(scan.ms / 1000, 1)
    _cell_data(stats, m)


def _cell_data(stats: _Charged, m: dict[str, Any]) -> None:
    """Cellular data volume, the modem's modelled drain and the power-model split."""
    for label, key in (
        ("Cellular data received", "cellular_rx_bytes"),
        ("Cellular data sent", "cellular_tx_bytes"),
        ("Cellular packets received", "cellular_rx_packets"),
        ("Cellular packets sent", "cellular_tx_packets"),
        ("Cellular Battery drain", "modem_modelled_mah"),
    ):
        if (v := stats.leaf(label)) and v.value is not None:
            m[key] = v.value
    if mr := stats.component("mobile_radio"):
        m["mobile_radio_modelled_mah"] = mr.mah
        m["mobile_radio_apps_modelled_mah"] = mr.apps_mah
        m["mobile_radio_unattributed_modelled_mah"] = round(mr.mah - mr.apps_mah, 2)
        m.update(_radio_split(stats))


def _radio_split(stats: _Charged) -> dict[str, float]:
    """Split the modelled mobile-radio mAh the way the power model built it.

    AOSP MobileRadioPowerCalculator spreads one active-time cost over all
    radio-active time: each app pays for its own active time, the rest of the
    active time is billed to no app, and what remains of the total is the
    modem idling or asleep (standby camping). Returns no values when the
    numbers do not fit that model, as with measured modem energy.
    """
    power = stats.since.power
    mr = power.global_components.get("mobile_radio") if power else None
    # Durations cover all power states, so per-state dumps cannot be split.
    if power is None or mr is None or not mr.apps_mah or power.state_components:
        return {}
    app_s = sum(u.durations.get("mobile_radio", 0.0) for u in power.uids.values())
    if not app_s:
        app_s = sum(u.radio_ms for u in stats.uids.values()) / 1000
    if not app_s:
        return {}
    active_s = mr.duration_s
    summary = stats.leaf("Cellular kernel active time") or stats.leaf(
        "Mobile radio active time"
    )
    if active_s is None and summary is not None and summary.ms is not None:
        active_s = summary.ms / 1000
    active_s = max(active_s or 0.0, app_s)
    active_mah = mr.apps_mah * active_s / app_s
    if active_mah > mr.mah * (1 + RADIO_SPLIT_TOLERANCE):
        return {}
    return {
        "mobile_radio_active_s_modelled": round(active_s, 1),
        "mobile_radio_app_active_s_modelled": round(app_s, 1),
        "mobile_radio_active_modelled_mah": round(active_mah, 1),
        "mobile_radio_unattributed_active_modelled_mah": round(
            active_mah - mr.apps_mah, 1
        ),
        "mobile_radio_inactive_modelled_mah": round(max(mr.mah - active_mah, 0.0), 1),
    }


def _cell_uids(ctx: Context, stats: _Charged, result: Result) -> None:
    """Per-UID mobile radio time, packets and ms-per-packet."""
    rows: list[dict[str, Any]] = []
    for uid, u in stats.uids.items():
        if not (
            u.radio_ms or u.net.get("mobile_rx_pkts") or u.net.get("mobile_tx_pkts")
        ):
            continue
        mspp = stats.mspp.get(uid)
        power = stats.since.power.uids.get(uid) if stats.since.power else None
        rows.append(
            {
                "uid": uid,
                "name": _uid_name(ctx, uid),
                "radio_active_s": round(u.radio_ms / 1000, 1),
                "activations": u.radio_count,
                "ms_per_packet": mspp[0] if mspp else u.mspp,
                "mobile_rx_packets": u.net.get("mobile_rx_pkts", 0),
                "mobile_tx_packets": u.net.get("mobile_tx_pkts", 0),
                "mobile_rx_bytes": u.net.get("mobile_rx_bytes", 0),
                "mobile_tx_bytes": u.net.get("mobile_tx_bytes", 0),
                "mobile_radio_modelled_mah": (
                    power.components.get("mobile_radio") if power else None
                ),
            }
        )
    rows.sort(key=lambda r: -r["radio_active_s"])
    result.add_table("uid_mobile_radio", rows)


def _cell_history(hist: _History, result: Result) -> None:
    """Radio activations, screen-off radio time and TX-power toggles."""
    if not hist.records:
        return
    m = result.metrics
    on_batt = [a for a in hist.radio if a.on_battery]
    m["radio_activations_total"] = len(hist.radio)
    m["radio_activations_on_battery"] = len(on_batt)
    m["radio_active_on_battery_min"] = round(sum(a.seconds for a in on_batt) / 60, 2)
    m["radio_active_screen_off_min"] = round(
        hist.durations["radio_screen_off"] / 60_000, 2
    )
    m["high_tx_power_toggles_on_battery"] = hist.high_tx_toggles
    battery_ms = hist.durations["battery"]
    shares = {
        level: pct(hist.durations[f"signal_{level}"], battery_ms)
        for level in _LEVELS
        if hist.durations[f"signal_{level}"]
    }
    if shares:
        m["history_signal_level_pct"] = shares
    if hist.durations["phone_scanning"]:
        m["phone_scanning_s"] = round(hist.durations["phone_scanning"] / 1000, 1)
    longest = sorted(on_batt, key=lambda a: -a.seconds)
    result.add_table(
        "longest_radio_activations",
        [
            {
                "start": _fmt(a.ts),
                "duration_s": round(a.seconds, 1),
                "screen": "on" if a.screen_on else "off",
                "ref": hist.text.ref(a.index) if hist.text else None,
            }
            for a in longest
        ],
    )
    if hist.high_tx_toggles:
        result.notes.append(
            "'+cellular_high_tx_power' toggles in the history are an accounting "
            "artifact; use the TX power-level times instead.",
        )


def _mobile_bearers(ctx: Context, result: Result) -> None:
    """Whether 'mobile data always on' keeps an idle internet bearer up."""
    settings = load_settings(ctx)
    if settings and (always := settings.value("mobile_data_always_on", "global")):
        result.metrics["mobile_data_always_on"] = always == "1"
    conn = ctx.sources.get("connectivity")
    if conn is None:
        return
    kinds: Counter[str] | None = None
    for line in conn.lines:
        if m := _NAI_RE.match(line):
            is_internet = m["type"] == "MOBILE" and "internet" in m["extra"]
            kinds = Counter() if is_internet else None
            if is_internet:
                result.metrics["mobile_internet_requests"] = kinds
        elif kinds is not None and (r := _BACKGROUND_REQUEST_RE.search(line)):
            kinds[r["kind"]] += 1
    requests = result.metrics.get("mobile_internet_requests")
    if requests is not None:
        result.metrics["mobile_internet_requests"] = dict(requests)
        result.metrics["mobile_internet_background_only"] = (
            requests.get("REQUEST", 0) == 0
            and requests.get("BACKGROUND_REQUEST", 0) > 0
        )


def _mobile_idents(ctx: Context, hist: _History, result: Result) -> None:
    """Which mobile connection carried the kernel's (UID 0) packets on battery."""
    net = _netstats(ctx)
    spans = _battery_spans(ctx, hist)
    if net is None or not _zone_known(ctx) or not spans:
        return
    used = set(_buckets_in(ctx, net, spans))
    by_kind: Counter[str] = Counter()
    for (kind, uid, st), cell in net.cells.items():
        if uid == 0 and st in used and kind.startswith("mobile"):
            by_kind[kind] += cell[1] + cell[3]
    if by_kind:
        result.metrics["kernel_mobile_packets_by_connection"] = dict(by_kind)


def _radio_active(m: dict[str, Any], on_battery_s: float | None) -> tuple[float, float]:
    """Return (active seconds, percent of battery time) from summary or history."""
    active_s = m.get("radio_active_s")
    if active_s is None and "radio_active_on_battery_min" in m:
        active_s = m["radio_active_on_battery_min"] * 60
    share = m.get("radio_active_pct")
    if share is None and active_s is not None:
        share = pct(active_s, on_battery_s)
    return active_s or 0.0, share or 0.0


def _radio_finding(
    ctx: Context,
    stats: _Charged | None,
    hist: _History,
    result: Result,
) -> Finding | None:
    """Report a modem held active for little data or by single tiny packets."""
    m = result.metrics
    active_s, share = _radio_active(m, _on_battery_s(ctx, hist))
    known = "cellular_rx_bytes" in m
    data = m.get("cellular_rx_bytes", 0) + m.get("cellular_tx_bytes", 0)
    per_s = data / active_s if active_s else 0.0
    tiny = [
        r
        for r in result.tables.get("uid_mobile_radio", [])
        if (r["ms_per_packet"] or 0) >= MSPP_TINY_TRAFFIC
        and r["radio_active_s"] >= MSPP_MIN_ACTIVE_S
    ]
    small = share >= RADIO_ACTIVE_LOW_PCT and (
        not known or per_s < SMALL_TRAFFIC_BYTES_PER_ACTIVE_S
    )
    if not (small or tiny):
        return None
    severity = (
        "high"
        if share >= RADIO_ACTIVE_HIGH_PCT
        else "medium"
        if share >= RADIO_ACTIVE_MEDIUM_PCT
        else "low"
    )
    volume = (
        f"for {data / 1024:.0f} KB of cellular data ({per_s:.0f} B per active second)"
        if known
        else "(cellular data volume not reported)"
    )
    summary = (
        f"The mobile radio was active {active_s / 60:.1f} min ({share:.1f}% of battery "
        f"time) {volume}."
    )
    summary += "".join(
        f" The radio was held {r['radio_active_s']:.0f} s by {r['name']} for "
        f"{r['mobile_rx_packets'] + r['mobile_tx_packets']} packets "
        f"({r['ms_per_packet']} ms per packet)."
        for r in tiny[:3]
    )
    summary += _power_sentence(m) + _bearer_sentence(m)
    if "radio_activations_on_battery" in m:
        summary += (
            f" The history shows {m['radio_activations_on_battery']} activations on "
            f"battery, {m['radio_active_screen_off_min']} min with the screen off."
        )
    return Finding(
        id="cellular_radio.active_for_little_data",
        title="Mobile radio kept active by small amounts of traffic",
        symptom="battery",
        severity=severity,
        basis="measured",
        window="on_battery",
        summary=summary,
        metrics={
            "radio_active_s": round(active_s, 1),
            "radio_active_pct": share,
            "cellular_bytes": data,
            "tiny_traffic_uids": [r["name"] for r in tiny],
        },
        evidence=_radio_evidence(stats, hist, tiny),
        recommendation=(
            "Find what sends small packets over mobile data: check per-app mobile data "
            "use (Settings > Network & internet > SIMs > App data usage) and restrict "
            "background data for chatty apps. If Wi-Fi calling or a VPN is active, "
            "check the ims_handover and vpn findings: IMS handovers and VPN heartbeats "
            "are common causes."
        ),
        followups=[
            (
                "Pair each +mobile_radio with -mobile_radio in the battery history and "
                "check the screen and Wi-Fi state at each start."
            ),
            (
                "Check in dumpsys netstats which mobile connection (internet or the "
                "unmetered IMS one) carried the packets."
            ),
            "Compare mobile radio active time over a day with Wi-Fi calling off.",
        ],
    )


def _power_sentence(m: dict[str, Any]) -> str:
    """Say how much of the modelled radio cost follows traffic."""
    if "mobile_radio_inactive_modelled_mah" in m:
        return (
            f" The power model bills {m['mobile_radio_modelled_mah']} mAh to the "
            f"mobile radio: {m['mobile_radio_active_modelled_mah']} mAh for "
            f"radio-active time ({m['mobile_radio_apps_modelled_mah']} mAh billed to "
            f"apps, {m['mobile_radio_unattributed_active_modelled_mah']} mAh to "
            "active time no app was billed for) and "
            f"{m['mobile_radio_inactive_modelled_mah']} mAh for the modem idling or "
            "asleep, the standby cost that less traffic does not reduce."
        )
    if "mobile_radio_apps_modelled_mah" in m:
        return (
            f" The power model bills {m['mobile_radio_modelled_mah']} mAh to the "
            f"mobile radio, of which {m['mobile_radio_apps_modelled_mah']} mAh is "
            "billed to apps; the rest is radio-active time no app was billed for "
            "plus the modem's idle and sleep cost."
        )
    return ""


def _bearer_sentence(m: dict[str, Any]) -> str:
    """Say which mobile connection carried the kernel's packets."""
    by_conn = m.get("kernel_mobile_packets_by_connection") or {}
    total = sum(by_conn.values())
    special = by_conn.get("mobile_unmetered", 0)
    text = ""
    if total and special * 2 >= total:
        text = (
            f" {special} of the kernel's {total} mobile packets went over the "
            "unmetered, non-default mobile connection (typically IMS for VoLTE and "
            "Wi-Fi calling), not over the internet connection."
        )
    if m.get("mobile_data_always_on") and m.get("mobile_internet_background_only"):
        text += (
            " 'Mobile data always active' keeps an idle mobile internet connection up "
            "as well."
        )
    return text


def _radio_evidence(
    stats: _Charged | None,
    hist: _History,
    tiny: list[dict[str, Any]],
) -> list[Evidence]:
    """Cite the radio-active, data and power-model lines."""
    out: list[Evidence] = []
    if stats:
        out.extend(
            stats.text.evidence(v.index)
            for label in (
                "Cellular kernel active time",
                "Mobile radio active time",
                "Cellular data received",
                "Cellular data sent",
            )
            if (v := stats.leaf(label))
        )
        if mr := stats.component("mobile_radio"):
            out.append(stats.text.evidence(mr.index))
        out.extend(
            stats.text.evidence(stats.mspp[r["uid"]][2])
            for r in tiny
            if r["uid"] in stats.mspp
        )
    if hist.radio:
        longest = max(hist.radio, key=lambda a: a.seconds)
        out += hist.evidence(longest.index)
    return out


def _signal_finding(
    stats: _Charged | None,
    on_battery_s: float | None,
    result: Result,
) -> Finding | None:
    """Report weak coverage or long searches for a network."""
    m = result.metrics
    levels = m.get("signal_level_pct") or m.get("history_signal_level_pct") or {}
    poor = (levels.get("none") or 0) + (levels.get("poor") or 0)
    scan_s = m.get("signal_scanning_s") or m.get("phone_scanning_s") or 0
    scan_pct = pct(scan_s, on_battery_s) or 0
    if poor < POOR_SIGNAL_PCT and scan_pct < SCANNING_PCT:
        return None
    evidence = []
    if stats:
        for header in ("Cellular Rx signal strength (RSRP)", "Phone signal levels"):
            rows = stats.children(header)
            evidence += [stats.text.evidence(v.index) for _, v in rows]
        if v := stats.leaf("Signal scanning time"):
            evidence.append(stats.text.evidence(v.index))
    return Finding(
        id="cellular_radio.weak_coverage",
        title="Weak cellular coverage or searching for a network",
        symptom="battery",
        severity="medium",
        basis="measured",
        window="on_battery",
        summary=(
            f"The phone had no or poor cellular signal {poor:.1f}% of battery time "
            f"and searched for a network {scan_pct:.1f}% of it. Weak signal makes the "
            "modem transmit at higher power and search more often."
        ),
        metrics={"poor_or_none_pct": round(poor, 1), "scanning_pct": scan_pct},
        evidence=evidence,
        recommendation=(
            "Where the phone rests in weak coverage, prefer Wi-Fi (with Wi-Fi calling) "
            "or airplane mode with Wi-Fi on; if the phone flips between network "
            "generations, try a fixed preferred network type in Settings > Network & "
            "internet > SIMs."
        ),
        followups=[
            "Compare the signal-level histogram for days spent at different places.",
            "Check 'Cellular Tx time' by power level for top-power transmission.",
        ],
    )


def _tx_power_finding(stats: _Charged | None, result: Result) -> Finding | None:
    """Long transmission at the top power level."""
    by_level = result.metrics.get("modem_tx_by_level_s") or {}
    total = sum(by_level.values())
    top = by_level.get("above 20dBm", 0.0)
    if stats is None or top < HIGH_TX_MIN_S:
        return None
    top_pct = pct(top, total)
    if (top_pct or 0) < HIGH_TX_SHARE_PCT:
        return None
    tx_lines = stats.children("Cellular Tx time")
    evidence = [stats.text.evidence(v.index) for _, v in tx_lines]
    return Finding(
        id="cellular_radio.high_tx_power",
        title="Modem transmitted at top power for a long time",
        symptom="battery",
        severity="low",
        basis="measured",
        window="on_battery",
        summary=(
            f"The modem transmitted above 20 dBm for {top:.0f} s, {top_pct}% "
            "of its transmit time: the uplink to the cell was weak."
        ),
        metrics={"tx_above_20dbm_s": top, "tx_total_s": round(total, 1)},
        evidence=evidence,
        recommendation="Prefer Wi-Fi where the cellular uplink is weak.",
        followups=["Compare TX power levels at the places where the phone rests."],
    )


@analyzer("cellular_radio")
def cellular_radio(ctx: Context) -> Result:
    """Mobile radio active time, coverage, TX power and the UIDs behind them."""
    stats = _charged(ctx)
    hist = _history(ctx)
    if stats is None and not hist.records:
        msg = "no batterystats dump"
        raise SkipError(msg)
    result = Result("cellular_radio", window="on_battery")
    _parse_notes(result, hist, stats)
    if stats:
        _cell_counters(stats, result)
        _cell_uids(ctx, stats, result)
    _cell_history(hist, result)
    _mobile_bearers(ctx, result)
    _mobile_idents(ctx, hist, result)
    for check in (
        _radio_finding(ctx, stats, hist, result),
        _signal_finding(stats, _on_battery_s(ctx, hist), result),
        _tx_power_finding(stats, result),
    ):
        if check:
            result.findings.append(check)
    if not result.metrics:
        msg = "no cellular statistics in batterystats"
        raise SkipError(msg)
    return result


# ---------------------------------------------------------------------------
# wifi_roaming

_L2_RE = re.compile(
    rf"^\s*(?P<ts>{_ISO}) - CMD_UPDATE_L2INFORMATION \S+ .*?"
    r"bssid: (?P<bssid>[0-9a-fA-F:]{17}|null)",
)
_ROAM_TRIGGER_RE = re.compile(
    r'\[ROAM_TRIGGER\]: VDEV\[\d+\] Reason: "(?P<reason>[^"]+)"(?P<rest>.*)'
)
_ROAM_RSSI_RE = re.compile(r"Current AP RSSI:\s*(?P<rssi>-?\d+)")
_ROAM_RESULT_RE = re.compile(
    r"\[ROAM_RESULT\]: VDEV\[\d+\] (?P<res>SUCCESS|FAILED)"
    r"(?:\s+Reason:\s*(?P<why>.+?))?\s*$",
)
_DRIVER_CLOCK_RE = re.compile(r"\]\[(?P<t>\d\d:\d\d:\d\d)\.\d+\] wlan:")
_DAY_S = 86_400
_ROAM_SCAN_TIME_RE = re.compile(r"radioRoamScanTimeMs=(?P<ms>\d+)")
_NO_NETWORK_STATES = {"no_net", "disconn", "scanning"}


@dataclass
class _Roam:
    """One IpClient L2 update; the BSSID stays in memory and is never reported."""

    ts: datetime
    index: int
    bssid: str
    changed: bool


def _parse_l2(text: Text | None) -> list[_Roam]:
    """BSSID updates from the IpClient log of ``dumpsys network_stack``."""
    if text is None:
        return []
    roams: list[_Roam] = []
    previous = None
    for i, m in text.find(_L2_RE):
        bssid = m["bssid"].lower()
        if bssid == "null":
            continue
        ts = datetime.fromisoformat(m["ts"])
        roams.append(_Roam(ts, i, bssid, bssid != previous))
        previous = bssid
    return roams


def _ap_key(bssid: str) -> str:
    """Group the radios of one access point: same first five octets.

    The locally administered bit of the first octet is ignored because access
    points derive extra BSSIDs by setting it.
    """
    first = int(bssid[:2], 16) & 0xFD
    return f"{first:02x}{bssid[2:14]}"


def _max_burst(times: list[datetime]) -> int:
    """Largest number of events inside any ``BURST_WINDOW_S`` window."""
    seconds = [t.timestamp() for t in times]
    return max(
        (bisect_right(seconds, s + BURST_WINDOW_S) - i for i, s in enumerate(seconds)),
        default=0,
    )


def _roam_history(hist: _History, result: Result) -> None:
    """Associations by screen and Doze state, probe wakelocks, RSSI polling."""
    m = result.metrics
    assoc = [a for a in hist.associations if a.on_battery]
    off = [a for a in assoc if not a.screen_on]
    deep = [a for a in assoc if a.idle == "full"]
    hours = {
        k: hist.durations[k] / 3_600_000 for k in ("battery", "screen_off", "idle_full")
    }
    m["associations_on_battery"] = len(assoc)
    m["associations_screen_off"] = len(off)
    m["associations_deep_idle"] = len(deep)
    m["deep_idle_h"] = round(hours["idle_full"], 2)
    for key, n, h in (
        ("on_battery", len(assoc), hours["battery"]),
        ("screen_off", len(off), hours["screen_off"]),
        ("deep_idle", len(deep), hours["idle_full"]),
    ):
        if h:
            m[f"associations_per_h_{key}"] = round(n / h, 1)
    _irm_metrics(hist, assoc, m)
    rssi = [s for s in hist.wifi_signal if s.on_battery]
    m["rssi_updates_on_battery"] = len(rssi)
    if rssi:
        m["rssi_updates_screen_on_pct"] = pct(sum(s.screen_on for s in rssi), len(rssi))
    marks = [a.ms for a in assoc]
    spans = []
    for start, end, index in hist.screen_off:
        n = bisect_left(marks, end) - bisect_left(marks, start)
        spans.append(
            {
                "start": _fmt(hist.wall(start)),
                "minutes": round((end - start) / 60_000, 1),
                "associations": n,
                "ref": hist.text.ref(index) if hist.text else None,
            }
        )
    result.add_table("screen_off_spans", spans)


def _irm_metrics(hist: _History, assoc: list[_Mark], m: dict[str, Any]) -> None:
    """Neighbour-probe wakelocks and their delay after the last association."""
    irm = [w for w in hist.irm if w.on_battery]
    if not irm:
        return
    marks = [a.ms for a in assoc]
    delays = []
    for w in irm:
        pos = bisect_right(marks, w.ms) - 1
        if pos >= 0:
            delays.append((w.ms - marks[pos]) / 1000)
    m["irm_probe_wakelock_starts"] = len(irm)
    near = sum(d <= IRM_MATCH_S for d in delays)
    m["irm_within_1s_of_association_pct"] = pct(near, len(irm))
    if delays:
        m["irm_delay_median_s"] = round(median(delays), 3)


def _roam_l2(
    roams: list[_Roam],
    spans: list[tuple[datetime, datetime]],
    result: Result,
) -> list[_Roam]:
    """BSSID changes, distinct BSSIDs, AP groups and bursts inside the window."""
    m = result.metrics
    inside = [r for r in roams if _in_spans(r.ts, spans)] if spans else roams
    if roams and not spans:
        result.notes.append(
            "No battery window known: BSSID counts cover the whole log."
        )
    changes = [r for r in inside if r.changed]
    m["l2_updates_on_battery"] = len(inside)
    m["bssid_changes_on_battery"] = len(changes)
    m["distinct_bssids_on_battery"] = len({r.bssid for r in inside})
    m["access_points_on_battery"] = len({_ap_key(r.bssid) for r in inside})
    m["max_bssid_changes_in_2min"] = _max_burst([r.ts for r in changes])
    if roams and spans and roams[0].ts > spans[0][0]:
        result.notes.append(
            f"The IpClient log starts at {_fmt(roams[0].ts)}, after the battery window "
            "began: BSSID counts are lower bounds.",
        )
    per_hour = Counter(r.ts.strftime("%Y-%m-%d %H:00") for r in changes)
    result.add_table(
        "bssid_changes_per_hour",
        [{"hour": h, "bssid_changes": n} for h, n in sorted(per_hour.items())],
    )
    labels: dict[str, str] = {}
    for r in inside:
        labels.setdefault(_ap_key(r.bssid), f"AP-{len(labels) + 1}")
    rows: list[dict[str, Any]] = [
        {
            "access_point": label,
            "radios_seen": len({r.bssid for r in inside if _ap_key(r.bssid) == key}),
            "associations": sum(_ap_key(r.bssid) == key for r in inside),
        }
        for key, label in labels.items()
    ]
    rows.sort(key=lambda r: -r["associations"])
    result.add_table("access_points", rows)
    return changes


@dataclass
class _Trigger:
    """A firmware roam trigger from the kernel log."""

    index: int
    reason: str
    rssi_dbm: int | None


def _roam_triggers(ctx: Context, result: Result) -> list[_Trigger]:
    """Vendor WLAN driver roam triggers and results (Qualcomm format)."""
    dmesg = ctx.sources.get("dmesg")
    if dmesg is None:
        return []
    triggers: list[_Trigger] = []
    outcomes: Counter[str] = Counter()
    clocks: list[str] = []  # driver clock of every Wi-Fi driver line, in log order
    for i, line in enumerate(dmesg.lines):
        if "] wlan:" in line and (clock := _DRIVER_CLOCK_RE.search(line)):
            clocks.append(clock["t"])
        if "ROAM_" not in line:
            continue
        if t := _ROAM_TRIGGER_RE.search(line):
            rssi = _ROAM_RSSI_RE.search(t["rest"])
            dbm = -abs(int(rssi["rssi"])) if rssi else None
            triggers.append(_Trigger(i, t["reason"], dbm))
        elif r := _ROAM_RESULT_RE.search(line):
            outcomes[r["res"] if r["res"] == "SUCCESS" else f"FAILED: {r['why']}"] += 1
    if not triggers:
        return []
    m = result.metrics
    m["roam_triggers_kernel_sample"] = len(triggers)
    m["roam_trigger_reasons"] = dict(Counter(t.reason for t in triggers))
    dbms = [t.rssi_dbm for t in triggers if t.rssi_dbm is not None]
    if dbms:
        m["roam_trigger_rssi_dbm_min"], m["roam_trigger_rssi_dbm_max"] = (
            min(dbms),
            max(dbms),
        )
    m["roam_results_kernel_sample"] = dict(outcomes)
    coverage = ""
    if clocks:
        span_s = _clock_span_s(clocks)
        m["kernel_log_wifi_span_s"] = round(span_s)
        coverage = (
            f" Its Wi-Fi driver lines span {fmt_duration(span_s)} "
            f"(driver clock {clocks[0]}-{clocks[-1]} UTC)."
        )
    result.notes.append(
        f"The kernel log is a ring buffer.{coverage} Roam triggers are a sample "
        "from that stretch, not a total.",
    )
    return triggers


def _clock_span_s(clocks: list[str]) -> float:
    """Seconds from the first to the last HH:MM:SS stamp, across midnights."""
    total = 0.0
    for a, b in pairwise(clocks):
        step = parse_clock_s(b) - parse_clock_s(a)
        total += (step + _DAY_S) if step < -_DAY_S / 2 else step
    return total


def _wifi_counters(ctx: Context, stats: _Charged | None, result: Result) -> None:
    """Wi-Fi state shares, RSSI histogram, roam scan time and roam wakelock."""
    m = result.metrics
    if stats:
        states = {label: v.pct for label, v in stats.children("Wifi states")}
        if states:
            m["wifi_state_pct"] = states
            m["wifi_on_no_network_pct"] = round(
                sum(v or 0 for k, v in states.items() if k in _NO_NETWORK_STATES),
                1,
            )
        rssi = stats.children("Wifi Rx signal strength (RSSI)") or stats.children(
            "Wifi signal levels",
        )
        if levels := _level_shares(rssi):
            m["wifi_rssi_level_pct"] = levels
        wakelocks = stats.since.kernel_wakelocks
        if wl := next((k for k in wakelocks if k.name == "wlan_roam_ho_wl"), None):
            m["roam_handoff_wakelock_s"] = round(wl.seconds, 1)
            m["roam_handoff_wakelock_count"] = wl.count
        if (v := stats.leaf("Connectivity changes")) and v.value is not None:
            m["connectivity_changes"] = int(v.value)
    wifi = ctx.sources.get("wifi")
    if wifi and (found := wifi.find(_ROAM_SCAN_TIME_RE)):
        m["roam_scan_time_since_wifi_start_s"] = round(int(found[0][1]["ms"]) / 1000, 1)


def _conn_metrics(hist: _History, result: Result) -> None:
    """Summarise the history's 'conn=' events: states, screen and timing."""
    events = [c for c in hist.conn if c.on_battery]
    if not events:
        return
    m = result.metrics
    m["conn_events_on_battery"] = len(events)
    m["conn_events_screen_on_pct"] = pct(sum(c.screen_on for c in events), len(events))
    m["conn_event_values"] = dict(Counter(c.value for c in events))
    wifi_changes = sorted(
        [s.ms for s in hist.wifi_signal] + [a.ms for a in hist.associations],
    )
    follows = 0
    for c in events:
        pos = bisect_right(wifi_changes, c.ms) - 1
        follows += pos >= 0 and c.ms - wifi_changes[pos] <= CONN_FOLLOW_S * 1000
    m["conn_events_after_wifi_change_pct"] = pct(follows, len(events))


def _roam_rate(m: dict[str, Any]) -> tuple[str, int, float] | None:
    """Pick the best stationary roam rate: deep idle, else screen off, else L2."""
    for key, count_key, label in (
        ("associations_per_h_deep_idle", "associations_deep_idle", "in deep idle"),
        ("associations_per_h_screen_off", "associations_screen_off", "screen off"),
    ):
        if key in m and m[count_key]:
            return label, m[count_key], m[key]
    return None


def _roam_finding(
    hist: _History,
    l2: tuple[Text | None, list[_Roam]],
    triggers: tuple[Text | None, list[_Trigger]],
    battery_s: float | None,
    result: Result,
) -> Finding | None:
    """Report ping-pong roaming while the phone lies still."""
    m = result.metrics
    rate = _roam_rate(m)
    if rate is None and m.get("bssid_changes_on_battery") and battery_s:
        n = m["bssid_changes_on_battery"]
        rate = ("on battery", n, round(n / (battery_s / 3600), 1))
    if rate is None or rate[1] < ROAMS_MIN_COUNT or rate[2] < ROAMS_PER_H_IDLE:
        return None
    state, count, per_h = rate
    summary = (
        f"Wi-Fi re-associated {m.get('associations_on_battery', count)} times on "
        f"battery; {count} of them {state} ({per_h}/h), when the phone was lying still."
    )
    if "bssid_changes_on_battery" in m:
        summary += (
            f" The network stack log shows {m['bssid_changes_on_battery']} BSSID "
            f"changes across {m['distinct_bssids_on_battery']} BSSIDs on at least "
            f"{m['access_points_on_battery']} access points, up to "
            f"{m['max_bssid_changes_in_2min']} within two minutes."
        )
    if "roam_triggers_kernel_sample" in m:
        reasons = ", ".join(f"{k} x{v}" for k, v in m["roam_trigger_reasons"].items())
        summary += (
            " In the kernel log sample the firmware triggered "
            f"{m['roam_triggers_kernel_sample']} roams ({reasons})"
        )
        if "roam_trigger_rssi_dbm_min" in m:
            summary += (
                f" with the current AP at {m['roam_trigger_rssi_dbm_min']} to "
                f"{m['roam_trigger_rssi_dbm_max']} dBm"
            )
        summary += ": the resting spot is at the edge of several access points."
    if (m.get("rssi_updates_screen_on_pct") or 0) >= RSSI_SCREEN_ON_SHARE * 100:
        summary += (
            " The batterystats Wi-Fi signal histogram is sampled with the screen on, "
            "so it does not describe the screen-off resting spot."
        )
    return Finding(
        id="wifi_roaming.stationary_roaming",
        title="Wi-Fi keeps roaming between access points while the phone lies still",
        symptom="battery",
        severity="medium",
        basis="measured",
        window="on_battery",
        summary=summary,
        metrics={"roams": count, "state": state, "roams_per_h": per_h},
        evidence=_roam_evidence(hist, l2, triggers),
        recommendation=(
            "A phone that does not move should stay on one access point. Check the "
            "access points for minimum-RSSI kicking, band steering and aggressive "
            "802.11k/v roaming assistance; lower the transmit power of access points "
            "that overlap where the phone usually rests, or move its resting or "
            "charging spot closer to one access point."
        ),
        followups=[
            (
                "Count 'wifi_suppl=associated' in the next battery history; aim for "
                "fewer than about 10 per night."
            ),
            (
                "Capture the kernel log while the phone dozes and read the roam "
                "trigger reasons and RSSI values."
            ),
            (
                "If Wi-Fi calling is on, compare roam times with IMS handovers "
                "(ims_handover)."
            ),
        ],
    )


def _roam_evidence(
    hist: _History,
    l2: tuple[Text | None, list[_Roam]],
    triggers: tuple[Text | None, list[_Trigger]],
) -> list[Evidence]:
    """Cite a few associations, BSSID changes (without the BSSID) and roam triggers."""
    out: list[Evidence] = []
    deep = [a for a in hist.associations if a.on_battery and a.idle == "full"]
    for a in deep[:3]:
        out += hist.evidence(a.index)
    text, changes = l2
    if text:
        out += [
            text.evidence(
                r.index,
                f"{r.ts.isoformat()} CMD_UPDATE_L2INFORMATION (BSSID changed)",
            )
            for r in changes[:3]
        ]
    text, found = triggers
    if text:
        out += [text.evidence(t.index) for t in found[:3]]
    return out


def _conn_finding(hist: _History, result: Result) -> Finding | None:
    """Explain a large 'Connectivity changes' counter that is not flapping."""
    m = result.metrics
    total = m.get("connectivity_changes") or m.get("conn_events_on_battery") or 0
    values = m.get("conn_event_values") or {}
    events = sum(values.values())
    connected = sum(n for v, n in values.items() if v.endswith(":CONNECTED"))
    if (
        total < CONN_CHANGES_MIN
        or not events
        or connected / events < CONN_SAME_STATE_SHARE
    ):
        return None
    evidence = [e for c in hist.conn[:3] for e in hist.evidence(c.index)]
    return Finding(
        id="wifi_roaming.connectivity_changes_not_reconnects",
        title="'Connectivity changes' are capability updates, not reconnects",
        symptom="info",
        severity="info",
        basis="inferred",
        window="on_battery",
        summary=(
            f"Batterystats counted {total} connectivity changes. In the history "
            f"{connected} of {events} were 'CONNECTED' events for an already connected "
            f"network, {m.get('conn_events_screen_on_pct')}% with the screen on and "
            f"{m.get('conn_events_after_wifi_change_pct')}% within {CONN_FOLLOW_S:.0f} "
            "s of a Wi-Fi signal-level change or roam. They are capability updates "
            "(for example a VPN re-announcing the underlying Wi-Fi's signal level), "
            "not network flapping."
        ),
        metrics={"connectivity_changes": total, "connected_events": connected},
        evidence=evidence,
        recommendation="No action; do not read this counter as network drops.",
        followups=[
            (
                "Check network creation times in dumpsys connectivity: a real "
                "reconnect creates a new network ID."
            ),
        ],
    )


def _no_network_finding(
    stats: _Charged | None,
    on_battery_s: float | None,
    result: Result,
) -> Finding | None:
    """Wi-Fi switched on but not connected for a long time."""
    share = result.metrics.get("wifi_on_no_network_pct") or 0
    seconds = share / 100 * (on_battery_s or 0)
    if stats is None or share < WIFI_NO_NETWORK_PCT or seconds < WIFI_NO_NETWORK_MIN_S:
        return None
    return Finding(
        id="wifi_roaming.wifi_without_network",
        title="Wi-Fi was on without a network for a long time",
        symptom="battery",
        severity="low",
        basis="measured",
        window="on_battery",
        summary=(
            f"Wi-Fi was switched on but not connected {share:.1f}% of battery time "
            f"({seconds / 3600:.1f} h), scanning for known networks."
        ),
        metrics={"no_network_pct": share, "no_network_h": round(seconds / 3600, 2)},
        evidence=[
            stats.text.evidence(v.index) for _, v in stats.children("Wifi states")
        ],
        recommendation=(
            "Turn Wi-Fi off away from known networks, or let the phone do it (Settings "
            "> Network & internet > Internet > Network preferences); turn off Wi-Fi "
            "scanning in Settings > Location > Location services if not needed."
        ),
        followups=["Compare 'WiFi Scan time' and Wi-Fi states on a day spent at home."],
    )


@analyzer("wifi_roaming")
def wifi_roaming(ctx: Context) -> Result:
    """Roams and re-associations, roam triggers and the connectivity counter."""
    hist = _history(ctx)
    netstack = ctx.sources.get("network_stack")
    if not hist.records and netstack is None:
        msg = "no battery history and no network_stack dump"
        raise SkipError(msg)
    result = Result("wifi_roaming", window="on_battery")
    stats = _charged(ctx)
    _parse_notes(result, hist, stats)
    if hist.records:
        _roam_history(hist, result)
        _conn_metrics(hist, result)
    changes = _roam_l2(_parse_l2(netstack), _battery_spans(ctx, hist), result)
    triggers = _roam_triggers(ctx, result)
    _wifi_counters(ctx, stats, result)
    if (
        result.metrics.get("rssi_updates_screen_on_pct") or 0
    ) >= RSSI_SCREEN_ON_SHARE * 100:
        result.notes.append(
            "Wi-Fi RSSI levels were updated almost only with the screen on: the "
            "signal histogram does not describe screen-off conditions.",
        )
    for finding in (
        _roam_finding(
            hist,
            (netstack, changes),
            (ctx.sources.get("dmesg"), triggers),
            _on_battery_s(ctx, hist),
            result,
        ),
        _conn_finding(hist, result),
        _no_network_finding(stats, _on_battery_s(ctx, hist), result),
    ):
        if finding:
            result.findings.append(finding)
    return result


# ---------------------------------------------------------------------------
# ims_handover

_PREF_RE = re.compile(
    rf"(?P<ts>{_ISO}) - setPreferredTransports: apnType=ims, "
    r"transport=(?P<t>WLAN|WWAN)",
)
_PREF_LOGCAT_RE = re.compile(
    r"setPreferredTransports: apnType=ims, transport=(?P<t>WLAN|WWAN)"
)
_IWLAN_MODE_RE = re.compile(r"IWLAN operation mode=(?P<mode>\S+)")
_DATA_CONN_RE = re.compile(
    rf"(?P<ts>{_ISO}) - notifyDataConnectionForSubscriber: .*?state: (?P<state>\w+), "
    r"transport: (?P<transport>WWAN|WLAN),.*?APN Setting: (?P<apn>.*?)(?:, link "
    r"properties|$)",
)
_IMS_APN_RE = re.compile(r"(?:^|[,|]\s*)ims\s*(?:[,|]|$)")
_WFC_RE = re.compile(
    r"simSlotIndex=(?P<slot>-?\d+).*?isWifiCallingEnabled=(?P<on>\d)"
    r"(?:.*?wifiCallingMode=(?P<mode>\w+))?",
)
_NATT_RE = re.compile(rf"(?P<ts>{_ISO}) - Start natt keepalive ")


@dataclass
class _ImsWindow:
    """One stay of the IMS connection on Wi-Fi (IWLAN)."""

    start: datetime
    end: datetime | None
    index: int

    @property
    def seconds(self) -> float | None:
        """Dwell time on Wi-Fi in seconds, if the window closed."""
        return (self.end - self.start).total_seconds() if self.end else None


def _windows_from_transports(
    events: Iterable[tuple[datetime, str, int]],
) -> list[_ImsWindow]:
    """Pair WLAN with the next WWAN preference into IWLAN windows."""
    windows: list[_ImsWindow] = []
    open_window: _ImsWindow | None = None
    for ts, transport, index in events:
        if transport == "WLAN" and open_window is None:
            open_window = _ImsWindow(ts, None, index)
        elif transport == "WWAN" and open_window is not None:
            open_window.end = ts
            windows.append(open_window)
            open_window = None
    if open_window:
        windows.append(open_window)
    return windows


def _windows_from_registry(text: Text) -> list[_ImsWindow]:
    """IWLAN windows from the telephony registry's data connection log."""
    windows: list[_ImsWindow] = []
    pending: tuple[datetime, int] | None = None
    current: _ImsWindow | None = None
    for i, m in text.find(_DATA_CONN_RE):
        if not _IMS_APN_RE.search(m["apn"]):
            continue
        ts, state, transport = (
            datetime.fromisoformat(m["ts"]),
            m["state"],
            m["transport"],
        )
        if state == "HANDOVERINPROGRESS" and transport == "WWAN" and current is None:
            pending = (ts, i)
        elif state == "CONNECTED" and transport == "WLAN" and current is None:
            start, index = pending or (ts, i)
            current = _ImsWindow(start, None, index)
        elif current is not None and (
            (state == "CONNECTED" and transport == "WWAN") or state == "DISCONNECTED"
        ):
            current.end = ts
            windows.append(current)
            current, pending = None, None
    if current:
        windows.append(current)
    return windows


def _ims_windows(ctx: Context) -> tuple[Text | None, list[_ImsWindow], str]:
    """Find IWLAN windows: AccessNetworksManager log, registry, radio log."""
    platform = ctx.sources.get("app_services_platform")
    if platform and (found := platform.find(_PREF_RE)):
        events = ((datetime.fromisoformat(m["ts"]), m["t"], i) for i, m in found)
        return platform, _windows_from_transports(events), "AccessNetworksManager log"
    registry = ctx.sources.get("telephony_registry")
    if registry and (windows := _windows_from_registry(registry)):
        return registry, windows, "telephony registry data connection log"
    radio = ctx.sources.get("logcat_radio")
    if radio:
        reference = ctx.windows.log_reference()
        events = [
            (line.ts, m["t"], line.lineno - radio.first_line)
            for line in iter_logcat(radio.text, reference, radio.first_line)
            if (m := _PREF_LOGCAT_RE.search(line.message))
        ]
        if events:
            return radio, _windows_from_transports(events), "radio log"
    return None, [], ""


def _wfc_settings(ctx: Context, result: Result) -> None:
    """Wi-Fi calling switch and mode for the SIM in use, and the IWLAN mode."""
    isub = ctx.sources.get("isub")
    for _, m in isub.find(_WFC_RE) if isub else []:
        if int(m["slot"]) >= 0:
            result.metrics["wifi_calling_enabled"] = m["on"] == "1"
            if m["mode"]:
                result.metrics["wifi_calling_mode"] = m["mode"]
            break
    platform = ctx.sources.get("app_services_platform")
    if platform and (found := platform.find(_IWLAN_MODE_RE)):
        result.metrics["iwlan_operation_mode"] = found[0][1]["mode"]


def _roam_leads(
    windows: list[_ImsWindow],
    roam_times: list[datetime],
    result: Result,
) -> list[float | None]:
    """Seconds from the last roam to each IWLAN start; roams followed by IWLAN."""
    leads: list[float | None] = []
    for w in windows:
        pos = bisect_right(roam_times, w.start) - 1
        leads.append(
            round((w.start - roam_times[pos]).total_seconds(), 1) if pos >= 0 else None
        )
    starts = [w.start for w in windows]
    followed = sum(
        bisect_right(starts, r + timedelta(seconds=ROAM_TO_IWLAN_S))
        > bisect_right(starts, r)
        for r in roam_times
    )
    result.metrics["roams_followed_by_iwlan_within_60s"] = followed
    result.metrics["roams_considered"] = len(roam_times)
    return leads


def _radio_in_windows(
    windows: list[_ImsWindow],
    activations: list[_Activation],
    result: Result,
) -> tuple[float, float, float]:
    """Mobile-radio activations starting inside the windows, per margin.

    Returns the radio-active seconds inside the windows without and with the
    widest margin, and the radio-active seconds on battery.
    """
    total_s = sum(a.seconds for a in activations)
    in_windows: list[float] = []
    for margin in IMS_MARGINS_S:
        pad = timedelta(seconds=margin)
        inside = [
            a
            for a in activations
            if a.ts
            and any(w.start - pad <= a.ts <= (w.end or w.start) + pad for w in windows)
        ]
        seconds = sum(a.seconds for a in inside)
        result.metrics[f"radio_activations_in_windows_margin_{margin}s"] = len(inside)
        result.metrics[f"radio_minutes_in_windows_margin_{margin}s"] = round(
            seconds / 60, 2
        )
        in_windows.append(seconds)
    low, high = min(in_windows), max(in_windows)
    result.metrics["radio_activations_on_battery"] = len(activations)
    result.metrics["radio_minutes_on_battery"] = round(total_s / 60, 2)
    result.metrics["radio_share_in_windows_pct_range"] = [
        pct(low, total_s) or 0.0,
        pct(high, total_s) or 0.0,
    ]
    return low, high, total_s


def _ims_finding(
    source: tuple[Text, list[_ImsWindow]],
    leads: list[float | None],
    radio: tuple[float, float, float] | None,
    split: dict[str, float],
    result: Result,
) -> Finding | None:
    """Short IMS stays on Wi-Fi, repeated after roams."""
    text, windows = source
    dwell = [w.seconds for w in windows if w.seconds is not None]
    if len(windows) < IMS_CYCLES_MIN or not dwell or median(dwell) > IMS_SHORT_DWELL_S:
        return None
    m = result.metrics
    known = [lead for lead in leads if lead is not None]
    after_roam = sum(lead <= ROAM_TO_IWLAN_S for lead in known)
    mode = f" ({m['wifi_calling_mode']})" if "wifi_calling_mode" in m else ""
    summary = (
        f"With Wi-Fi calling on{mode}, the IMS connection moved from mobile to Wi-Fi "
        f"and back {len(windows)} times on battery, staying {median(dwell):.0f} s "
        "(median) each time."
    )
    if known:
        summary += (
            f" {after_roam} of {len(windows)} moves started within {ROAM_TO_IWLAN_S} s "
            "of a Wi-Fi BSSID change (lead times "
            f"{', '.join(f'{x:.0f}' for x in known)} s); only "
            f"{m['roams_followed_by_iwlan_within_60s']} of {m['roams_considered']} "
            "roams led to one."
        )
    severity: Severity = "low"
    if radio and radio[2]:
        low_s, high_s, total_s = radio
        summary += (
            f" Between {100 * low_s / total_s:.0f}% (no margin) and "
            f"{100 * high_s / total_s:.0f}% (±{IMS_MARGINS_S[-1]} s) of the "
            f"{m['radio_minutes_on_battery']} min of mobile-radio activity on "
            "battery fell inside these windows."
        )
        if high_s / total_s >= IMS_RADIO_SHARE_MEDIUM:
            severity = "medium"
        summary += _ims_cost_sentence(low_s, high_s, split)
    return Finding(
        id="ims_handover.iwlan_pingpong",
        title="Wi-Fi calling moves the IMS connection to Wi-Fi and back after roams",
        symptom="battery",
        severity=severity,
        basis="measured",
        window="on_battery",
        summary=summary,
        metrics={"cycles": len(windows), "median_dwell_s": round(median(dwell), 1)},
        evidence=[_ims_evidence(text, w) for w in windows[:7]],
        recommendation=(
            "Test one day with Wi-Fi calling off (Settings > Network & internet > SIMs "
            "> Wi-Fi calling) while keeping VoLTE on, or fix Wi-Fi roaming so the "
            "phone stays on one access point; either should stop these moves."
        ),
        followups=[
            (
                "Compare 'Mobile radio active' or 'Cellular kernel active time' for a "
                "day with Wi-Fi calling off."
            ),
            "Check in the next capture whether every IMS move still follows a roam.",
            (
                "The modem's reason for returning to mobile after a fixed time is not "
                "in the logs; a carrier or vendor bug report would be needed."
            ),
        ],
    )


def _ims_cost_sentence(low_s: float, high_s: float, split: dict[str, float]) -> str:
    """Price the radio time inside the windows at the model's active-time rate."""
    if not split:
        return ""
    active_mah = split["mobile_radio_active_modelled_mah"]
    active_s = split["mobile_radio_active_s_modelled"]
    rate = active_mah / active_s
    return (
        f" At the power model's cost of radio-active time ({active_mah} mAh for "
        f"{fmt_duration(active_s)}), the radio time in these windows comes to about "
        f"{low_s * rate:.0f}-{high_s * rate:.0f} mAh (modelled)."
    )


def _ims_evidence(text: Text, window: _ImsWindow) -> Evidence:
    """Cite an IWLAN window start with its times as the excerpt."""
    end = _hms(window.end) if window.end else "open"
    return text.evidence(window.index, f"IMS on Wi-Fi {_hms(window.start)} - {end}")


_LOG_TS_RE = re.compile(rf"^\s*(?P<ts>{_ISO}) - ")


def _ims_extras(
    ctx: Context,
    text: Text,
    spans: list[tuple[datetime, datetime]],
    result: Result,
) -> None:
    """Count IPsec NAT-T keepalive starts; note when the logs start too late."""
    conn = ctx.sources.get("connectivity")
    natt = [m for _, m in conn.find(_NATT_RE)] if conn else []
    result.metrics["natt_keepalive_starts_on_battery"] = sum(
        _in_spans(datetime.fromisoformat(m["ts"]), spans) for m in natt
    )
    first = next((m for _, m in text.find(_LOG_TS_RE)), None)
    start = datetime.fromisoformat(first["ts"]) if first else None
    if text.origin.endswith(("logcat_radio.txt", "RADIO LOG")):
        start = None
        result.notes.append(
            "IWLAN windows come from the radio log, which covers only its last "
            "minutes: cycle counts are lower bounds.",
        )
    if start and spans and start > spans[0][0]:
        result.notes.append(
            f"The IMS transport log starts at {_fmt(start)}, after the battery window "
            "began (ring buffer): cycle counts are lower bounds.",
        )
    if natt:
        result.notes.append(
            "NAT-T keepalive starts come from a ring buffer; treat them as a lower "
            "bound.",
        )


@analyzer("ims_handover")
def ims_handover(ctx: Context) -> Result:
    """IMS LTE/Wi-Fi handovers, their link to roams and to mobile-radio time."""
    text, windows, origin = _ims_windows(ctx)
    result = Result("ims_handover", window="on_battery")
    _wfc_settings(ctx, result)
    if text is None:
        if not result.metrics:
            msg = "no IMS transport log, telephony registry log or Wi-Fi calling state"
            raise SkipError(msg)
        result.metrics["iwlan_cycles_on_battery"] = 0
        return result
    hist = _history(ctx)
    spans = _battery_spans(ctx, hist)
    on_batt = [w for w in windows if _in_spans(w.start, spans)] if spans else windows
    result.metrics["iwlan_cycles_total"] = len(windows)
    result.metrics["iwlan_cycles_on_battery"] = len(on_batt)
    result.notes.append(f"IWLAN windows from the {origin}.")
    roams = [r.ts for r in _parse_l2(ctx.sources.get("network_stack")) if r.changed]
    if not roams:
        roams = [a.ts for a in hist.associations if a.ts]
    roams = sorted(r for r in roams if _in_spans(r, spans)) if spans else roams
    leads = _roam_leads(on_batt, roams, result) if roams else [None] * len(on_batt)
    acts = [a for a in hist.radio if a.on_battery]
    radio = _radio_in_windows(on_batt, acts, result) if acts else None
    _ims_extras(ctx, text, spans, result)
    result.add_table(
        "iwlan_windows",
        [
            {
                "start": _fmt(w.start),
                "end": _fmt(w.end),
                "dwell_s": round(w.seconds, 1) if w.seconds is not None else None,
                "last_roam_before_s": lead,
                "ref": text.ref(w.index),
            }
            for w, lead in zip(on_batt, leads, strict=True)
        ],
    )
    stats = _charged(ctx)
    split = _radio_split(stats) if stats else {}
    if finding := _ims_finding((text, on_batt), leads, radio, split, result):
        result.findings.append(finding)
    return result


# ---------------------------------------------------------------------------
# network_traffic


@dataclass
class _Talker:
    """On-battery packet counts of one UID from batterystats."""

    uid: int
    name: str
    rx_pkts: int
    tx_pkts: int
    rx_bytes: int
    index: int
    rx_per_s: float = 0.0
    tx_per_s: float = 0.0
    steady: bool | None = None

    @property
    def rx_packet_bytes(self) -> float:
        """Average received packet size."""
        return self.rx_bytes / self.rx_pkts if self.rx_pkts else 0.0


def _talkers(ctx: Context, stats: _Charged, seconds: float | None) -> list[_Talker]:
    """Per-UID Wi-Fi plus mobile packets on battery, with per-second rates."""
    out = []
    for uid, u in stats.uids.items():
        n = u.net
        rx = n.get("wifi_rx_pkts", 0) + n.get("mobile_rx_pkts", 0)
        tx = n.get("wifi_tx_pkts", 0) + n.get("mobile_tx_pkts", 0)
        if not (rx or tx):
            continue
        talker = _Talker(
            uid,
            _uid_name(ctx, uid),
            rx,
            tx,
            n.get("wifi_rx_bytes", 0) + n.get("mobile_rx_bytes", 0),
            u.net_index.get("wifi", u.net_index.get("mobile", 0)),
        )
        if seconds:
            talker.rx_per_s, talker.tx_per_s = rx / seconds, tx / seconds
        out.append(talker)
    out.sort(key=lambda t: -t.rx_pkts)
    return out


def _bucket_tables(
    ctx: Context,
    net: _NetStats,
    used: list[int],
    result: Result,
) -> dict[int, dict[str, Any]]:
    """Per-bucket totals per network, and per-UID totals over the used buckets."""
    per_bucket: dict[int, Counter[str]] = {st: Counter() for st in used}
    per_uid: dict[int, dict[str, Any]] = {}
    for (kind, uid, st), (rb, rp, _tb, tp) in net.cells.items():
        if st not in per_bucket:
            continue
        per_bucket[st][f"{kind}_rx_pkts"] += rp
        per_bucket[st][f"{kind}_tx_pkts"] += tp
        row = per_uid.setdefault(uid, Counter())
        row[f"{kind}_rx_pkts"] += rp
        row[f"{kind}_tx_pkts"] += tp
        row[f"{kind}_rx_bytes"] += rb
        if rp >= STEADY_MIN_BUCKET_PKTS:
            row[f"present_{st}"] = 1
    result.tables["netstats_buckets"] = [
        {"start": _fmt(_local(ctx, st)), **dict(per_bucket[st])} for st in used
    ]
    return per_uid


def _uid_traffic_rows(
    ctx: Context,
    per_uid: dict[int, dict[str, Any]],
    used: list[int],
    result: Result,
) -> None:
    """Rank UIDs by received packets over the battery buckets."""
    minutes = len(used) * ((result.metrics.get("netstats_bucket_s") or 7200) / 60)
    rows: list[dict[str, Any]] = []
    for uid, c in per_uid.items():
        rx = c["wifi_rx_pkts"] + c["mobile_rx_pkts"] + c["mobile_unmetered_rx_pkts"]
        rx_bytes = c["wifi_rx_bytes"] + c["mobile_rx_bytes"]
        rows.append(
            {
                "uid": uid,
                "name": _uid_name(ctx, uid),
                "wifi_rx_pkts": c["wifi_rx_pkts"],
                "wifi_tx_pkts": c["wifi_tx_pkts"],
                "vpn_rx_pkts": c["vpn_rx_pkts"],
                "vpn_tx_pkts": c["vpn_tx_pkts"],
                "mobile_rx_pkts": c["mobile_rx_pkts"] + c["mobile_unmetered_rx_pkts"],
                "mobile_tx_pkts": c["mobile_tx_pkts"] + c["mobile_unmetered_tx_pkts"],
                "rx_pkts_per_min": round(rx / minutes, 2) if minutes else None,
                "buckets_present": sum(c[f"present_{st}"] for st in used),
                "rx_bytes_per_pkt": round(rx_bytes / rx) if rx else None,
            }
        )
    rows.sort(key=lambda r: -(r["wifi_rx_pkts"] + r["mobile_rx_pkts"]))
    result.add_table("netstats_uid_traffic", rows)


def _kernel_vpn_segments(
    ctx: Context,
    net: _NetStats,
    used: list[int],
    result: Result,
) -> int:
    """Kernel (UID 0) segments sent into the VPN with no payload and no replies."""
    rows, bare = [], 0
    for st in used:
        rb, rp, tb, tp = net.cells.get(("vpn", 0, st), [0, 0, 0, 0])
        if not tp:
            continue
        size = tb / tp
        rows.append(
            {
                "start": _fmt(_local(ctx, st)),
                "tx_pkts": tp,
                "tx_bytes_per_pkt": round(size, 1),
                "rx_pkts": rp,
                "rx_bytes": rb,
            }
        )
        bare += tp if size <= BARE_SEGMENT_MAX_BYTES and rp * 10 <= tp else 0
    if rows:
        result.tables["kernel_vpn_segments"] = rows
        result.metrics["kernel_vpn_bare_tx_segments"] = bare
    return bare


def _large_downloads(
    ctx: Context,
    net: _NetStats,
    used: list[int],
) -> list[dict[str, Any]]:
    """Single buckets in which one UID received more than ``LARGE_DOWNLOAD_BYTES``."""
    rows = [
        {
            "uid": uid,
            "name": _uid_name(ctx, uid),
            "network": kind,
            "bucket_start": _fmt(_local(ctx, st)),
            "rx_mib": round(cell[0] / 1024**2, 1),
            "ref": net.text.ref(net.first_index[kind, uid]),
        }
        for (kind, uid, st), cell in net.cells.items()
        if st in used and kind != "vpn" and cell[0] >= LARGE_DOWNLOAD_BYTES
    ]
    return sorted(rows, key=lambda r: -r["rx_mib"])


def _netstats_part(
    ctx: Context,
    hist: _History,
    talkers: list[_Talker],
    result: Result,
) -> list[dict[str, Any]]:
    """Bucket-level traffic from netstats; marks batterystats talkers as steady."""
    net = _netstats(ctx)
    spans = _battery_spans(ctx, hist)
    if net is None or not spans:
        return []
    if not _zone_known(ctx):
        result.notes.append("UTC offset unknown: netstats buckets were read as UTC.")
    used = _buckets_in(ctx, net, spans)
    if not used:
        return []
    result.metrics["netstats_bucket_s"] = net.bucket_s
    result.metrics["netstats_span"] = [
        _fmt(_local(ctx, used[0])),
        _fmt(_local(ctx, used[-1] + net.bucket_s)),
    ]
    result.notes.append(
        "netstats buckets do not align with the battery window: the edge buckets "
        "include time on the charger. Tunnelled traffic is counted on both the VPN "
        "and the underlying Wi-Fi; never add the vpn and wifi columns.",
    )
    per_uid = _bucket_tables(ctx, net, used, result)
    _uid_traffic_rows(ctx, per_uid, used, result)
    _kernel_vpn_segments(ctx, net, used, result)
    for t in talkers:
        c = per_uid.get(t.uid)
        t.steady = c is not None and all(c[f"present_{st}"] for st in used)
    return _large_downloads(ctx, net, used)


def _vpn_app(ctx: Context) -> tuple[int, str, str] | None:
    """Return the VPN app's UID, name and finding id if vpn reports its packets."""
    vpn = ctx.results.get("vpn")
    uid = vpn.metrics.get("vpn_app_uid") if vpn else None
    if vpn is None or uid is None or not vpn.findings:
        return None
    return uid, vpn.findings[0].metrics.get("package", str(uid)), vpn.findings[0].id


def _steady_finding(
    ctx: Context,
    talkers: list[_Talker],
    stats: _Charged,
) -> Finding | None:
    """UIDs exchanging small packets at a steady rate through the battery period.

    The VPN app is left out when the vpn finding reports its packets.
    """
    steady = [
        t
        for t in talkers
        if t.rx_per_s >= STEADY_LOW_PKTS_PER_S
        and t.rx_packet_bytes <= SMALL_PACKET_BYTES
        and t.steady is not False
    ]
    vpn = _vpn_app(ctx)
    left_out = ""
    if vpn and any(t.uid == vpn[0] for t in steady):
        steady = [t for t in steady if t.uid != vpn[0]]
        left_out = f" The VPN app {vpn[1]} is left out: {vpn[2]} reports its packets."
    if not steady:
        return None
    steady.sort(key=lambda t: -t.rx_per_s)
    high = any(
        uid_class(t.uid, ctx.packages.third_party) != "core"
        and t.rx_per_s >= STEADY_HIGH_PKTS_PER_S
        for t in steady
    )
    listed = "; ".join(
        f"{t.name}: {t.rx_per_s:.2f} received and {t.tx_per_s:.2f} sent packets/s, "
        f"{t.rx_packet_bytes:.0f} B average"
        for t in steady[:5]
    )
    return Finding(
        id="network_traffic.steady_background_packets",
        title="Apps exchange a steady stream of small packets on battery",
        symptom="battery",
        severity="medium" if high else "low",
        basis="measured",
        window="on_battery",
        summary=(
            f"{len(steady)} UIDs kept exchanging small packets through the battery "
            f"period ({listed}). Received packets can wake a sleeping phone; these "
            "senders are triggers, so their costs do not add up with wakeup or CPU "
            f"findings.{left_out}"
        ),
        metrics={
            "uids": [t.name for t in steady],
            "top_rx_pkts_per_s": round(steady[0].rx_per_s, 3),
        },
        evidence=[stats.text.evidence(t.index) for t in steady[:5]],
        recommendation=(
            "For each app, check whether it must stay connected (push, sync, companion "
            "or VPN apps). Turn off unneeded background sync or keepalive features in "
            "the app, or set Settings > Apps > (app) > App battery usage to "
            "Restricted. For a VPN, see the vpn finding."
        ),
        followups=[
            (
                "Correlate with Wi-Fi receive wakeups ('Wakeup reason' lines) and "
                "their periodicity."
            ),
            (
                "Stop the top app for one screen-off hour on battery and compare drain "
                "and wakeups."
            ),
            "On the server or peer side, check what keeps the connection busy.",
        ],
    )


def _download_finding(rows: list[dict[str, Any]]) -> Finding | None:
    """Large single downloads on battery explain Wi-Fi volume."""
    if not rows:
        return None
    top = rows[0]
    return Finding(
        id="network_traffic.large_download_on_battery",
        title="Large download on battery",
        symptom="info",
        severity="info",
        basis="measured",
        window="on_battery",
        summary=(
            f"{top['name']} received {top['rx_mib']} MiB over {top['network']} in the "
            f"bucket starting {top['bucket_start']}; {len(rows)} such bucket(s) on "
            "battery. A one-off download explains data volume, not standby drain."
        ),
        metrics={"downloads": len(rows), "largest_mib": top["rx_mib"]},
        evidence=[
            Evidence(top["ref"], f"uid={top['uid']} {top['network']} bucket rows")
        ],
        recommendation=(
            "No action unless the download repeats; then schedule it for Wi-Fi and "
            "charger."
        ),
        followups=["Check whether the app was in the foreground at that time."],
    )


@analyzer("network_traffic", after=("windows", "vpn"))
def network_traffic(ctx: Context) -> Result:
    """Per-UID packets per network and bucket, keepalive flows, downloads."""
    stats = _charged(ctx)
    if stats is None and ctx.sources.get("netstats") is None:
        msg = "no batterystats and no netstats dump"
        raise SkipError(msg)
    hist = _history(ctx)
    result = Result("network_traffic", window="on_battery")
    seconds = _on_battery_s(ctx, hist)
    talkers = _talkers(ctx, stats, seconds) if stats else []
    if stats:
        for label, key in (
            ("Wifi data received", "wifi_rx_bytes"),
            ("Wifi data sent", "wifi_tx_bytes"),
            ("Wifi packets received", "wifi_rx_packets"),
            ("Wifi packets sent", "wifi_tx_packets"),
        ):
            if (v := stats.leaf(label)) and v.value is not None:
                result.metrics[key] = v.value
    downloads = _netstats_part(ctx, hist, talkers, result)
    result.add_table(
        "batterystats_traffic",
        [
            {
                "uid": t.uid,
                "name": t.name,
                "rx_pkts": t.rx_pkts,
                "tx_pkts": t.tx_pkts,
                "rx_pkts_per_s": round(t.rx_per_s, 3),
                "tx_pkts_per_s": round(t.tx_per_s, 3),
                "rx_bytes_per_pkt": round(t.rx_packet_bytes),
                "steady_in_netstats": t.steady,
            }
            for t in talkers
        ],
    )
    for finding in (
        _steady_finding(ctx, talkers, stats) if stats else None,
        _download_finding(downloads),
    ):
        if finding:
            result.findings.append(finding)
    return result


# ---------------------------------------------------------------------------
# vpn

# Known mesh VPN apps: every peer keeps a path to the phone alive.
MESH_VPN_PACKAGES = {
    "com.tailscale.ipn": "Tailscale",
    "com.zerotier.one": "ZeroTier",
    "io.netbird.client": "NetBird",
    "net.defined.mobile_nebula": "Nebula",
}
_CREATED_RE = re.compile(r"\bcreated=(?P<c>\d{4}-\d\d-\d\dT[\d:.]+)Z")
_UNDERLYING_RE = re.compile(r"underlying\{\[(?P<u>[^\]]*)\]\}")
_IFACE_NAME_RE = re.compile(r"InterfaceName: (?P<i>\S+)")
_ROUTES_RE = re.compile(r"Routes: \[(?P<r>[^\]]*)\]")
_LINK_ADDRS_RE = re.compile(r"LinkAddresses: \[(?P<a>[^\]]*)\]")
_DNS_ADDRS_RE = re.compile(r"DnsAddresses: \[(?P<a>[^\]]*)\]")
_OWNER_RE = re.compile(r"OwnerUid: (?P<uid>\d+)")
_LOCKDOWN_RE = re.compile(r"lockdown=(?P<lock>true|false) alwaysOn=(?P<on>true|false)")


@dataclass
class _Network:
    """One network agent from ``dumpsys connectivity``."""

    net_id: str
    kind: str
    extra: str
    index: int
    created: datetime | None = None
    underlying: list[str] = field(default_factory=list)
    iface: str | None = None
    peer_routes: int = 0


def _parse_networks(text: Text) -> list[_Network]:
    """Network agents with type, interface, underlying networks and routes."""
    nets = []
    for i, m in text.find(_NAI_RE):
        rest = m["rest"]
        net = _Network(m["net"], m["type"], m["extra"].strip(), i)
        if c := _CREATED_RE.search(rest):
            net.created = datetime.fromisoformat(c["c"])
        if u := _UNDERLYING_RE.search(rest):
            net.underlying = [x.strip() for x in u["u"].split(",") if x.strip()]
        if f := _IFACE_NAME_RE.search(rest):
            net.iface = f["i"]
        if routes := _ROUTES_RE.search(rest):
            # Host routes to the network's own addresses and to its DNS
            # resolvers (a mesh VPN's built-in resolver) are not peers.
            local = _addresses(_LINK_ADDRS_RE.search(rest))
            local |= _addresses(_DNS_ADDRS_RE.search(rest))
            net.peer_routes = len(_host_routes(routes["r"]) - local)
        nets.append(net)
    return nets


def _addresses(found: re.Match[str] | None) -> set[str]:
    """Return the addresses of a ``[ 192.0.2.1/24,/198.51.100.53 ]`` list."""
    items = found["a"].split(",") if found else []
    return {a.strip().strip("/").split("/")[0] for a in items if a.strip()}


def _host_routes(routes: str) -> set[str]:
    """Return the destinations of the /32 and /128 routes of a route list."""
    dests = (r.split(maxsplit=1)[0] for r in routes.split(",") if r.strip())
    return {d.rsplit("/", 1)[0] for d in dests if d.endswith(("/32", "/128"))}


def _created(ctx: Context, utc: datetime | None) -> datetime | None:
    """Return a network's UTC creation time as the phone's local time."""
    if utc is None:
        return None
    return ctx.windows.local_from_epoch(utc.replace(tzinfo=UTC).timestamp())


def _vpn_state(ctx: Context, result: Result) -> int | None:
    """Always-on and lockdown state; return the VPN owner UID if listed."""
    owner = None
    mgmt = ctx.sources.get("vpn_management")
    if mgmt:
        if found := mgmt.find(_OWNER_RE):
            owner = int(found[0][1]["uid"])
        if found := mgmt.find(_LOCKDOWN_RE):
            result.metrics["vpn_lockdown"] = found[0][1]["lock"] == "true"
            result.metrics["vpn_always_on"] = found[0][1]["on"] == "true"
    settings = load_settings(ctx)
    if settings and settings.get("always_on_vpn_lockdown", "secure"):
        lockdown = settings.value("always_on_vpn_lockdown", "secure")
        result.metrics["vpn_lockdown"] = lockdown == "1"
    if settings and settings.get("always_on_vpn_app", "secure"):
        # An unset app reads "null": always-on VPN is off.
        app = settings.value("always_on_vpn_app", "secure")
        result.metrics["vpn_always_on"] = bool(app)
    return owner


def _vpn_traffic(
    ctx: Context,
    owner: int | None,
    hist: _History,
    result: Result,
) -> list[Evidence]:
    """Collect the VPN app's own packets and the kernel's bare segments."""
    m = result.metrics
    evidence: list[Evidence] = []
    stats = _charged(ctx)
    seconds = _on_battery_s(ctx, hist)
    talkers = _talkers(ctx, stats, seconds) if stats and seconds else []
    if stats and (talker := next((t for t in talkers if t.uid == owner), None)):
        m["vpn_app_uid"] = owner
        m["vpn_app_rx_pkts"], m["vpn_app_tx_pkts"] = talker.rx_pkts, talker.tx_pkts
        m["vpn_app_rx_pkts_per_s"] = round(talker.rx_per_s, 3)
        m["vpn_app_tx_pkts_per_s"] = round(talker.tx_per_s, 3)
        evidence.append(stats.text.evidence(talker.index))
    net = _netstats(ctx)
    spans = _battery_spans(ctx, hist)
    if net and spans:
        used = _buckets_in(ctx, net, spans)
        _kernel_vpn_segments(ctx, net, used, result)
        if (ratio := _vpn_overhead(net, used, owner)) is not None:
            m["vpn_app_to_tunnel_packets_ratio_max"] = ratio
    return evidence


def _vpn_overhead(net: _NetStats, used: list[int], owner: int | None) -> float | None:
    """Return the top per-bucket ratio of the VPN app's own to tunnelled packets."""
    if owner is None:
        return None
    ratios = []
    for st in used:
        own = sum(net.cells.get((k, owner, st), [0, 0, 0, 0])[1] for k in _UNDERLAY)
        tunnel = sum(
            c[1] for (k, _, s), c in net.cells.items() if (k, s) == ("vpn", st)
        )
        if own and tunnel:
            ratios.append(own / tunnel)
    return round(max(ratios), 1) if ratios else None


_UNDERLAY = ("wifi", "mobile", "mobile_unmetered")


def _vpn_summary(vpn_net: _Network, nets: list[_Network], m: dict[str, Any]) -> str:
    """Describe the VPN, its mesh nature and the traffic it keeps alive."""
    package = vpn_net.extra.removeprefix("VPN:")
    under = {n.net_id: n.kind for n in nets}
    over = (
        "/".join(under.get(u, "?") for u in vpn_net.underlying) or "an unknown network"
    )
    since = f" since {m['vpn_created']}" if "vpn_created" in m else ""
    summary = (
        f"A VPN by {package} is up on {vpn_net.iface or 'a tunnel'} over {over}{since}."
    )
    if m.get("vpn_mesh"):
        product = MESH_VPN_PACKAGES.get(package, "per-peer host routes")
        summary += (
            f" It is a mesh VPN ({product}; {vpn_net.peer_routes} peer routes): every "
            "peer that talks to the phone keeps heartbeats and keepalives flowing, "
            "even when the tunnel carries no app data."
        )
    if "vpn_app_rx_pkts" in m:
        summary += (
            f" On battery the VPN app itself received {m['vpn_app_rx_pkts']} and sent "
            f"{m['vpn_app_tx_pkts']} packets ({m['vpn_app_rx_pkts_per_s']}/s received)."
        )
    if "vpn_app_to_tunnel_packets_ratio_max" in m:
        summary += (
            " In one netstats bucket its own packets were "
            f"{m['vpn_app_to_tunnel_packets_ratio_max']}x the packets it tunnelled for "
            "apps: protocol overhead such as peer heartbeats."
        )
    if bare := m.get("kernel_vpn_bare_tx_segments"):
        summary += (
            f" The kernel sent {bare} bare TCP segments (no payload) into the tunnel "
            "and received none back, which looks like resets answering repeated "
            "connection attempts from a peer (inferred)."
        )
    return summary


def _vpn_finding(
    vpn_net: _Network,
    nets: list[_Network],
    evidence: list[Evidence],
    m: dict[str, Any],
) -> Finding:
    """Explain what an active VPN does to standby; stronger for mesh VPNs."""
    mesh = bool(m.get("vpn_mesh"))
    busy = (m.get("vpn_app_rx_pkts_per_s") or 0) >= VPN_BUSY_PKTS_PER_S
    bare = m.get("kernel_vpn_bare_tx_segments") or 0
    severity: Severity = "info"
    if mesh:
        severity = "medium" if busy or bare >= BARE_SEGMENTS_MIN else "low"
    return Finding(
        id="vpn.mesh_vpn_keepalives" if mesh else "vpn.active_vpn",
        title=(
            "Mesh VPN keeps peer heartbeats and keepalives flowing"
            if mesh
            else "A VPN is active"
        ),
        symptom="battery" if mesh else "info",
        severity=severity,
        basis="inferred",
        window="on_battery",
        summary=_vpn_summary(vpn_net, nets, m),
        metrics={
            "package": vpn_net.extra.removeprefix("VPN:"),
            "mesh": mesh,
            "peer_routes": vpn_net.peer_routes,
        },
        evidence=evidence,
        recommendation=(
            "Pause the VPN for one screen-off hour on battery and compare drain and "
            "Wi-Fi wakeups. If it matters, stop whatever on the peers keeps contacting "
            "the phone (monitoring checks, sync or reconnect loops), remove peers the "
            "phone does not need, or turn the VPN on only when needed."
        ),
        followups=list(_VPN_FOLLOWUPS),
    )


_VPN_FOLLOWUPS = (
    (
        "On each peer, capture traffic to the phone's VPN address (for example with "
        "tcpdump on the VPN interface) and look for repeated connection attempts "
        "answered by resets."
    ),
    (
        "On each peer, check whether the VPN lists the phone as an active, direct "
        "connection while the phone is idle."
    ),
    (
        "Compare the VPN app's packets per hour in dumpsys netstats before and after "
        "the change."
    ),
)


@analyzer("vpn", requires=("connectivity",))
def vpn(ctx: Context) -> Result:
    """Detect VPNs, always-on mode and the traffic a mesh VPN keeps alive."""
    conn = ctx.sources.get("connectivity")
    if conn is None:
        msg = "no connectivity dump"
        raise SkipError(msg)
    result = Result("vpn", window="snapshot")
    nets = _parse_networks(conn)
    vpns = [n for n in nets if n.kind == "VPN"]
    owner = _vpn_state(ctx, result)
    net = _netstats(ctx)
    tunnels = {i for i, k in net.ifaces if k == "vpn"} if net else set()
    m = result.metrics
    m["vpn_active"] = bool(vpns)
    m["vpn_interfaces"] = sorted(tunnels) or [n.iface for n in vpns if n.iface]
    result.tables["vpns"] = [
        {
            "package": n.extra.removeprefix("VPN:"),
            "interface": n.iface,
            "peer_routes": n.peer_routes,
            "created": _fmt(_created(ctx, n.created)),
            "ref": conn.ref(n.index),
        }
        for n in vpns
    ]
    if not vpns:
        return result
    first = vpns[0]
    package = first.extra.removeprefix("VPN:")
    m["vpn_mesh"] = (
        package in MESH_VPN_PACKAGES or first.peer_routes >= MESH_MIN_PEER_ROUTES
    )
    if result.tables["vpns"][0]["created"]:
        m["vpn_created"] = result.tables["vpns"][0]["created"]
    if owner is None:
        owner = next(
            (a for a, names in ctx.packages.by_app_id.items() if package in names),
            None,
        )
    evidence = [
        conn.evidence(
            first.index, f"NetworkAgentInfo VPN CONNECTED extra: VPN:{package}"
        )
    ]
    evidence += _vpn_traffic(ctx, owner, _history(ctx), result)
    result.findings.append(_vpn_finding(first, nets, evidence, m))
    return result


# ---------------------------------------------------------------------------
# background_scanning_sensors_location

_BT_APP_RE = re.compile(
    r"^  (?P<app>[A-Za-z][\w.]*(?::\d+)?)(?P<reg> \(Registered\))?\s*$"
)
_BT_SCANS_RE = re.compile(r"LE scans \(started/stopped\)\s*:\s*(?P<a>\d+) / (?P<b>\d+)")
_BT_TIME_RE = re.compile(
    r"Scan time in ms \(active/suspend/total\)\s*:\s*\d+ / \d+ / (?P<t>\d+)"
)
_BT_MODES_RE = re.compile(
    r"Scan time with mode in ms \((?P<names>[^)]*)\)\s*:\s*(?P<v>[\d /]+)"
)
_BT_RESULTS_RE = re.compile(r"Total number of results\s*:\s*(?P<n>\d+)")
_BT_SCAN_RE = re.compile(
    r"^\s+\d\d-\d\d \d\d:\d\d:\d\d - (?P<ms>\d+)ms (?P<flags>.*?)(?P<n>\d+) results",
)
_BT_CONFIG_RE = re.compile(r"ScanMode=(?P<mode>\w+)")
_BT_FILTER_RE = re.compile(r"BluetoothLeScanFilter \[(?P<f>.*)\]")


@dataclass
class _Scanner:
    """One app's BLE scanning from the Bluetooth service (since it started)."""

    app: str
    index: int
    total_ms: int = 0
    scans: int = 0
    results: int | None = None
    modes_ms: dict[str, int] = field(default_factory=dict)
    ongoing: list[dict[str, Any]] = field(default_factory=list)
    section: str = ""


def _parse_scanners(text: Text) -> list[_Scanner]:
    """App blocks of the 'GATT Scanner Map' in ``dumpsys bluetooth_manager``."""
    scanners: list[_Scanner] = []
    inside, current = False, None
    for i, line in enumerate(text.lines):
        if line.strip() == "GATT Scanner Map":
            inside = True
        elif inside and line and not line[0].isspace():
            break
        elif inside and (m := _BT_APP_RE.match(line)):
            current = _Scanner(m["app"], i)
            scanners.append(current)
        elif inside and current:
            try:
                _scanner_line(current, i, line)
            except ValueError:
                continue
    return scanners


def _scanner_line(s: _Scanner, index: int, line: str) -> None:
    """Fold one line of an app block into ``s``."""
    if m := _BT_SCANS_RE.search(line):
        s.scans = int(m["a"])
    elif m := _BT_TIME_RE.search(line):
        s.total_ms = int(m["t"])
    elif m := _BT_MODES_RE.search(line):
        names = [n.strip() for n in m["names"].split("/")]
        values = [int(v) for v in m["v"].split("/") if v.strip()]
        s.modes_ms = {n: v for n, v in zip(names, values, strict=False) if v}
    elif m := _BT_RESULTS_RE.search(line):
        s.results = int(m["n"])
    elif "Ongoing scans" in line or line.strip().startswith("Last "):
        s.section = "ongoing" if "Ongoing" in line else "last"
    elif s.section == "ongoing" and (m := _BT_SCAN_RE.match(line)):
        s.ongoing.append({"ms": int(m["ms"]), "results": int(m["n"]), "index": index})
    elif s.ongoing and s.section == "ongoing":
        if m := _BT_CONFIG_RE.search(line):
            s.ongoing[-1]["mode"] = m["mode"]
        elif m := _BT_FILTER_RE.search(line):
            s.ongoing[-1]["filtered"] = s.ongoing[-1].get("filtered") or bool(
                m["f"].strip()
            )


def _ble(
    ctx: Context,
    stats: _Charged | None,
    result: Result,
) -> list[tuple[str, Evidence]]:
    """BLE scan time and results per app; return problems with evidence."""
    problems: list[tuple[str, Evidence]] = []
    if stats:
        rows: list[dict[str, Any]] = []
        for uid, u in stats.uids.items():
            if not u.ble_ms:
                continue
            name = _uid_name(ctx, uid)
            rows.append(
                {
                    "uid": uid,
                    "name": name,
                    "scan_s": round(u.ble_ms / 1000),
                    "scans": u.ble_count,
                    "results": u.ble_results,
                    "running": u.ble_running,
                }
            )
            if (
                u.ble_ms >= BLE_LONG_SCAN_S * 1000
                and u.ble_results == 0
                and u.ble_index
            ):
                hours = u.ble_ms / 3.6e6
                problems.append(
                    (
                        f"{name} scanned {hours:.1f} h on battery with 0 results",
                        stats.text.evidence(u.ble_index),
                    )
                )
        rows.sort(key=lambda r: -r["scan_s"])
        result.add_table("ble_scans_on_battery", rows)
        if bt := stats.component("bluetooth"):
            result.metrics["bluetooth_modelled_mah"] = bt.mah
    bt_text = ctx.sources.get("bluetooth_manager")
    if bt_text:
        problems += _ble_service(bt_text, result)
    return problems


def _ble_service(text: Text, result: Result) -> list[tuple[str, Evidence]]:
    """Problems among the Bluetooth service's ongoing scans (since BT start)."""
    problems = []
    rows: list[dict[str, Any]] = []
    for s in _parse_scanners(text):
        longest = max(s.ongoing, key=operator.itemgetter("ms"), default=None)
        rows.append(
            {
                "app": s.app,
                "scans": s.scans,
                "scan_s": round(s.total_ms / 1000),
                "results": s.results,
                "mode_s": {k: round(v / 1000) for k, v in s.modes_ms.items()},
                "ongoing_s": round(longest["ms"] / 1000) if longest else 0,
                "ongoing_mode": longest.get("mode") if longest else None,
                "ongoing_filtered": longest.get("filtered") if longest else None,
            }
        )
        if longest is None or longest["ms"] < BLE_LONG_SCAN_S * 1000:
            continue
        hours = longest["ms"] / 3.6e6
        issues = [
            what
            for what, bad in (
                (
                    f"{longest.get('mode', '?')} mode",
                    longest.get("mode") == "LOW_LATENCY",
                ),
                ("no filter", longest.get("filtered") is False),
                ("0 results", longest["results"] == 0),
            )
            if bad
        ]
        if issues:
            problems.append(
                (
                    (
                        f"{s.app} has a scan running for {hours:.1f} h "
                        f"({', '.join(issues)})"
                    ),
                    text.evidence(longest["index"]),
                )
            )
    rows.sort(key=lambda r: -r["scan_s"])
    result.add_table("ble_scanners_since_bt_start", rows)
    return problems


_LOC_PROVIDER_RE = re.compile(r"^    (?P<p>\w+)(?: provider)?:\s*$")
_LOC_AGG_RE = re.compile(
    r"^\s+(?P<uid>\d+)/(?P<pkg>[\w.]+)(?:\[(?P<tag>[^\]]*)\])?: min/max interval = "
    r"(?P<min>\S+)/(?P<max>\S+), total/active/foreground duration = "
    r"(?P<total>[^/]+)/(?P<active>[^/]+)/(?P<fg>[^,]+), locations = (?P<n>\d+)",
)
_LOC_LISTENER_RE = re.compile(
    r"^\s+(?P<uid>\d+)/(?P<pkg>[\w.]+)(?:\[[^\]]*\])?/\w+ (?:\(\w+\) )?"
    r"Request\[(?P<req>.*)\]\s*$",
)
_LOC_INTERVAL_RE = re.compile(r"^@(?P<iv>\+?[\dhmsd]+|0)")
_QUALITY_RE = re.compile(r"\b(HIGH_ACCURACY|BALANCED|LOW_POWER|PASSIVE)\b")


def _interval_s(text: str) -> float | None:
    """Parse a location interval such as '0s', '21600s', '+6h0m0s0ms' or 'passive'."""
    s = text.strip()
    if s.endswith("s") and s[:-1].isdigit():
        return float(s[:-1])
    try:
        return _ms(s) / 1000
    except ValueError:
        return None


def _location(ctx: Context, result: Result) -> list[tuple[str, Evidence]]:
    """Location use per app and provider since the location service started."""
    text = ctx.sources.get("location")
    if text is None:
        return []
    problems: list[tuple[str, Evidence]] = []
    rows: list[dict[str, Any]] = []
    provider, in_agg, skipped = "", False, 0
    for i, line in enumerate(text.lines):
        if line.strip().startswith("Historical Aggregate"):
            in_agg = "Location Provider" in line
        elif m := _LOC_PROVIDER_RE.match(line):
            provider = m["p"]
        else:
            try:
                problem = _location_line(
                    ctx, (provider, in_agg), (i, line), rows, result
                )
            except ValueError:
                skipped += 1
                continue
            if problem:
                problems.append((problem, text.evidence(i)))
    result.add_table("location_requests", rows)
    if skipped:
        result.notes.append(
            f"location: {skipped} lines with unreadable values skipped."
        )
    return problems


def _location_line(
    ctx: Context,
    state: tuple[str, bool],
    numbered: tuple[int, str],
    rows: list[dict[str, Any]],
    result: Result,
) -> str | None:
    """Read a listener or aggregate line; return a problem description if any."""
    provider, in_agg = state
    index, line = numbered
    if m := _LOC_LISTENER_RE.match(line):
        rows.append(_listener_row(provider, m, index))
    elif in_agg and (m := _LOC_AGG_RE.match(line)):
        return _aggregate_row(ctx, provider, m, index, result)
    return None


def _listener_row(provider: str, m: re.Match[str], index: int) -> dict[str, Any]:
    """Describe a current location request: provider, app, quality, interval."""
    request = m["req"]
    quality = _QUALITY_RE.search(request)
    interval = _LOC_INTERVAL_RE.match(request)
    return {
        "provider": provider,
        "uid": int(m["uid"]),
        "package": m["pkg"],
        "quality": quality[1] if quality else None,
        "interval_s": _ms(interval["iv"]) / 1000 if interval else None,
        "line": index + 1,
    }


def _aggregate_row(
    ctx: Context,
    provider: str,
    m: re.Match[str],
    index: int,
    result: Result,
) -> str | None:
    """Record background location use; return a problem description if any."""
    active, fg = _ms(m["active"]), _ms(m["fg"])
    background_s = max(active - fg, 0) / 1000
    min_interval = _interval_s(m["min"])
    rows = result.tables.setdefault("location_use_since_boot", [])
    rows.append(
        {
            "provider": provider,
            "uid": int(m["uid"]),
            "package": m["pkg"],
            "active_s": round(active / 1000),
            "background_s": round(background_s),
            "min_interval_s": min_interval,
            "locations": int(m["n"]),
            "line": index + 1,
        }
    )
    name = _uid_name(ctx, int(m["uid"])) if m["pkg"] == "android" else m["pkg"]
    if provider == "gps" and background_s >= LOCATION_BG_GPS_S:
        return f"{name} used GPS for {background_s / 60:.0f} min in the background"
    fast = min_interval is not None and min_interval < LOCATION_FAST_INTERVAL_S
    if provider != "passive" and fast and background_s >= LOCATION_BG_FAST_S:
        return (
            f"{name} requested {provider} locations every {min_interval:.0f} s for "
            f"{background_s / 3600:.1f} h in the background"
        )
    return None


_SENSOR_LIST_RE = re.compile(
    r"^0x(?P<h>[0-9a-f]+)\) (?P<name>.+?)\s*\|.*?\| type: (?P<type>[\w.]+?)\(\d+\)"
    r".*\| flags: 0x(?P<flags>[0-9a-f]+)",
)
_SENSOR_CONN_RE = re.compile(r"\|\s*uid (?P<uid>\d+)\s*\|")
_SENSOR_ACTIVE_RE = re.compile(
    r"^\s+(?P<name>.+?) 0x(?P<h>[0-9a-f]+) \| status: active"
)
_REPORTING_MODES = ("continuous", "on-change", "one-shot", "special-trigger")


@dataclass
class _Sensor:
    """A hardware sensor from the sensorservice list."""

    name: str
    type: str
    wakeup: bool
    mode: str


def _sensor_list(text: Text | None) -> dict[int, _Sensor]:
    """Map sensor handles to name, type, wakeup flag and reporting mode."""
    sensors: dict[int, _Sensor] = {}
    for _, m in text.find(_SENSOR_LIST_RE) if text else []:
        flags = int(m["flags"], 16)
        mode = _REPORTING_MODES[(flags >> 1) & 0x3]
        sensors.setdefault(
            int(m["h"], 16),
            _Sensor(m["name"].strip(), m["type"], bool(flags & 1), mode),
        )
    return sensors


def _sensors(
    ctx: Context,
    stats: _Charged | None,
    result: Result,
) -> list[tuple[str, Evidence]]:
    """Sensor use per UID on battery and the current listeners."""
    text = ctx.sources.get("sensorservice")
    sensors = _sensor_list(text)
    problems: list[tuple[str, Evidence]] = []
    if stats:
        rows = _sensor_rows(ctx, stats, sensors, problems)
        result.add_table("sensors_on_battery", rows)
    if text:
        result.add_table("sensor_listeners_now", _sensor_listeners(ctx, text, sensors))
    return problems


def _sensor_rows(
    ctx: Context,
    stats: _Charged,
    sensors: dict[int, _Sensor],
    problems: list[tuple[str, Evidence]],
) -> list[dict[str, Any]]:
    """Rank per-UID sensor time on battery; collect costly background use."""
    rows: list[dict[str, Any]] = []
    for uid, u in stats.uids.items():
        for handle, real_ms, bg_ms, index in u.sensors:
            s = sensors.get(int(handle)) if handle.isdigit() else None
            rows.append(
                {
                    "uid": uid,
                    "name": _uid_name(ctx, uid),
                    "sensor": s.name if s else handle,
                    "wakeup": s.wakeup if s else None,
                    "mode": s.mode if s else None,
                    "realtime_s": round(real_ms / 1000),
                    "background_s": round(bg_ms / 1000),
                }
            )
            if s is None or not (s.wakeup and s.mode == "continuous"):
                continue
            app = uid_class(uid, ctx.packages.third_party) != "core"
            if app and bg_ms >= SENSOR_BG_S * 1000:
                hours = bg_ms / 3.6e6
                problems.append(
                    (
                        (
                            f"{_uid_name(ctx, uid)} held the wakeup sensor {s.name} "
                            f"{hours:.1f} h in the background"
                        ),
                        stats.text.evidence(index),
                    )
                )
    rows.sort(key=lambda r: -r["background_s"])
    return rows


def _sensor_listeners(
    ctx: Context,
    text: Text,
    sensors: dict[int, _Sensor],
) -> list[dict[str, Any]]:
    """List current sensorservice connections: who listens to which sensor."""
    rows: list[dict[str, Any]] = []
    uid = None
    for line in text.lines:
        if m := _SENSOR_CONN_RE.search(line):
            uid = int(m["uid"])
        elif uid is not None and (m := _SENSOR_ACTIVE_RE.match(line)):
            s = sensors.get(int(m["h"], 16))
            rows.append(
                {
                    "uid": uid,
                    "name": _uid_name(ctx, uid),
                    "sensor": m["name"].strip(),
                    "wakeup": s.wakeup if s else None,
                    "mode": s.mode if s else None,
                }
            )
    return rows


@analyzer("background_scanning_sensors_location")
def background_scanning_sensors_location(ctx: Context) -> Result:
    """BLE scans, location requests and sensor listeners in the background."""
    keys = ("bluetooth_manager", "location", "sensorservice")
    stats = _charged(ctx)
    if stats is None and not any(ctx.sources.has(k) for k in keys):
        msg = "no batterystats, bluetooth_manager, location or sensorservice dump"
        raise SkipError(msg)
    result = Result("background_scanning_sensors_location", window="on_battery")
    ble = _ble(ctx, stats, result)
    location = _location(ctx, result)
    sensors = _sensors(ctx, stats, result)
    for name in ("gnss", "sensors"):
        if component := (stats.component(name) if stats else None):
            result.metrics[f"{name}_modelled_mah"] = component.mah
    result.metrics["ble_problems"] = len(ble)
    result.metrics["location_problems"] = len(location)
    result.metrics["sensor_problems"] = len(sensors)
    for finding in (
        _scan_finding(ble, "ble", result),
        _scan_finding(location, "location", result),
        _scan_finding(sensors, "sensors", result),
    ):
        if finding:
            result.findings.append(finding)
    return result


_SCAN_TEXT: dict[str, tuple[str, Severity, str, str, tuple[str, str]]] = {
    "ble": (
        "Bluetooth LE scans run for hours",
        "low",
        "Bluetooth scanning",
        (
            "In each app, turn off features that look for nearby devices or beacons "
            "when they are not needed (pairing with a wearable no longer used, beacon "
            "or travel surveys), remove unused companion apps, or restrict their "
            "battery use in Settings > Apps > (app) > App battery usage. Settings > "
            "Location > Location services > Bluetooth scanning controls system "
            "background scans."
        ),
        ("bluetooth_modelled_mah", "Bluetooth"),
    ),
    "location": (
        "Apps use location in the background",
        "medium",
        "location use",
        (
            "Set the app's location permission to 'Allow only while using the app' "
            "(Settings > Location > App location permissions) or turn off the feature "
            "that tracks location."
        ),
        ("gnss_modelled_mah", "GNSS"),
    ),
    "sensors": (
        "Apps keep wakeup sensors on in the background",
        "low",
        "sensor use",
        (
            "Turn off the app feature that needs the sensor (step counting, motion "
            "detection) or restrict the app's background activity."
        ),
        ("sensors_modelled_mah", "sensors"),
    ),
}


def _scan_finding(
    problems: list[tuple[str, Evidence]],
    kind: str,
    result: Result,
) -> Finding | None:
    """One finding per kind of background scanning problem."""
    if not problems:
        return None
    title, severity, what, advice, (metric, label) = _SCAN_TEXT[kind]
    summary = "; ".join(p for p, _ in problems[:5]) + "."
    if metric in result.metrics:
        summary += (
            f" The power model bills {result.metrics[metric]} mAh to {label} on "
            "battery, which leaves out the CPU wakeups these cause."
        )
    return Finding(
        id=f"background_scanning_sensors_location.{kind}",
        title=title,
        symptom="battery",
        severity=severity,
        basis="measured",
        window="on_battery" if kind != "location" else "since_boot",
        summary=summary,
        metrics={"count": len(problems)},
        evidence=[e for _, e in problems[:5]],
        recommendation=advice,
        followups=[
            f"Re-check {what} in the next capture after changing the app settings.",
            "Compare the modelled component in 'Estimated power use' before and after.",
        ],
    )
