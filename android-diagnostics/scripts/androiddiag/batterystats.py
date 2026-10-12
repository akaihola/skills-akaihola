"""The "Statistics since last charge" block of batterystats, parsed once per run.

``dumpsys batterystats --charged`` prints only this block; the full dump and
the bugreport's ``DUMP OF SERVICE batterystats`` contain it after the history.
:func:`load_since_charge` finds it in either and returns a :class:`SinceCharge`
that keeps every value with its line index, so analyzers can cite it.

The block holds the summary header (``Time on battery``, ``Discharge``...),
the ``Estimated power use (mAh)`` model, kernel wakelocks, wakeup reasons and
one block per UID (with ``Proc`` CPU lines). The power model has three
layouts, all read here:

- Android 12-14: ``Global`` component lines (``cpu: 132 apps: 132``) and one
  ``UID u0a1: 79.1 fg: 4.70 ( screen=70.5 cpu=8.41 )`` line per UID.
- Android 15+ with power-state data (AOSP ``BatteryUsageStats.dump``): the
  ``Global`` lines cover all states, then ``(on battery, screen on)``-style
  sub-blocks repeat the components per state; UID lines are followed by
  continuation lines, optionally prefixed with the state.
- Android 11 and older: ``Uid u0a1: 0.540 ( cpu=0.540 ) Including smearing``
  and device rows such as ``Screen: 7.35`` or ``Cell standby: 0.584``.

mAh values below 100 are printed with decimals (``Discharge: 84.7 mAh``,
AOSP ``BatteryStats.formatCharge``) and old builds print the decimal
separator of the phone's locale, so every number goes through
``parse_decimal``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .common import parse_decimal, parse_duration_ms, parse_uid

if TYPE_CHECKING:
    from .model import Context, Evidence
    from .source import Text

_HEADER = "Statistics since last charge"
_NUM = r"\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?"
_DUR = r"(?:\d+(?:ms|d|h|m|s) ?)+"

_HEADER_LINE_RE = re.compile(r"^ {2}(?: {2})?(?P<label>[A-Z][^:]*?): (?P<value>.*\S)")
# Header-like lines that are list entries, not summary values.
_NOT_HEADERS = ("Kernel Wake lock ", "Wake lock ", "Wakeup reason ", "Uid ", "UID ")
_DURATION_RE = re.compile(rf"^(?P<rt>{_DUR})")
_UPTIME_RE = re.compile(rf"realtime, (?P<up>{_DUR})")
_MAH_RE = re.compile(rf"^(?P<mah>{_NUM})\s*mAh\b")

_UID_BLOCK_RE = re.compile(r"^  (?P<uid>u\d+[ais]\d+|\d+):\s*$")
_KERNEL_WAKELOCK_RE = re.compile(
    rf"^\s+Kernel Wake lock (?P<name>.*): (?P<dur>{_DUR})\s*\((?P<n>\d+) times\)"
    r"\s*realtime",
)
_WAKEUP_REASON_RE = re.compile(
    rf"^\s+Wakeup reason (?P<name>.+): (?P<dur>{_DUR})\s*\((?P<n>\d+) times\)"
    r"\s*realtime\s*$",
)
_WAKEUP_REASON_BARE_RE = re.compile(r"^\s+Wakeup reason (?P<name>.+?)\s+realtime\s*$")
_PROC_RE = re.compile(r"^    Proc (?P<name>.+):$")
_PROC_CPU_RE = re.compile(
    r"^\s+CPU: (?P<usr>.+?) usr \+ (?P<krn>.+?) krn(?: ; (?P<fg>.+?) fg)?\s*$",
)
_PROC_COUNTS_RE = re.compile(r"(\d+) (starts|crashes|anrs)\b")

_POWER_HEADER = "Estimated power use (mAh):"
_CAPACITY_RE = re.compile(
    rf"Capacity: (?P<cap>{_NUM})(?:, Rated: (?P<rated>{_NUM}))?"
    rf"(?:, Typical: (?P<typical>{_NUM}))?, Computed drain: (?P<computed>{_NUM}), "
    rf"actual drain: (?P<lo>{_NUM})(?:-(?P<hi>{_NUM}))?",
)
_COMPONENT_LINE_RE = re.compile(
    rf"^\s+(?P<name>[A-Za-z_]\w*): (?P<mah>{_NUM}) apps: (?P<apps>{_NUM})"
    rf"(?: duration: (?P<dur>{_DUR}))?\s*$",
)
_STATE_LABEL_RE = re.compile(r"^\s+\((?P<label>[^()]+)\)\s*$")
_UID_POWER_RE = re.compile(
    rf"^(?P<indent>\s+)U(?:ID|id) (?P<uid>\S+): (?P<total>{_NUM})(?P<rest>.*)$",
)
_CONTINUATION_RE = re.compile(
    r"^(?P<indent>\s+)(?:\((?P<label>[^()]+)\)\s*)?(?P<body>\S.*=.*)$",
)
_DEVICE_ROW_RE = re.compile(
    rf"^\s+(?P<label>[A-Z][A-Za-z -]*?): (?P<mah>{_NUM})(?:\s|$)",
)
_PROCESS_STATE_RE = re.compile(rf"\b(?P<state>fg|bg|fgs|cached): (?P<mah>{_NUM})")
_COMPONENT_RE = re.compile(
    rf"(?<![\w:])(?P<name>[a-z_]+)(?::(?P<state>[a-z]+))?=(?P<mah>{_NUM})"
    rf"(?: \((?P<dur>{_DUR})\s*\))?",
)
_SMEARING = (" Including smearing:", " Excluded from smearing")


def _seconds(text: str) -> float:
    return parse_duration_ms(text) / 1000


def _power_state(label: str) -> str:
    """Return ``on battery`` or ``not on battery`` from a state label, else ``""``."""
    state = label.split(",", 1)[0].strip()
    return state if state in {"on battery", "not on battery"} else ""


def _on_battery_split(
    all_states: dict[str, float],
    states: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Return mAh per component on battery.

    With power-state sub-blocks, a component is the sum of its ``on battery``
    states. AOSP leaves out components without state data, so those keep
    their all-states value; without power states every value is kept.
    """
    if not any(_power_state(label) for label in states):
        return dict(all_states)
    split = {
        name for label, comps in states.items() if _power_state(label) for name in comps
    }
    found = {name: mah for name, mah in all_states.items() if name not in split}
    for label, comps in states.items():
        if _power_state(label) == "on battery":
            for name, mah in comps.items():
                found[name] = found.get(name, 0.0) + mah
    return found


# --- Power model ---------------------------------------------------------------


@dataclass
class PowerComponent:
    """One ``cpu: 133 apps: 133 duration: 1h 59m`` line of the power model."""

    name: str
    mah: float
    apps_mah: float
    duration_s: float | None
    index: int


@dataclass
class UidPower:
    """One UID of the power model, with its continuation lines.

    ``states`` are the process-state shares (``fg``, ``bg``, ``fgs``,
    ``cached``); ``components`` cover all power states, ``power_states``
    holds the per-state components of Android 15+ (``on battery, screen on``).
    """

    uid: int
    total: float
    index: int
    states: dict[str, float] = field(default_factory=dict)
    components: dict[str, float] = field(default_factory=dict)
    durations: dict[str, float] = field(default_factory=dict)
    power_states: dict[str, dict[str, float]] = field(default_factory=dict)
    lines: list[int] = field(default_factory=list)

    def on_battery(self) -> dict[str, float]:
        """Return mAh per component on battery (see ``_on_battery_split``)."""
        return _on_battery_split(self.components, self.power_states)


@dataclass
class PowerModel:
    """The ``Estimated power use (mAh)`` block: modelled, not measured, mAh."""

    index: int
    capacity: float | None = None
    rated: float | None = None  # Samsung
    typical: float | None = None  # Samsung
    computed_drain: float | None = None
    actual_drain_min: float | None = None
    actual_drain_max: float | None = None
    capacity_index: int | None = None
    # Components over all power states (the "Global" lines).
    global_components: dict[str, PowerComponent] = field(default_factory=dict)
    # Android 15+: components per power state, by label.
    state_components: dict[str, dict[str, PowerComponent]] = field(
        default_factory=dict,
    )
    # Android 11 and older: device rows such as "Screen" or "Cell standby".
    device_rows: dict[str, tuple[float, int]] = field(default_factory=dict)
    uids: dict[int, UidPower] = field(default_factory=dict)
    unparsed: int = 0

    def on_battery_components(self) -> dict[str, float]:
        """Return mAh per component on battery.

        With power-state sub-blocks this is the sum of the ``on battery``
        ones, because the ``Global`` lines also count time on the charger.
        """
        states = {
            label: {name: c.mah for name, c in comps.items()}
            for label, comps in self.state_components.items()
        }
        all_states = {name: c.mah for name, c in self.global_components.items()}
        return _on_battery_split(all_states, states)

    def modelled_mah(self) -> float | None:
        """Return the modelled on-battery total, or None without components."""
        components = self.on_battery_components()
        return sum(components.values()) if components else None


def _components(body: str) -> tuple[dict[str, float], dict[str, float]]:
    """Return ``name=mAh`` components (not per process state) and durations."""
    mah: dict[str, float] = {}
    durations: dict[str, float] = {}
    for c in _COMPONENT_RE.finditer(body):
        if c["state"]:
            continue
        mah[c["name"]] = parse_decimal(c["mah"])
        if c["dur"]:
            durations[c["name"]] = _seconds(c["dur"])
    return mah, durations


class _PowerParser:
    """One pass over the lines of the power block."""

    def __init__(self, index: int) -> None:
        self.model = PowerModel(index)
        self.state: str | None = None  # current power-state label
        self.uid: UidPower | None = None
        self.uid_indent = 0

    def line(self, i: int, line: str) -> None:
        try:
            parsed = self._dispatch(i, line)
        except ValueError:
            parsed = False
        if not parsed:
            self.model.unparsed += 1

    def _dispatch(self, i: int, line: str) -> bool:
        """Apply one line; return False if it has no known form."""
        if m := _CAPACITY_RE.search(line):
            self._capacity(i, m)
        elif line.strip() == "Global":
            self.state = None
        elif m := _UID_POWER_RE.match(line):
            self._uid(i, m)
        elif (
            self.uid
            and (m := _CONTINUATION_RE.match(line))
            and len(m["indent"]) > self.uid_indent
        ):
            self._continuation(self.uid, i, m)
        elif m := _STATE_LABEL_RE.match(line):
            self.state, self.uid = m["label"].strip(), None
        elif m := _COMPONENT_LINE_RE.match(line):
            self._component(i, m)
        elif m := _DEVICE_ROW_RE.match(line):
            mah = parse_decimal(m["mah"])
            self.model.device_rows.setdefault(m["label"], (mah, i))
            self.uid = None
        else:
            return False
        return True

    def _capacity(self, i: int, m: re.Match[str]) -> None:
        model = self.model
        model.capacity = parse_decimal(m["cap"])
        model.rated = parse_decimal(m["rated"]) if m["rated"] else None
        model.typical = parse_decimal(m["typical"]) if m["typical"] else None
        model.computed_drain = parse_decimal(m["computed"])
        model.actual_drain_min = parse_decimal(m["lo"])
        model.actual_drain_max = parse_decimal(m["hi"] or m["lo"])
        model.capacity_index = i

    def _uid(self, i: int, m: re.Match[str]) -> None:
        self.uid = None  # an unparsable UID line must not extend the previous UID
        rest = m["rest"]
        for marker in _SMEARING:
            rest = rest.split(marker, 1)[0]
        row = UidPower(parse_uid(m["uid"]), parse_decimal(m["total"]), i, lines=[i])
        row.states = {
            s["state"]: parse_decimal(s["mah"])
            for s in _PROCESS_STATE_RE.finditer(rest)
        }
        row.components, row.durations = _components(rest)
        # The first line of a UID wins; a repeat's continuation lines are dropped.
        self.uid = self.model.uids.setdefault(row.uid, row)
        if self.uid is not row:
            self.uid = None
        self.uid_indent = len(m["indent"])

    def _continuation(self, uid: UidPower, i: int, m: re.Match[str]) -> None:
        mah, durations = _components(m["body"])
        if m["label"]:
            uid.power_states.setdefault(m["label"].strip(), {}).update(mah)
        else:
            uid.components.update(mah)
            uid.durations.update(durations)
        uid.lines.append(i)

    def _component(self, i: int, m: re.Match[str]) -> None:
        component = PowerComponent(
            m["name"],
            parse_decimal(m["mah"]),
            parse_decimal(m["apps"]),
            _seconds(m["dur"]) if m["dur"] else None,
            i,
        )
        if self.state is None:
            target = self.model.global_components
        else:
            target = self.model.state_components.setdefault(self.state, {})
        target.setdefault(component.name, component)
        self.uid = None


# --- Since-charge block ----------------------------------------------------------


@dataclass
class KernelWakelock:
    """One ``Kernel Wake lock NAME: 1m 2s (34 times) realtime`` line."""

    name: str
    seconds: float
    count: int
    index: int


@dataclass
class WakeupReason:
    """One ``Wakeup reason NAME: 43m 5s (5745 times) realtime`` line.

    A bare ``Wakeup reason NAME realtime`` line has no time and no count.
    """

    name: str
    seconds: float | None
    count: int | None
    index: int


@dataclass
class ProcCpu:
    """A ``Proc NAME:`` entry of a UID block and its CPU line."""

    uid: int
    name: str
    index: int
    usr_s: float = 0.0
    krn_s: float = 0.0
    fg_s: float | None = None
    cpu_index: int | None = None
    starts: int = 0
    crashes: int = 0
    anrs: int = 0

    @property
    def cpu_s(self) -> float:
        """User plus kernel CPU seconds on battery."""
        return self.usr_s + self.krn_s


@dataclass
class SinceCharge:
    """The since-charge block with line indexes into ``text``.

    ``start`` is the index of the ``Statistics since last charge:`` line
    (-1 when a ``--charged`` dump has none); ``end`` is one past the block.
    """

    text: Text
    start: int
    end: int
    headers: dict[str, tuple[str, int]] = field(default_factory=dict)
    power: PowerModel | None = None
    kernel_wakelocks: list[KernelWakelock] = field(default_factory=list)
    wakeup_reasons: list[WakeupReason] = field(default_factory=list)
    uid_blocks: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    procs: list[ProcCpu] = field(default_factory=list)

    def header(self, label: str) -> tuple[str, int] | None:
        """Return ``(value, line index)`` of a ``Label: value`` summary line."""
        return self.headers.get(label)

    def evidence(self, label: str) -> list[Evidence]:
        """Cite the summary line ``label``, if present."""
        found = self.headers.get(label)
        return [self.text.evidence(found[1])] if found else []

    def duration_s(self, label: str) -> tuple[float, float | None] | None:
        """Return ``(realtime s, uptime s or None)`` of a duration line.

        ``Time on battery: 5h 2m 40s (99,1%) realtime, 3h 22m (66,9%) uptime``
        gives both; ``Time on battery screen doze: 0ms (0,0%)`` only realtime.
        """
        found = self.headers.get(label)
        if found is None or not (m := _DURATION_RE.match(found[0])):
            return None
        up = _UPTIME_RE.search(found[0])
        return _seconds(m["rt"]), _seconds(up["up"]) if up else None

    def mah(self, label: str) -> float | None:
        """Return the mAh of a line such as ``Discharge: 84.7 mAh``."""
        found = self.headers.get(label)
        if found is None or not (m := _MAH_RE.match(found[0])):
            return None
        return parse_decimal(m["mah"])

    def lines(self) -> list[tuple[int, str]]:
        """Return ``(index, line)`` for every line of the block."""
        return [(i, self.text.lines[i]) for i in range(self.start + 1, self.end)]


def _in_power_block(line: str) -> bool:
    """Power lines are indented by 4+, UID lines of Android 15+ by 2."""
    if line.startswith("    "):
        return bool(line.strip())
    return line.startswith(("  UID ", "  Uid "))


class _BlockParser:
    """One pass over the since-charge block."""

    def __init__(self, result: SinceCharge) -> None:
        self.result = result
        self.power: _PowerParser | None = None
        self.uid: int | None = None
        self.proc: ProcCpu | None = None

    def line(self, i: int, line: str) -> None:
        if self.power is not None:
            if _in_power_block(line):
                self.power.line(i, line)
                return
            self.power = None
        if m := _UID_BLOCK_RE.match(line):
            self.uid, self.proc = parse_uid(m["uid"]), None
            self.result.uid_blocks.setdefault(self.uid, [])
        elif self.uid is not None and line.startswith("    "):
            self.result.uid_blocks[self.uid].append((i, line))
            self._uid_line(self.uid, i, line)
        elif line.strip():
            self.uid = self.proc = None
            self._top_line(i, line)

    def _top_line(self, i: int, line: str) -> None:
        result = self.result
        if line.strip() == _POWER_HEADER:
            self.power = _PowerParser(i)
            # A since-charge block has one model; keep the first.
            result.power = result.power or self.power.model
        elif m := _KERNEL_WAKELOCK_RE.match(line):
            result.kernel_wakelocks.append(
                KernelWakelock(m["name"], _seconds(m["dur"]), int(m["n"]), i),
            )
        elif m := _WAKEUP_REASON_RE.match(line):
            result.wakeup_reasons.append(
                WakeupReason(m["name"], _seconds(m["dur"]), int(m["n"]), i),
            )
        elif m := _WAKEUP_REASON_BARE_RE.match(line):
            result.wakeup_reasons.append(WakeupReason(m["name"], None, None, i))
        elif (m := _HEADER_LINE_RE.match(line)) and not line.strip().startswith(
            _NOT_HEADERS,
        ):
            result.headers.setdefault(m["label"], (m["value"], i))

    def _uid_line(self, uid: int, i: int, line: str) -> None:
        if m := _PROC_RE.match(line):
            self.proc = ProcCpu(uid, m["name"], i)
            self.result.procs.append(self.proc)
        elif self.proc is None or not line.startswith("      "):
            self.proc = None
        elif m := _PROC_CPU_RE.match(line):
            try:
                self.proc.usr_s = _seconds(m["usr"])
                self.proc.krn_s = _seconds(m["krn"])
                self.proc.fg_s = _seconds(m["fg"]) if m["fg"] else None
            except ValueError:
                return
            self.proc.cpu_index = i
        else:
            for value, kind in _PROC_COUNTS_RE.findall(line):
                setattr(self.proc, kind, int(value))


def parse_since_charge(text: Text, *, whole: bool = False) -> SinceCharge | None:
    """Parse the since-charge block of ``text``, or None if it has none.

    With ``whole``, a text without the ``Statistics since last charge`` line
    (a bare ``--charged`` dump) is read as one block.
    """
    lines = text.lines
    start = next((i for i, x in enumerate(lines) if x.startswith(_HEADER)), None)
    if start is None:
        if not whole:
            return None
        start, end = -1, len(lines)
    else:
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i][:1].strip()),
            len(lines),
        )
    result = SinceCharge(text, start, end)
    parser = _BlockParser(result)
    for i in range(start + 1, end):
        parser.line(i, lines[i])
    found = (
        result.headers,
        result.power,
        result.uid_blocks,
        result.kernel_wakelocks,
        result.wakeup_reasons,
    )
    return result if any(found) else None


def load_since_charge(ctx: Context) -> SinceCharge | None:
    """Return the since-charge block: ``--charged`` first, else the full dump."""

    def build() -> SinceCharge | None:
        if charged := ctx.sources.get("batterystats_charged"):
            found = parse_since_charge(charged) or parse_since_charge(
                charged,
                whole=True,
            )
            if found:
                return found
        full = ctx.sources.get("batterystats")
        return parse_since_charge(full) if full else None

    return ctx.sources.memo("since_charge", build)
