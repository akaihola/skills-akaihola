"""Result types and the analyzer registry.

An analyzer is a function ``(ctx: Context) -> Result`` registered with
:func:`analyzer`. It reads inputs through ``ctx.sources``, may read earlier
results through ``ctx.results``, and returns metrics, tables and findings.

Every number in a finding must say which time window it covers and whether it
was measured (kernel or gauge counters), modelled (the power-profile mAh
estimates of batterystats) or inferred (a heuristic). Those labels let the
report keep measured drain separate from the model, which on some phones misses
most of the standby drain.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING, Any, Literal

from .common import parse_utc_offset

if TYPE_CHECKING:
    from collections.abc import Callable

    from .common import PackageMap
    from .source import Sources

Symptom = Literal["battery", "slowness", "both", "info"]
Severity = Literal["high", "medium", "low", "info"]
Basis = Literal["measured", "modelled", "inferred"]
Status = Literal["ok", "skipped", "error"]

# Findings sort by this rank; unknown severities go last.
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}

# Default row limit of result tables (see Result.add_table).
TABLE_CAP = 25

# Window names used in metrics and findings.
WINDOWS = {
    "since_charge": "since the last full charge (batterystats --charged)",
    "on_battery": "time on battery since the last full charge",
    "screen_off_on_battery": "screen-off time on battery since the last full charge",
    "since_boot": "since the last boot",
    "last_24h": "the last 24 hours",
    "daily": "the daily step history (about 10 days)",
    "previous_charge": "the charge period before the current one",
    "recent_history": "records kept across reboots (dropbox, exit and start info)",
    "log_coverage": "the time span covered by the log buffer",
    "snapshot": "the moment of collection",
}


@dataclass
class Evidence:
    """A citation: where a value or line came from."""

    ref: str  # "live/batterystats_charged.txt:462" or "bugreport:KERNEL LOG:1234"
    excerpt: str = ""


@dataclass
class Finding:
    """One diagnosed problem or notable fact, ready for the report."""

    id: str  # "<analyzer>.<slug>"
    title: str
    symptom: Symptom
    severity: Severity
    basis: Basis
    window: str  # a key of WINDOWS
    summary: str  # one or two sentences with the key numbers
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    recommendation: str = ""
    followups: list[str] = field(default_factory=list)
    # Ids of other findings that state the same fact or explain this one.
    related: list[str] = field(default_factory=list)


@dataclass
class Result:
    """What one analyzer produced."""

    analyzer: str
    status: Status = "ok"
    reason: str = ""
    window: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)

    def add_table(self, name: str, rows: list[dict], cap: int = TABLE_CAP) -> None:
        """Store the first ``cap`` rows as table ``name``; note any cut rows."""
        self.tables[name] = rows[:cap]
        if len(rows) > cap:
            self.notes.append(f"{name}: showing {cap} of {len(rows)} rows")


@dataclass
class Windows:
    """Time anchors shared by all analyzers; any field may be unknown (None).

    Device times are naive local wall time, as the phone prints them.
    """

    dump_time: datetime | None = None
    boot_time: datetime | None = None
    since_charge_start: datetime | None = None
    on_battery_at_capture: bool | None = None
    on_battery_s: float | None = None
    screen_off_on_battery_s: float | None = None
    plugged_at: datetime | None = None
    utc_offset: str | None = None  # "+0300", the offset at capture
    zone: tzinfo | None = None  # the phone's time zone (persist.sys.timezone)
    plugged_at_source: str | None = None  # how plugged_at was found
    on_battery_uptime_s: float | None = None  # awake part of on_battery_s
    screen_off_uptime_s: float | None = None  # awake part of screen-off time

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict with ISO timestamps."""
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, datetime):
                value = value.isoformat(sep=" ")
            elif isinstance(value, tzinfo):
                value = str(value)
            out[f.name] = value
        return out

    def offset(self) -> timedelta | None:
        """Return ``utc_offset`` as a timedelta, or None when unknown or malformed."""
        return parse_utc_offset(self.utc_offset)

    def local_from_epoch(self, epoch_s: float) -> datetime | None:
        """Return the phone's naive local wall time of a Unix time.

        The time zone handles daylight saving; without it the fixed offset at
        capture is used. Returns None when neither is known.
        """
        offset = self.offset()
        zone = self.zone or (timezone(offset) if offset is not None else None)
        if zone is None:
            return None
        try:
            return datetime.fromtimestamp(epoch_s, tz=zone).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None

    def battery_span(self) -> tuple[datetime, datetime] | None:
        """Return the on-battery stretch since the last full charge.

        It starts at ``since_charge_start`` and ends at ``plugged_at`` when
        the phone was charging at capture, else at ``dump_time``. Returns None
        when an end is unknown or not after the start.
        """
        start = self.since_charge_start
        if start is None:
            return None
        charging = self.on_battery_at_capture is False
        end = self.plugged_at if charging else self.dump_time
        return (start, end) if end is not None and end > start else None

    def log_reference(self) -> datetime:
        """Return the time used to pick the year of yearless log stamps.

        Without a capture time, the current time keeps recent logs in the
        right year.
        """
        return self.dump_time or datetime.now()


@dataclass
class Context:
    """Everything an analyzer may read."""

    sources: Sources
    packages: PackageMap
    windows: Windows
    results: dict[str, Result] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def finding(self, finding_id: str) -> Finding | None:
        """Return the finding ``finding_id`` if an analyzer that ran emitted it."""
        result = self.results.get(finding_id.split(".", 1)[0])
        if result is None:
            return None
        return next((f for f in result.findings if f.id == finding_id), None)


def link(owner: Finding, member: Finding, *, mutual: bool = True) -> None:
    """Record that ``member`` restates part of ``owner``'s fact.

    The owner lists the member and, with ``mutual``, the member names the
    owner. The report folds the weaker of two linked findings into the
    stronger (``budget.owner_map``); on equal strength a one-way link makes
    the lister the owner, while a mutual link picks the lower id.
    """
    if member.id not in owner.related:
        owner.related.append(member.id)
    if mutual and owner.id not in member.related:
        member.related.append(owner.id)


class SkipError(Exception):
    """Raise from an analyzer when its inputs are absent or not applicable."""


@dataclass
class Registration:
    """An analyzer function with its declared inputs and ordering."""

    name: str
    func: Callable[[Context], Result]
    requires: tuple[str, ...]
    after: tuple[str, ...]
    module: str


REGISTRY: dict[str, Registration] = {}


def analyzer(
    name: str,
    *,
    requires: tuple[str, ...] = (),
    after: tuple[str, ...] = ("windows",),
) -> Callable[[Callable[[Context], Result]], Callable[[Context], Result]]:
    """Register an analyzer.

    ``requires`` lists source keys that must all be present, otherwise the
    analyzer is reported as skipped without being called. ``after`` lists
    analyzers whose results this one reads from ``ctx.results``.
    """

    def register(func: Callable[[Context], Result]) -> Callable[[Context], Result]:
        if name in REGISTRY:
            msg = f"analyzer {name!r} registered twice"
            raise ValueError(msg)
        REGISTRY[name] = Registration(
            name=name,
            func=func,
            requires=requires,
            after=() if name == "windows" else after,
            module=func.__module__,
        )
        return func

    return register


def run_order(registrations: dict[str, Registration]) -> list[Registration]:
    """Order analyzers so each runs after the ones it reads; ties keep names."""
    ordered: list[Registration] = []
    done: set[str] = set()
    pending = dict(sorted(registrations.items()))
    while pending:
        ready = [
            r
            for r in pending.values()
            if all(dep in done or dep not in registrations for dep in r.after)
        ]
        if not ready:
            cycle = ", ".join(sorted(pending))
            msg = f"analyzer dependency cycle among: {cycle}"
            raise ValueError(msg)
        for reg in ready:
            ordered.append(reg)
            done.add(reg.name)
            del pending[reg.name]
    return ordered
