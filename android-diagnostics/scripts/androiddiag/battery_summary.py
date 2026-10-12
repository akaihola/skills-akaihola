"""Since-charge batterystats summaries: wakeups, wakelocks, multicast, power model.

The analyzers here read the "Statistics since last charge" block, parsed once
by :func:`androiddiag.batterystats.load_since_charge`, and the service dumps
that explain it: alarms, jobs, Wi-Fi, the network stack and the OEM power
profile.

Batterystats counts cover the time on battery since the last full charge,
except those on its screen-off time base (AOSP BatteryStatsImpl): kernel and
partial wakelocks and wakeup alarms count only with the screen off (doze
included) on battery. Its mAh figures come in two kinds. "Discharge" is the
fuel gauge's counter (measured); "Estimated power use" is a model built from
the OEM power profile (modelled). Some profiles price sleep and awake-idle time
at about 0 mA, and the model then misses most standby drain, so the two are
kept apart here.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .battery_history import checkin_rows
from .batterystats import load_since_charge
from .common import (
    fmt_duration,
    format_uid,
    parse_decimal,
    parse_duration_ms,
    parse_uid,
    pct,
    per_hour,
)
from .model import Context, Evidence, Finding, Result, SkipError, analyzer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .batterystats import PowerModel, SinceCharge, UidPower
    from .source import Text

MIN_EVENTS = 50  # below this many events, ratios and rates are noise
MIN_HOURS = 0.5  # shorter windows give unstable per-hour rates

# Aborted suspend attempts per real resume. Healthy kernels abort now and
# then. At 0.5 every other wake is followed by a failed attempt to sleep; at
# 1.0 or more each wake costs extra awake time in retries and backoff.
ABORT_RATIO_FLAG = 0.5
ABORT_RATIO_HIGH = 1.0
# A top abort reason within this factor of the resume count tracks the
# resumes one to one: a side effect of each resume, not a separate source.
PER_RESUME_LOW = 0.8
PER_RESUME_HIGH = 1.25

# A kernel wakeup source taken this many times per real resume, for at least
# CHURN_MIN_S in total, is re-armed on every wake.
CHURN_PER_RESUME = 10
CHURN_MIN_S = 60
# One UID holding partial wakelocks this long per screen-off hour (5 %)
# keeps the phone awake noticeably on its own.
HEAVY_PARTIAL_S_PER_H = 180
# PowerManager.SuspendLockout means autosuspend is off. Ten minutes of it with
# the screen off on battery is far more than housekeeping needs.
LOCKOUT_SCREEN_OFF_S = 600
# One lockout longer than an hour since boot deserves a look: normal for long
# screen-on or projection sessions, a drain if the screen was off.
LOCKOUT_SINCE_BOOT_S = 3600

# A Wi-Fi multicast lock held for most of the battery time keeps the Wi-Fi
# chip passing LAN multicast (mDNS, SSDP) to the host, also while dozing.
MULTICAST_SHARE_PCT = 50

# Share of the measured discharge that no model component explains. Above
# this, per-app lists such as Settings > Battery usage cannot rank causes.
UNMODELLED_PCT = 30
# Kernel (UID 0) plus system (UID 1000) share of the per-UID estimates above
# which wake-triggered system work, not apps, dominates the model.
SYSTEM_UID_PCT = 30
# An app's non-screen model mAh as a share of the discharge worth flagging.
APP_BACKGROUND_PCT = 5
# Current the model charges for awake-idle time below which it does not price
# being awake. Real SoCs draw tens of mA awake (general knowledge).
MODEL_AWAKE_FLOOR_MA = 1.0
# The model's awake-idle component must cover this long to be judged.
MIN_MODEL_AWAKE_S = 1800
# Two drain figures closer than this are the same figure.
SAME_MAH = 1.0

# Power-profile currents for standby states below this are placeholders: real
# hardware draws milliamps when suspended, idle or associated to Wi-Fi.
PROFILE_ZERO_MA = 1.0
STANDBY_KEYS = (
    "cpu.suspend",
    "cpu.idle",
    "cpu.awake",
    "wifi.on",
    "modem.controller.sleep",
    "modem.controller.idle",
)
# CPU minutes at zero-priced frequency steps worth a finding.
ZERO_STEP_MIN_MINUTES = 1.0

# One app's alarm tag firing wakeup alarms more than once per 10 minutes.
ALARMS_PER_H = 6
# Wakeup alarms plus job runs above this share of real resumes may drive
# standby wakes; below it they are not the main source.
ALARM_JOB_SHARE_PCT = 10
# Job run time per battery hour for one UID that is a cost of its own.
JOB_S_PER_H = 120

_S_PER_H = 3600
_MS_PER_S = 1000
_MS_PER_MIN = 60_000
_MS_MA_PER_MAH = 3_600_000  # ms x mA / 3.6e6 = mAh
_SYSTEM_UIDS = (0, 1000)
_FIRST_APP_ID = 10_000

_DUR = r"(?:\d+(?:ms|d|h|m|s) ?)+"
_NUM = r"\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?"
_UID = r"u\d+[ais]\d+|\d+"
_COMPACT_DUR = r"(?:\d+(?:ms|d|h|m|s))+"  # alarm and job offsets: +38s482ms

# Since-charge summary labels.
_ON_BATTERY = "Time on battery"
_SCREEN_OFF = "Time on battery screen off"
_APK_RE = re.compile(r"^    Apk (?P<pkg>\S+):\s*$")
_UID_HEADER_RE = re.compile(rf"^  (?P<uid>{_UID}):\s*$")


def _per_h(count: float, seconds: float | None) -> float | None:
    """Return a rate per hour, or None for windows too short to rate."""
    if not seconds or seconds < MIN_HOURS * _S_PER_H:
        return None
    return per_hour(count, seconds)


def _since_charge(ctx: Context) -> SinceCharge:
    """Return the since-charge block, or skip the analyzer without one."""
    since = load_since_charge(ctx)
    if since is None:
        msg = "no 'Statistics since last charge' block in batterystats"
        raise SkipError(msg)
    return since


def _durations(since: SinceCharge, label: str) -> tuple[float | None, float | None]:
    """Return ``(realtime s, uptime s)`` of a summary duration line, if present."""
    return since.duration_s(label) or (None, None)


def _section(since: SinceCharge, header: str) -> list[tuple[int, str]]:
    """Return the lines under ``header`` up to the next blank line."""
    rows: list[tuple[int, str]] = []
    inside = False
    for i, line in since.lines():
        if not inside:
            inside = line.strip() == header
        elif line.strip():
            rows.append((i, line))
        else:
            break
    return rows


def _unparsed(since: SinceCharge, prefix: str, parsed: set[int]) -> int:
    """Count block lines starting with ``prefix`` that no parser understood."""
    return sum(
        1
        for i, line in since.lines()
        if i not in parsed and line.lstrip().startswith(prefix)
    )


def _uid_lines(since: SinceCharge) -> Iterator[tuple[int, str, int, str | None]]:
    """Yield ``(index, line, uid, apk)`` for the per-UID part of the block.

    UID blocks are scanned here rather than read from ``since.uid_blocks``:
    some Samsung builds indent one line of a UID block by three spaces
    (``   Screen-off cpu times per freq ...``), which ends the block there.
    """
    uid: int | None = None
    apk: str | None = None
    for i, line in since.lines():
        if m := _UID_HEADER_RE.match(line):
            uid, apk = parse_uid(m["uid"]), None
        elif uid is None:
            continue
        elif not line.startswith("   "):
            uid = None if line.strip() else uid
        elif m := _APK_RE.match(line):
            apk = m["pkg"]
        else:
            if not line.startswith("     "):
                apk = None
            yield i, line, uid, apk


def _screen_off_resumes(ctx: Context) -> int | None:
    """Screen-off resumes on battery from the history replay (standby_wake)."""
    standby = ctx.results.get("standby_wake")
    if standby is None or standby.status != "ok":
        return None
    return standby.metrics.get("resumes")


# Wakeup reasons: real IRQ resumes and aborted suspend attempts.

# (kind, pattern, whether group 1 is a space-separated wakeup source list)
_ABORT_KINDS = (
    (
        "pending_wakeup_sources",
        re.compile(r"^Abort: Pending Wakeup Sources?: (.*)$"),
        True,
    ),
    (
        "last_active_wakeup_source",
        re.compile(r"^Abort: Last active Wakeup Source: (.*)$"),
        True,
    ),
    ("callback_failed", re.compile(r"^Abort: Callback failed on (\S+)"), False),
    (
        "noirq_suspend_failed",
        re.compile(r"^Abort: noirq suspend of (\S+) device failed"),
        False,
    ),
    ("cpu_offline_failed", re.compile(r"^Abort: (Disabling non-boot cpus)"), False),
)


@dataclass
class _Reason:
    name: str
    count: int
    seconds: float
    index: int
    counted: bool
    abort_kind: str | None = None  # None for a real resume
    sources: list[str] = field(default_factory=list)

    @property
    def is_abort(self) -> bool:
        return self.abort_kind is not None


def _classify(reason: _Reason) -> None:
    if not reason.name.startswith("Abort"):
        return
    reason.abort_kind = "other"
    for kind, regex, is_list in _ABORT_KINDS:
        if m := regex.match(reason.name):
            reason.abort_kind = kind
            reason.sources = list(dict.fromkeys(m[1].split())) if is_list else [m[1]]
            return


def _parse_wakeup_reasons(since: SinceCharge) -> tuple[list[_Reason], int]:
    """Return the wakeup reasons and the number of unparsable reason lines."""
    reasons = []
    for w in since.wakeup_reasons:
        counted = w.count is not None
        reason = _Reason(w.name, w.count or 0, w.seconds or 0.0, w.index, counted)
        _classify(reason)
        reasons.append(reason)
    parsed = {r.index for r in reasons}
    return reasons, _unparsed(since, "Wakeup reason", parsed)


def _resume_count(ctx: Context, since: SinceCharge | None) -> int | None:
    """Real resumes on battery, from the wakeup_reasons result or reparsed."""
    earlier = ctx.results.get("wakeup_reasons")
    if earlier and earlier.status == "ok":
        return earlier.metrics.get("resumes")
    if since is None:
        return None
    reasons, _ = _parse_wakeup_reasons(since)
    if not reasons:
        return None
    return sum(r.count for r in reasons if not r.is_abort)


def _reason_rows(
    reasons: list[_Reason],
    since: SinceCharge,
    on_s: float | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "reason": r.name,
            "class": "abort" if r.is_abort else "resume",
            "abort_kind": r.abort_kind,
            "count": r.count,
            "awake_after_s": round(r.seconds, 1),
            "awake_per_event_s": round(r.seconds / r.count, 2) if r.count else None,
            "per_h": _per_h(r.count, on_s),
            "ref": since.text.ref(r.index),
        }
        for r in reasons
    ]
    rows.sort(key=lambda row: (-row["count"], -row["awake_after_s"]))
    return rows


def _abort_tables(aborts: list[_Reason]) -> dict[str, list[dict[str, Any]]]:
    kinds: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    sources: Counter[str] = Counter()
    for r in aborts:
        entry = kinds[r.abort_kind or "other"]
        entry[0] += r.count
        entry[1] += r.seconds
        for source in r.sources:
            sources[source] += r.count
    return {
        "abort_kinds": sorted(
            (
                {"kind": k, "aborts": int(v[0]), "awake_after_s": round(v[1], 1)}
                for k, v in kinds.items()
            ),
            key=lambda row: -row["aborts"],
        ),
        "abort_sources": [
            {"source": s, "aborts": n} for s, n in sources.most_common() if n
        ],
    }


def _reason_metrics(
    resumes: list[_Reason],
    aborts: list[_Reason],
    on_s: float | None,
    on_up_s: float | None,
) -> dict[str, Any]:
    n_res = sum(r.count for r in resumes)
    n_ab = sum(r.count for r in aborts)
    t_res = sum(r.seconds for r in resumes)
    t_ab = sum(r.seconds for r in aborts)
    top_res = max(resumes, key=lambda r: r.count, default=None)
    top_ab = max(aborts, key=lambda r: r.count, default=None)
    return {
        "reason_lines": len(resumes) + len(aborts),
        "reason_lines_without_counts": sum(
            1 for r in resumes + aborts if not r.counted
        ),
        "resumes": n_res,
        "aborts": n_ab,
        "abort_to_resume_ratio": round(n_ab / n_res, 2) if n_res else None,
        "resumes_per_h": _per_h(n_res, on_s),
        "aborts_per_h": _per_h(n_ab, on_s),
        "awake_after_resumes_s": round(t_res, 1),
        "awake_after_aborts_s": round(t_ab, 1),
        "awake_after_aborts_pct_of_uptime": pct(t_ab, on_up_s),
        "awake_per_resume_s": round(t_res / n_res, 2) if n_res else None,
        "awake_per_abort_s": round(t_ab / n_ab, 2) if n_ab else None,
        "top_resume_reason": top_res.name if top_res else None,
        "top_resume_count": top_res.count if top_res else None,
        "top_resume_share_pct": pct(top_res.count, n_res) if top_res else None,
        "top_abort_reason": top_ab.name if top_ab else None,
        "top_abort_count": top_ab.count if top_ab else None,
        "on_battery_h": round(on_s / _S_PER_H, 2) if on_s else None,
        "on_battery_uptime_h": round(on_up_s / _S_PER_H, 2) if on_up_s else None,
    }


def _checkin_cross_check(ctx: Context, metrics: dict[str, Any], result: Result) -> None:
    """Compare with the machine-readable ``wr`` rows of the checkin dump."""
    rows = checkin_rows(ctx).get("wr", [])
    if not rows:
        return
    resumes = aborts = 0
    for _, fields in rows:
        try:
            count = int(fields[2])
        except (IndexError, ValueError):
            continue
        if fields[0].startswith("Abort"):
            aborts += count
        else:
            resumes += count
    metrics["checkin_resumes"] = resumes
    metrics["checkin_aborts"] = aborts
    if (resumes, aborts) != (metrics["resumes"], metrics["aborts"]):
        origin = (
            text.origin if (text := ctx.sources.get("batterystats_checkin")) else ""
        )
        result.notes.append(
            f"Checkin 'wr' rows in {origin} give {resumes} resumes and "
            f"{aborts} aborts since the last charge; the text dump gives "
            f"{metrics['resumes']} and {metrics['aborts']}. Small differences "
            "come from dumps taken at different moments; large ones mean the "
            "checkin covers another charge period.",
        )


def _kernel_abort_metrics(ctx: Context, metrics: dict[str, Any]) -> list[str]:
    """Add the since-boot and log-sample abort figures; return summary sentences."""
    stats = ctx.results.get("suspend_stats")
    kernel = ctx.results.get("kernel_suspend")
    failed = stats.metrics.get("fail_share_pct") if stats else None
    sample = kernel.metrics.get("aborts_per_deep_resume") if kernel else None
    metrics["since_boot_failed_suspend_pct"] = failed
    metrics["log_sample_aborts_per_resume"] = sample
    parts = []
    if failed is not None:
        parts.append(
            f"Since boot the suspend service counts {failed}% of suspend attempts "
            "as failed (suspend_stats).",
        )
    if sample is not None:
        parts.append(
            f"The kernel log sample shows {sample} aborts per real resume "
            "(kernel_suspend).",
        )
    return parts


def _abort_finding(
    metrics: dict[str, Any],
    aborts: list[_Reason],
    since: SinceCharge,
    other_windows: list[str],
) -> Finding | None:
    ratio = metrics["abort_to_resume_ratio"]
    if ratio is None or ratio < ABORT_RATIO_FLAG or metrics["aborts"] < MIN_EVENTS:
        return None
    top = sorted(aborts, key=lambda r: -r.count)[:3]
    tracks = ""
    per_resume = top[0].count / metrics["resumes"] if metrics["resumes"] else 0
    if PER_RESUME_LOW <= per_resume <= PER_RESUME_HIGH:
        tracks = (
            f" The top abort happens about once per real resume ({per_resume:.2f}"
            " per resume), which points to a side effect of each resume rather"
            " than an independent wake source (inferred)."
        )
    share = metrics["awake_after_aborts_pct_of_uptime"]
    share_text = f" ({share}% of the awake time on battery)" if share else ""
    return Finding(
        id="wakeup_reasons.suspend_aborts",
        title=(
            "Suspend attempts abort more often than the phone really wakes"
            if ratio >= ABORT_RATIO_HIGH
            else "Many suspend attempts abort"
        ),
        symptom="battery",
        severity="high" if ratio >= ABORT_RATIO_HIGH else "medium",
        basis="measured",
        window="on_battery",
        summary=" ".join(
            [
                (
                    f"{metrics['aborts']:,} suspend attempts aborted against "
                    f"{metrics['resumes']:,} real resumes on battery (ratio "
                    f"{ratio}). The awake time after aborts adds up to "
                    f"{fmt_duration(metrics['awake_after_aborts_s'])}{share_text}. "
                    f"Top abort: '{top[0].name}' ({top[0].count:,} times).{tracks}"
                ),
                *other_windows,
            ],
        ),
        metrics={
            k: metrics[k]
            for k in (
                "aborts",
                "resumes",
                "abort_to_resume_ratio",
                "awake_after_aborts_s",
                "awake_after_aborts_pct_of_uptime",
                "top_abort_reason",
                "top_abort_count",
                "since_boot_failed_suspend_pct",
                "log_sample_aborts_per_resume",
            )
        },
        evidence=[since.text.evidence(r.index) for r in top],
        recommendation=(
            "An aborted suspend means a wakeup source or driver refused to sleep "
            "right after a wake, so each wake keeps the SoC up longer. Look up "
            "the named wakeup sources and devices in the kernel log around the "
            "suspend-abort lines; driver and firmware causes need an OS update "
            "from the vendor. Fewer real wakes also means fewer aborts."
        ),
        followups=[
            (
                "Read the kernel log (dmesg, bugreport KERNEL LOG) for the events "
                "just before each 'Abort' to find what keeps the source pending."
            ),
            (
                "Check whether the top abort's count follows the top resume IRQ's "
                "count across charge periods (checkin 'wr' rows)."
            ),
        ],
    )


@analyzer("wakeup_reasons", after=("windows", "kernel_suspend", "suspend_stats"))
def wakeup_reasons(ctx: Context) -> Result:
    """Count real IRQ resumes and aborted suspends since the last charge."""
    since = _since_charge(ctx)
    reasons, bad = _parse_wakeup_reasons(since)
    if not reasons:
        msg = "batterystats has no 'All wakeup reasons' lines"
        raise SkipError(msg)
    result = Result("wakeup_reasons", window="on_battery")
    if bad:
        result.notes.append(f"{bad} wakeup-reason lines could not be parsed.")
    resumes = [r for r in reasons if not r.is_abort]
    aborts = [r for r in reasons if r.is_abort]
    on_s, on_up_s = _durations(since, _ON_BATTERY)
    result.metrics = _reason_metrics(resumes, aborts, on_s, on_up_s)
    result.add_table("reasons", _reason_rows(reasons, since, on_s))
    for name, rows in _abort_tables(aborts).items():
        result.add_table(name, rows)
    _checkin_cross_check(ctx, result.metrics, result)
    other_windows = _kernel_abort_metrics(ctx, result.metrics)
    result.notes.append(
        "The time listed with each reason is the awake (uptime) time that "
        "followed it until the next suspend attempt. The resume rate and top "
        "wake reason are reported by standby_wake.awake_share for the "
        "screen-off time; they stay here as metrics and tables.",
    )
    if finding := _abort_finding(result.metrics, aborts, since, other_windows):
        result.findings.append(finding)
    return result


# Wakelocks: kernel wakeup sources, app partial wakelocks, SuspendLockout.

_PARTIAL_WL_RE = re.compile(
    rf"^\s+Wake lock (?P<uid>{_UID}) (?P<tag>.+): (?P<dur>{_DUR})\s*"
    r"\((?P<n>\d+) times\)(?: max=(?P<max>\d+))?(?: actual=(?P<actual>\d+))?"
    r"\s*realtime\s*$",
)
_PARTIAL_BARE_RE = re.compile(rf"^\s+Wake lock (?:{_UID}) .+ realtime\s*$")
_TOTAL_WAKE_RE = re.compile(r"^\s+TOTAL wake: (?P<body>.+?)\s*realtime\s*$")
_WAKE_PART_RE = re.compile(
    rf"^(?P<dur>{_DUR})\s*(?P<kind>full|blamed partial|actual background partial"
    r"|actual partial|window)$",
)
_AUTOSUSPEND_RE = re.compile(
    r"^\s*(?P<key>mUseAutoSuspend|mHalAutoSuspendModeEnabled"
    r"|mDecoupleHalAutoSuspendModeFromDisplayConfig)=(?P<value>true|false)",
)
_AUTOSUSPEND_METRICS = {
    "mUseAutoSuspend": "use_auto_suspend",
    "mHalAutoSuspendModeEnabled": "hal_auto_suspend_mode_enabled",
    "mDecoupleHalAutoSuspendModeFromDisplayConfig": (
        "decouple_hal_auto_suspend_from_display"
    ),
}
_LOCKOUT = "PowerManager.SuspendLockout"


@dataclass
class _Lock:
    name: str
    seconds: float
    count: int
    index: int
    uid: int | None = None
    max_ms: int | None = None
    actual_ms: int | None = None


@dataclass
class _Wakelocks:
    kernel: list[_Lock] = field(default_factory=list)
    partial: list[_Lock] = field(default_factory=list)
    uid_totals: dict[int, dict[str, Any]] = field(default_factory=dict)
    bad: Counter[str] = field(default_factory=Counter)


def _parse_wakelocks(since: SinceCharge) -> _Wakelocks:
    found = _Wakelocks(
        kernel=[
            _Lock(k.name, k.seconds, k.count, k.index) for k in since.kernel_wakelocks
        ],
    )
    parsed = {k.index for k in found.kernel}
    if bad := _unparsed(since, "Kernel Wake lock", parsed):
        found.bad["All kernel wake locks"] = bad
    for i, line in _section(since, "All partial wake locks:"):
        if m := _PARTIAL_WL_RE.match(line):
            found.partial.append(
                _Lock(
                    m["tag"],
                    parse_duration_ms(m["dur"]) / _MS_PER_S,
                    int(m["n"]),
                    i,
                    uid=parse_uid(m["uid"]),
                    max_ms=int(m["max"]) if m["max"] else None,
                    actual_ms=int(m["actual"]) if m["actual"] else None,
                ),
            )
        elif not _PARTIAL_BARE_RE.match(line):
            found.bad["All partial wake locks"] += 1
    for i, line, uid, _apk in _uid_lines(since):
        if m := _TOTAL_WAKE_RE.match(line):
            totals: dict[str, Any] = {"index": i}
            for part in m["body"].split(", "):
                if p := _WAKE_PART_RE.match(part.strip()):
                    totals[p["kind"]] = parse_duration_ms(p["dur"]) / _MS_PER_S
                else:
                    found.bad["TOTAL wake"] += 1
            found.uid_totals[uid] = totals
    return found


def _lockout_since_boot(ctx: Context) -> tuple[dict[str, Any], Evidence] | None:
    """Read the SuspendLockout row of suspend_control_internal (since boot)."""
    text = ctx.sources.get("suspend_control")
    if text is None:
        return None
    columns: list[str] = []
    for i, line in enumerate(text.lines):
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == "NAME":
            columns = cells
        elif columns and cells and cells[0] == _LOCKOUT:
            row = dict(zip(columns, cells, strict=False))
            try:
                values = {
                    "count": int(row["ACTIVE COUNT"]),
                    "total_s": int(row["TOTAL TIME"].removesuffix("ms")) / _MS_PER_S,
                    "max_s": int(row["MAX TIME"].removesuffix("ms")) / _MS_PER_S,
                    "active": row.get("STATUS") == "Active",
                }
            except (KeyError, ValueError):
                return None
            return values, text.evidence(i)
    return None


def _kernel_rows(
    kernel: list[_Lock],
    resumes: int | None,
    since: SinceCharge,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "wakeup_source": k.name,
            "time_s": round(k.seconds, 1),
            "count": k.count,
            "per_resume": round(k.count / resumes, 1) if resumes else None,
            "avg_ms": round(k.seconds * _MS_PER_S / k.count) if k.count else None,
            "ref": since.text.ref(k.index),
        }
        for k in kernel
    ]
    rows.sort(key=lambda row: -row["time_s"])
    return rows


def _partial_rows(
    ctx: Context,
    found: _Wakelocks,
    since: SinceCharge,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "uid": format_uid(p.uid or 0),
            "package": ctx.packages.name(p.uid or 0),
            "tag": p.name,
            "blamed_s": round(p.seconds, 1),
            "actual_s": (
                round(p.actual_ms / _MS_PER_S, 1) if p.actual_ms is not None else None
            ),
            "count": p.count,
            "max_s": round(p.max_ms / _MS_PER_S, 1) if p.max_ms is not None else None,
            "ref": since.text.ref(p.index),
        }
        for p in found.partial
    ]
    rows.sort(key=lambda row: -row["blamed_s"])
    return rows


def _uid_wake_rows(
    ctx: Context,
    found: _Wakelocks,
    since: SinceCharge,
    off_s: float | None,
) -> list[dict[str, Any]]:
    hours = off_s / _S_PER_H if off_s else None
    rows: list[dict[str, Any]] = []
    for uid, totals in found.uid_totals.items():
        actual = totals.get("actual partial", totals.get("blamed partial", 0.0))
        rows.append(
            {
                "uid": format_uid(uid),
                "package": ctx.packages.name(uid),
                "blamed_partial_s": round(totals.get("blamed partial", 0.0), 1),
                "actual_partial_s": round(actual, 1),
                "full_s": round(totals.get("full", 0.0), 1),
                "actual_partial_s_per_screen_off_h": (
                    round(actual / hours, 1) if hours else None
                ),
                "ref": since.text.ref(totals["index"]),
            },
        )
    rows.sort(key=lambda row: -row["actual_partial_s"])
    return rows


def _wakelock_metrics(
    ctx: Context,
    found: _Wakelocks,
    since: SinceCharge,
    resumes: int | None,
) -> dict[str, Any]:
    partial_s = _durations(since, "Total partial wakelock time")[0]
    off_s, off_up = _durations(since, _SCREEN_OFF)
    lockout = next((k for k in found.kernel if k.name == _LOCKOUT), None)
    top = max(found.kernel, key=lambda k: k.seconds, default=None)
    metrics: dict[str, Any] = {
        "kernel_wakelocks": len(found.kernel),
        "top_kernel_wakelock": top.name if top else None,
        "top_kernel_wakelock_s": round(top.seconds, 1) if top else None,
        "partial_wakelocks": len(found.partial),
        "partial_wakelock_total_s": partial_s,
        "full_wakelock_total_s": _durations(since, "Total full wakelock time")[0],
        "screen_off_uptime_s": off_up,
        "screen_off_awake_pct": pct(off_up, off_s),
        "partial_pct_of_screen_off_awake": pct(partial_s, off_up),
        "kernel_only_awake_screen_off_s": (
            round(max(off_up - partial_s, 0.0), 1)
            if off_up is not None and partial_s is not None
            else None
        ),
        "resumes": resumes,
        "screen_off_resumes": _screen_off_resumes(ctx),
        "suspend_lockout_screen_off_s": round(lockout.seconds, 1) if lockout else None,
        "suspend_lockout_screen_off_count": lockout.count if lockout else None,
    }
    if power := ctx.sources.get("power"):
        for _, m in power.find(_AUTOSUSPEND_RE):
            metrics.setdefault(_AUTOSUSPEND_METRICS[m["key"]], m["value"] == "true")
    return metrics


def _heavy_partial_finding(
    rows: list[dict[str, Any]],
    found: _Wakelocks,
    since: SinceCharge,
) -> Finding | None:
    heavy = [
        r
        for r in rows
        if (r["actual_partial_s_per_screen_off_h"] or 0) >= HEAVY_PARTIAL_S_PER_H
    ]
    if not heavy:
        return None
    names = ", ".join(
        f"{r['package']} ({r['uid']}, {fmt_duration(r['actual_partial_s'])})"
        for r in heavy[:5]
    )
    evidence = [
        Evidence(r["ref"], f"TOTAL wake {r['uid']}: {r['actual_partial_s']} s actual")
        for r in heavy[:5]
    ]
    heavy_uids = {r["uid"] for r in heavy}
    evidence += [
        since.text.evidence(p.index)
        for p in sorted(found.partial, key=lambda p: -p.seconds)
        if format_uid(p.uid or 0) in heavy_uids
    ][:3]
    return Finding(
        id="wakelocks.heavy_partial_wakelocks",
        title="Apps held partial wakelocks for long stretches with the screen off",
        symptom="battery",
        severity="medium",
        basis="measured",
        window="screen_off_on_battery",
        summary=(
            f"{len(heavy)} UID(s) held partial wakelocks for at least "
            f"{HEAVY_PARTIAL_S_PER_H // 60} min per screen-off hour: {names}. "
            "WorkSource attribution can move a wakelock from the system to the "
            "app that requested the work."
        ),
        metrics={
            "uids": len(heavy),
            "top_actual_partial_s": heavy[0]["actual_partial_s"],
        },
        evidence=evidence,
        recommendation=(
            "For an app, open Settings > Apps > (app) > App battery usage and "
            "choose Restricted or Optimized if it does not need to run in the "
            "background. For system UIDs (1000, 1073), look up the wakelock tag "
            "in the power dump (wake locks list) to find the app or feature "
            "behind it."
        ),
        followups=[
            (
                "List the UID's wakelock tags (per-UID 'Wake lock' lines) to see "
                "which component holds them."
            ),
            "Check whether the wakelocks line up with jobs or alarms of the app.",
        ],
    )


def _churn_finding(
    found: _Wakelocks,
    metrics: dict[str, Any],
    since: SinceCharge,
) -> Finding | None:
    off_resumes = metrics["screen_off_resumes"]
    resumes = off_resumes or metrics["resumes"]
    if not resumes or resumes < MIN_EVENTS:
        return None
    churn = [
        k
        for k in found.kernel
        if k.count >= CHURN_PER_RESUME * resumes and k.seconds >= CHURN_MIN_S
    ]
    if not churn:
        return None
    churn.sort(key=lambda k: -k.count)
    names = ", ".join(
        f"{k.name} ({k.count:,} times, {k.count / resumes:.0f} per resume, "
        f"{fmt_duration(k.seconds)})"
        for k in churn[:3]
    )
    against = (
        f"{resumes:,} screen-off resumes on battery"
        if off_resumes
        else f"{resumes:,} real resumes on battery (screen-off resumes unknown)"
    )
    return Finding(
        id="wakelocks.per_resume_churn",
        title="Kernel wakeup sources are re-armed many times on every resume",
        symptom="battery",
        severity="low",
        basis="measured",
        window="screen_off_on_battery",
        summary=(
            f"Kernel wakelock counts run with the screen off on battery. Against "
            f"{against}: {names}. Such sources fire repeatedly inside each wake "
            "and stretch it."
        ),
        metrics={"resumes": resumes, "sources": len(churn)},
        evidence=[since.text.evidence(k.index) for k in churn[:3]],
        recommendation=(
            "Find which driver or daemon owns the wakeup source (its name, the "
            "kernel log) and whether it reacts to every resume. Vendor drivers "
            "need an OS update; user-space event loops can be stopped by "
            "removing the app or setting that keeps them busy."
        ),
        followups=[
            (
                "Check whether the same source shows up in 'Abort: Pending Wakeup "
                "Sources' lines."
            ),
        ],
    )


def _previous_period_hold(ctx: Context, metrics: dict[str, Any]) -> bool:
    """Whether previous_cycle already reports the long since-boot lockout.

    That holds when its suspend_blocked finding fired, the boot predates the
    current charge period, and the current period's screen-off lockout is
    shorter than a long hold.
    """
    previous = ctx.results.get("previous_cycle")
    if previous is None or not any(
        f.id == "previous_cycle.suspend_blocked" for f in previous.findings
    ):
        return False
    boot, start = ctx.windows.boot_time, ctx.windows.since_charge_start
    current = metrics["suspend_lockout_screen_off_s"] or 0
    return bool(boot and start and boot < start and current < LOCKOUT_SINCE_BOOT_S)


def _lockout_findings(
    ctx: Context,
    metrics: dict[str, Any],
    found: _Wakelocks,
    since_boot: tuple[dict[str, Any], Evidence] | None,
    since: SinceCharge,
    result: Result,
) -> list[Finding]:
    findings = []
    screen_off = metrics["suspend_lockout_screen_off_s"]
    if screen_off is not None and screen_off >= LOCKOUT_SCREEN_OFF_S:
        lock = next(k for k in found.kernel if k.name == _LOCKOUT)
        findings.append(
            Finding(
                id="wakelocks.suspend_lockout_screen_off",
                title="Autosuspend was disabled with the screen off on battery",
                symptom="battery",
                severity="high",
                basis="measured",
                window="screen_off_on_battery",
                summary=(
                    f"{_LOCKOUT} was held {fmt_duration(screen_off)} with the screen "
                    "off on battery, so the SoC could not sleep. Power manager "
                    "takes it when autosuspend is off, usually because a display "
                    "(main, external, projected) is not off."
                ),
                metrics={"suspend_lockout_screen_off_s": screen_off},
                evidence=[since.text.evidence(lock.index)],
                recommendation=(
                    "Look for a display that stayed on: screen casting, Android "
                    "Auto or another projection, an always-on external display. "
                    "Disconnect it, then compare in the next charge cycle."
                ),
                followups=[
                    (
                        "Search the display dump (live/display.txt or the "
                        "bugreport's dumpsys display) for extra or virtual displays."
                    ),
                    (
                        "Match the lockout period with the battery history "
                        "(screen and plug events)."
                    ),
                ],
            ),
        )
    if not since_boot or since_boot[0]["max_s"] < LOCKOUT_SINCE_BOOT_S:
        return findings
    values, evidence = since_boot
    if _previous_period_hold(ctx, metrics):
        result.notes.append(
            f"The longest {_LOCKOUT} hold since boot "
            f"({fmt_duration(values['max_s'])}) lies before the current charge "
            "period; previous_cycle.suspend_blocked reports it.",
        )
        return findings
    findings.append(
        Finding(
            id="wakelocks.suspend_lockout_since_boot",
            title="Autosuspend was blocked for a long stretch since boot",
            symptom="battery",
            severity="low",
            basis="inferred",
            window="since_boot",
            summary=(
                f"Since boot {_LOCKOUT} was taken {values['count']} times for "
                f"{fmt_duration(values['total_s'])} in total, the longest single "
                f"hold {fmt_duration(values['max_s'])}. That is normal during long "
                "screen-on or projection sessions and while charging; if it "
                "happened with the screen off on battery, the phone could "
                "not sleep for that long."
            ),
            metrics={f"suspend_lockout_since_boot_{k}": v for k, v in values.items()},
            evidence=[evidence],
            recommendation=(
                "Match the long hold with the battery history (screen, plug "
                "and projection events) before acting on it."
            ),
            followups=[
                (
                    "Check the previous charge period's checkin 'kwl' row for "
                    f"{_LOCKOUT}."
                ),
            ],
        ),
    )
    return findings


@analyzer(
    "wakelocks",
    after=("windows", "wakeup_reasons", "standby_wake", "previous_cycle"),
)
def wakelocks(ctx: Context) -> Result:
    """Kernel wakeup sources, app partial wakelocks and SuspendLockout."""
    since = _since_charge(ctx)
    found = _parse_wakelocks(since)
    if not (found.kernel or found.partial or found.uid_totals):
        msg = "batterystats has no wakelock lines"
        raise SkipError(msg)
    result = Result("wakelocks", window="screen_off_on_battery")
    result.metrics = _wakelock_metrics(ctx, found, since, _resume_count(ctx, since))
    since_boot = _lockout_since_boot(ctx)
    if since_boot:
        for key, value in since_boot[0].items():
            result.metrics[f"suspend_lockout_since_boot_{key}"] = value
    for section, count in found.bad.items():
        result.notes.append(f"{count} lines in '{section}' could not be parsed.")
    uid_rows = _uid_wake_rows(ctx, found, since, _durations(since, _SCREEN_OFF)[0])
    per_resume = result.metrics["screen_off_resumes"] or result.metrics["resumes"]
    result.add_table("kernel_wakelocks", _kernel_rows(found.kernel, per_resume, since))
    result.add_table("partial_wakelocks", _partial_rows(ctx, found, since))
    result.add_table("uid_wake_totals", uid_rows)
    result.notes.append(
        "Kernel and partial wakelock totals are counted only with the screen off "
        "on battery (AOSP BatteryStatsImpl uses the screen-off time base); "
        "per_resume divides by screen-off resumes from the battery history when "
        "known. 'blamed' time is split among concurrent holders, 'actual' is "
        "wall time held. The awake time without any wakelock is reported by "
        "standby_wake.awake_share.",
    )
    if ctx.windows.on_battery_at_capture is False:
        result.notes.append(
            "Autosuspend flags from dumpsys power describe the phone on "
            "external power at capture.",
        )
    for finding in (
        _heavy_partial_finding(uid_rows, found, since),
        _churn_finding(found, result.metrics, since),
        *_lockout_findings(ctx, result.metrics, found, since_boot, since, result),
    ):
        if finding:
            result.findings.append(finding)
    return result


# Wi-Fi multicast locks and their effect on packet filtering.

_MC_UID_RE = re.compile(
    rf"^\s+WiFi Multicast Wakelock count = (?P<n>\d+) time = (?P<dur>{_DUR})",
)
_MC_ENABLED_RE = re.compile(r"^\s*mMulticast(?P<kind>Enabled|Disabled) (?P<n>\d+)\s*$")
_MULTICASTER_RE = re.compile(r"Multicaster\{(?P<tag>.*) uid=(?P<uid>\d+)\}")
_WLAN_WAKE_RE = re.compile(r"Wlan Wake Reasons: (?P<body>.*)$")
_COUNTER_RE = re.compile(r"(?P<key>[A-Za-z]\w*)[ =:](?P<value>\d+)")
_ISO_TS = r"(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)"
_APF_INSTALL_RE = re.compile(
    rf"^\s*{_ISO_TS} - INVOKE installPacketFilter\(.*?mcast: (?P<mcast>ALLOW|DROP),"
    r" doze: (?P<doze>TRUE|FALSE)",
)
_APF_CURRENT_RE = re.compile(
    r"^\s*ApfConfig: \{ mcast: (?P<mcast>ALLOW|DROP), doze: (?P<doze>TRUE|FALSE)",
)
_APF_EVIDENCE = 2  # example lines cited for multicast passed in Doze
_MULTICAST_TIME = "Total WiFi Multicast wakelock time"
_DTIM_RE = re.compile(rf"^\s*{_ISO_TS} - INVOKE setMaxDtimMultiplier\((?P<n>\d+)\)")


def _multicast_by_uid(since: SinceCharge) -> list[dict[str, Any]]:
    rows = []
    for i, line, uid, _apk in _uid_lines(since):
        if m := _MC_UID_RE.match(line):
            rows.append(
                {
                    "uid": uid,
                    "count": int(m["n"]),
                    "time_s": parse_duration_ms(m["dur"]) / _MS_PER_S,
                    "index": i,
                },
            )
    return rows


def _wifi_dump(ctx: Context, result: Result) -> list[Evidence]:
    """Read lock counters, locks held and firmware wake reasons from dumpsys wifi."""
    text = ctx.sources.get("wifi")
    if text is None:
        return []
    evidence: list[Evidence] = []
    held: list[dict[str, Any]] = []
    in_held = False
    for i, line in enumerate(text.lines):
        if m := _MC_ENABLED_RE.match(line):
            result.metrics[f"multicast_{m['kind'].lower()}_count"] = int(m["n"])
        elif line.strip() == "Multicast Locks held:":
            in_held = True
            evidence.append(text.evidence(i))
        elif in_held and (m := _MULTICASTER_RE.search(line)):
            uid = int(m["uid"])
            held.append(
                {
                    "tag": m["tag"],
                    "uid": format_uid(uid),
                    "package": ctx.packages.name(uid),
                    "ref": text.ref(i),
                },
            )
            evidence.append(text.evidence(i))
        elif m := _WLAN_WAKE_RE.search(line):
            in_held = False
            _wake_counters(m["body"], result)
            evidence.append(text.evidence(i))
        else:
            in_held = False
    if held or any(e.excerpt == "Multicast Locks held:" for e in evidence):
        result.metrics["locks_held_at_capture"] = len(held)
        result.tables["locks_held"] = held
    return evidence


def _wake_counters(body: str, result: Result) -> None:
    counters = {m["key"]: int(m["value"]) for m in _COUNTER_RE.finditer(body)}
    total = counters.get("totalRxDataWake")
    if not total:
        return
    multi = counters.get("rxMulticast", 0)
    broad = counters.get("rxBroadcast", 0)
    result.metrics.update(
        {
            "fw_rx_data_wakes": total,
            "fw_rx_multicast_wakes": multi,
            "fw_rx_broadcast_wakes": broad,
            "fw_multicast_broadcast_pct": pct(multi + broad, total),
        },
    )


def _apf_log(ctx: Context, result: Result) -> list[Evidence]:
    """Count packet-filter installs and DTIM changes in the network_stack log."""
    text = ctx.sources.get("network_stack")
    if text is None:
        return []
    configs: Counter[tuple[str, str]] = Counter()
    since_charge: Counter[tuple[str, str]] = Counter()
    dtim: Counter[int] = Counter()
    stamps: list[str] = []
    evidence: list[Evidence] = []
    start = ctx.windows.since_charge_start
    for i, line in enumerate(text.lines):
        if m := _APF_INSTALL_RE.match(line):
            key = (m["mcast"], m["doze"])
            configs[key] += 1
            stamps.append(m["ts"])
            if start and datetime.fromisoformat(m["ts"]) >= start:
                since_charge[key] += 1
            if key == ("ALLOW", "TRUE") and len(evidence) < _APF_EVIDENCE:
                evidence.append(text.evidence(i))
        elif m := _DTIM_RE.match(line):
            dtim[int(m["n"])] += 1
            stamps.append(m["ts"])
        elif (m := _APF_CURRENT_RE.match(line)) and "apf_current_mcast" not in (
            result.metrics
        ):
            result.metrics["apf_current_mcast"] = m["mcast"]
            result.metrics["apf_current_doze"] = m["doze"] == "TRUE"
    if not configs and not dtim:
        return []
    result.metrics.update(
        {
            "apf_installs": sum(configs.values()),
            "apf_mcast_allow_in_doze": configs["ALLOW", "TRUE"],
            "apf_mcast_drop_in_doze": configs["DROP", "TRUE"],
            "apf_mcast_allow_awake": configs["ALLOW", "FALSE"],
            "apf_mcast_drop_awake": configs["DROP", "FALSE"],
            "apf_mcast_allow_in_doze_since_charge": (
                since_charge["ALLOW", "TRUE"] if start else None
            ),
            "apf_log_first": min(stamps),
            "apf_log_last": max(stamps),
        },
    )
    result.tables["apf_configs"] = [
        {"mcast": k[0], "doze": k[1] == "TRUE", "installs": n}
        for k, n in configs.most_common()
    ]
    result.tables["dtim_multiplier"] = [
        {"multiplier": k, "count": n} for k, n in sorted(dtim.items())
    ]
    result.notes.append(
        "network_stack counts cover the IpClient log ring "
        f"({min(stamps)} to {max(stamps)}); older entries are gone, so they are "
        "lower bounds.",
    )
    return evidence


def _multicast_metrics(
    ctx: Context,
    since: SinceCharge | None,
    rows: list[dict[str, Any]],
    result: Result,
) -> None:
    if since is None:
        return
    total_s = _durations(since, _MULTICAST_TIME)[0]
    count = since.header("Total WiFi Multicast wakelock Count")
    battery_s = _durations(since, _ON_BATTERY)[0]
    result.metrics.update(
        {
            "multicast_total_s": total_s,
            "multicast_total_count": (
                int(count[0]) if count and count[0].isdigit() else None
            ),
            "multicast_pct_of_battery": pct(total_s, battery_s),
            "multicast_uids": len(rows),
            "on_battery_s": battery_s,
        },
    )
    rows.sort(key=lambda r: -r["time_s"])
    result.add_table(
        "multicast_by_uid",
        [
            {
                "uid": format_uid(r["uid"]),
                "package": ctx.packages.name(r["uid"]),
                "count": r["count"],
                "time_s": round(r["time_s"], 1),
                "pct_of_battery": pct(r["time_s"], battery_s),
                "ref": since.text.ref(r["index"]),
            }
            for r in rows
        ],
    )
    if rows:
        result.metrics["top_uid"] = format_uid(rows[0]["uid"])
        result.metrics["top_package"] = ctx.packages.name(rows[0]["uid"])
        result.metrics["top_uid_pct_of_battery"] = pct(rows[0]["time_s"], battery_s)


def _multicast_finding(
    result: Result,
    since: SinceCharge | None,
    extra_evidence: list[Evidence],
) -> Finding | None:
    metrics = result.metrics
    share = metrics.get("multicast_pct_of_battery")
    if since is None or share is None or share < MULTICAST_SHARE_PCT:
        return None
    rows = result.tables.get("multicast_by_uid", [])
    holders = "; ".join(
        f"{r['package']} ({r['uid']}) {fmt_duration(r['time_s'])} "
        f"({r['pct_of_battery']}%)"
        for r in rows[:3]
    )
    details = []
    if metrics.get("apf_mcast_allow_in_doze"):
        details.append(
            f"The network stack installed packet filters that pass multicast "
            f"while dozing {metrics['apf_mcast_allow_in_doze']} times "
            "('mcast: ALLOW, doze: TRUE').",
        )
    if metrics.get("fw_multicast_broadcast_pct") is not None:
        details.append(
            "Multicast and broadcast frames caused "
            f"{metrics['fw_multicast_broadcast_pct']}% of the Wi-Fi firmware's "
            "host wakes since the driver started.",
        )
    evidence = since.evidence(_MULTICAST_TIME)
    evidence += [Evidence(r["ref"], f"{r['uid']}: {r['time_s']} s") for r in rows[:3]]
    return Finding(
        id="wifi_multicast.lock_held",
        title=f"A Wi-Fi multicast lock was held {share:.0f}% of the time on battery",
        symptom="battery",
        severity="medium",
        basis="measured",
        window="on_battery",
        summary=(
            "Wi-Fi multicast locks were held "
            f"{fmt_duration(metrics['multicast_total_s'])} of "
            f"{fmt_duration(metrics['on_battery_s'])} on battery. Holders: {holders}. "
            "While any lock is held, the Wi-Fi chip passes LAN multicast (mDNS, "
            "SSDP) to the host and may wake the SoC for it, also in Doze. "
            + " ".join(details)
        ).strip(),
        metrics={
            k: metrics.get(k)
            for k in (
                "multicast_total_s",
                "multicast_pct_of_battery",
                "top_uid",
                "top_uid_pct_of_battery",
                "apf_mcast_allow_in_doze",
                "fw_multicast_broadcast_pct",
            )
        },
        evidence=evidence + extra_evidence[:4],
        recommendation=(
            "Find out why the holding app keeps a multicast lock in the "
            "background: device discovery, casting, phone-to-computer sync and "
            "smart-home apps do this. Turn off its LAN discovery feature, or "
            "set Settings > Apps > (app) > App battery usage to Restricted, then "
            "compare the 'Total WiFi Multicast wakelock time' after the next "
            "full charge. Filtering stays off until every holder releases its "
            "lock."
        ),
        followups=[
            (
                "Check 'Wlan Wake Reasons' in the Wi-Fi dump (live/wifi.txt or the "
                "bugreport's dumpsys wifi) for the multicast share of host wakes."
            ),
            (
                "Check the network_stack IpClient log for 'mcast: ALLOW, doze: TRUE' "
                "and setMaxDtimMultiplier(1) while the screen is off."
            ),
            (
                "adb_ro.py --save servicediscovery --workdir WORKDIR -- dumpsys "
                "servicediscovery, then grep the holding app's package in "
                "WORKDIR/live/servicediscovery.txt for its mDNS advertisers and "
                "browsers."
            ),
        ],
    )


@analyzer("wifi_multicast")
def wifi_multicast(ctx: Context) -> Result:
    """Wi-Fi multicast lock time per UID and the packet filter state."""
    since = load_since_charge(ctx)
    rows = _multicast_by_uid(since) if since else []
    has_header = bool(since and since.header(_MULTICAST_TIME))
    if not (rows or has_header or ctx.sources.has("wifi")):
        msg = "no multicast lines in batterystats and no Wi-Fi dump"
        raise SkipError(msg)
    result = Result("wifi_multicast", window="on_battery")
    _multicast_metrics(ctx, since, rows, result)
    evidence = _wifi_dump(ctx, result)
    evidence += _apf_log(ctx, result)
    if "fw_rx_data_wakes" in result.metrics:
        result.notes.append(
            "Wlan Wake Reasons count since the Wi-Fi driver started (since boot).",
        )
    result.notes.append(
        "Per-UID multicast time is that UID's share of the lock time; locks "
        "held by several apps at once overlap.",
    )
    if finding := _multicast_finding(result, since, evidence):
        result.findings.append(finding)
    return result


# Power model: "Estimated power use (mAh)" against the measured discharge.

_MAIN_COMPONENTS = ("screen", "cpu", "mobile_radio", "wifi", "wakelock")
# mAh of the power model are printed with up to 3 significant digits.
_MAH_DIGITS = 6


@dataclass
class _Component:
    """A power-model component on battery."""

    mah: float
    apps_mah: float
    duration_s: float | None
    index: int


def _power_state(label: str) -> str:
    """Return ``on battery`` or ``not on battery`` from a state label."""
    return label.split(",", 1)[0].strip()


def _components(model: PowerModel) -> dict[str, _Component]:
    """Return the model's components on battery.

    With power-state sub-blocks (Android 15+) a component is the sum of its
    ``(on battery, ...)`` lines, because the ``Global`` line also counts time
    on the charger (``PowerModel.on_battery_components``).
    """
    states = [
        comps
        for label, comps in model.state_components.items()
        if _power_state(label) == "on battery"
    ]
    found: dict[str, _Component] = {}
    for name, mah in model.on_battery_components().items():
        parts = [comps[name] for comps in states if name in comps]
        top = model.global_components.get(name)
        if parts:
            durations = [c.duration_s for c in parts if c.duration_s is not None]
            found[name] = _Component(
                mah,
                sum(c.apps_mah for c in parts),
                sum(durations) if durations else None,
                top.index if top else parts[0].index,
            )
        elif top:
            found[name] = _Component(mah, top.apps_mah, top.duration_s, top.index)
    return found


@dataclass
class _Uid:
    """A UID of the power model with its modelled mAh on battery."""

    power: UidPower
    total: float
    components: dict[str, float]

    @property
    def background_mah(self) -> float:
        """Model mAh outside the foreground: bg, fgs and cached, else non-screen.

        Process-state shares cover all power states; with per-state data they
        are scaled to the UID's share on battery.
        """
        u = self.power
        if not u.states:
            return self.total - self.components.get("screen", 0.0)
        background = sum(v for k, v in u.states.items() if k != "fg")
        return background * self.total / u.total if u.total else background


def _uids(model: PowerModel) -> list[_Uid]:
    """Return the UIDs with their on-battery mAh, largest first.

    A UID line covers all power states. Components that the Global model
    splits by power state take the UID's ``(on battery, ...)`` lines; the
    others keep the all-states value, as the Global model does (some vendors
    repeat one value in every state line).
    """
    split = {
        name
        for label, comps in model.state_components.items()
        if _power_state(label) in {"on battery", "not on battery"}
        for name in comps
    }
    found = []
    for u in model.uids.values():
        if not (split and u.power_states):
            found.append(_Uid(u, u.total, dict(u.components)))
            continue
        components = {k: v for k, v in u.components.items() if k not in split}
        for label, comps in u.power_states.items():
            if _power_state(label) != "on battery":
                continue
            for name, mah in comps.items():
                if name in split:
                    components[name] = components.get(name, 0.0) + mah
        found.append(_Uid(u, sum(components.values()), components))
    return sorted(found, key=lambda u: -u.total)


def _model_current_ma(
    components: dict[str, _Component],
    name: str,
) -> tuple[float, float] | None:
    """Return (mA, hours) the model charged for a component with a duration."""
    entry = components.get(name)
    if entry is None or not entry.duration_s:
        return None
    hours = entry.duration_s / _S_PER_H
    return round(entry.mah / hours, 3), hours


def _power_metrics(
    model: PowerModel,
    components: dict[str, _Component],
    uids: list[_Uid],
    since: SinceCharge,
) -> dict[str, Any]:
    counter = since.mah("Discharge")
    discharge = counter or model.actual_drain_min
    if components:
        modelled = sum(c.mah for c in components.values())
    else:
        modelled = model.computed_drain
    attributed = sum(u.total for u in uids)
    unmodelled = discharge - modelled if discharge and modelled is not None else None
    on_s, on_up_s = _durations(since, _ON_BATTERY)
    awake = _model_current_ma(components, "wakelock")
    idle = _model_current_ma(components, "idle")
    uid0 = next((u for u in uids if u.power.uid == 0), None)
    system = sum(u.total for u in uids if u.power.uid in _SYSTEM_UIDS)
    computed = model.computed_drain
    return {
        "capacity_mah": model.capacity,
        "computed_drain_mah": computed,
        "actual_drain_min_mah": model.actual_drain_min,
        "actual_drain_max_mah": model.actual_drain_max,
        "discharge_mah": counter,
        "computed_equals_discharge": (
            abs(computed - discharge) <= SAME_MAH
            if computed is not None and discharge
            else None
        ),
        "modelled_mah": round(modelled, 1) if modelled is not None else None,
        "modelled_pct": pct(modelled, discharge),
        "apps_mah": (
            round(sum(c.apps_mah for c in components.values()), 1)
            if components
            else None
        ),
        "attributed_mah": round(attributed, 1),
        "attributed_pct": pct(attributed, discharge),
        "uid_count": len(model.uids),
        "unmodelled_mah": round(unmodelled, 1) if unmodelled is not None else None,
        "unmodelled_pct": pct(unmodelled, discharge),
        "unmodelled_ma_per_awake_h": per_hour(unmodelled, on_up_s),
        "unmodelled_ma_per_battery_h": per_hour(unmodelled, on_s),
        "awake_idle_model_ma": awake[0] if awake else None,
        "awake_idle_model_s": round(awake[1] * _S_PER_H, 1) if awake else None,
        "idle_model_ma": idle[0] if idle else None,
        "uid0_wakelock_s": uid0.power.durations.get("wakelock") if uid0 else None,
        "uid0_wakelock_mah": uid0.components.get("wakelock") if uid0 else None,
        "system_uids_mah": round(system, 1),
        "system_uids_pct_of_attributed": pct(system, attributed),
    }


def _uid_power_rows(
    ctx: Context,
    uids: list[_Uid],
    metrics: dict[str, Any],
    since: SinceCharge,
) -> list[dict[str, Any]]:
    discharge = metrics["discharge_mah"] or metrics["actual_drain_min_mah"]
    rows = []
    for uid in uids:
        u, total, components = uid.power, uid.total, uid.components
        main = {c: components.get(c, 0.0) for c in _MAIN_COMPONENTS}
        rows.append(
            {
                "uid": format_uid(u.uid),
                "package": ctx.packages.name(u.uid),
                "total_mah": round(total, _MAH_DIGITS),
                "screen_mah": main["screen"],
                "cpu_mah": main["cpu"],
                "mobile_radio_mah": main["mobile_radio"],
                "wifi_mah": main["wifi"],
                "other_mah": round(total - sum(main.values()), 4),
                "fg_mah": u.states.get("fg"),
                "bg_mah": u.states.get("bg"),
                "fgs_mah": u.states.get("fgs"),
                "cached_mah": u.states.get("cached"),
                "pct_of_model": pct(total, metrics["modelled_mah"]),
                "pct_of_discharge": pct(total, discharge),
                "components": " ".join(f"{k}={v:g}" for k, v in components.items()),
                "ref": since.text.ref(u.index),
            },
        )
    return rows


def _unmodelled_finding(
    metrics: dict[str, Any],
    model: PowerModel,
    components: dict[str, _Component],
    since: SinceCharge,
) -> Finding | None:
    unmodelled = metrics["unmodelled_pct"]
    if unmodelled is None or unmodelled < UNMODELLED_PCT:
        return None
    discharge = metrics["discharge_mah"] or metrics["actual_drain_min_mah"]
    parts = [
        (
            f"The fuel gauge counted {discharge:.0f} mAh on battery, but the power "
            f"model's components add up to {metrics['modelled_mah']:.0f} mAh "
            f"({metrics['modelled_pct']}%) and the per-UID estimates to "
            f"{metrics['attributed_mah']:.0f} mAh. {metrics['unmodelled_mah']:.0f} mAh "
            f"({unmodelled}%) is in no component."
        ),
    ]
    if metrics["computed_equals_discharge"] and components:
        parts.append(
            f"'Computed drain' ({metrics['computed_drain_mah']:.0f}) equals the "
            "counter, so it is not a model sum here.",
        )
    awake = metrics["awake_idle_model_ma"]
    unpriced = awake is not None and awake < MODEL_AWAKE_FLOOR_MA
    evidence = since.evidence("Discharge")
    if model.capacity_index is not None:
        evidence.append(since.text.evidence(model.capacity_index))
    evidence += [
        since.text.evidence(c.index)
        for name, c in components.items()
        if name in {"wakelock", "idle"}
    ]
    return Finding(
        id="power_model.unmodelled_drain",
        title=f"The power model explains only {metrics['modelled_pct']}% of the drain",
        symptom="battery",
        severity="medium",
        basis="modelled",
        window="on_battery",
        summary=" ".join(parts),
        metrics={
            k: metrics[k]
            for k in (
                "discharge_mah",
                "modelled_mah",
                "attributed_mah",
                "unmodelled_mah",
                "unmodelled_pct",
                "unmodelled_ma_per_awake_h",
                "awake_idle_model_ma",
            )
        },
        evidence=evidence,
        recommendation=(
            "Rank fixes by measured numbers (screen-off mAh per hour, awake "
            "time, wakeup counts), not by Settings > Battery usage, which shows "
            "only the modelled part. Per-app mAh understate the cost of keeping "
            "the phone awake."
        ),
        followups=[
            (
                "Check power_profile for standby currents (cpu.suspend, cpu.idle, "
                "wifi.on) near 0 mA, which leave standby unpriced."
            ),
            (
                "Compare the unmodelled mAh per awake hour across charge periods: "
                "if it stays similar, the remainder follows awake time."
            ),
            (
                "Check for on-device energy metering (energy consumer stats, "
                "powerstats rails)."
            ),
        ],
        # power_profile.standby_unpriced states the 0 mA awake pricing.
        related=["power_profile.standby_unpriced"] if unpriced else [],
    )


def _system_finding(
    metrics: dict[str, Any],
    uids: list[_Uid],
    since: SinceCharge,
) -> Finding | None:
    share = metrics["system_uids_pct_of_attributed"]
    if share is None or share < SYSTEM_UID_PCT:
        return None
    system = [u for u in uids if u.power.uid in _SYSTEM_UIDS]
    cpu = sum(u.components.get("cpu", 0.0) for u in system)
    return Finding(
        id="power_model.system_uids_dominate",
        title="Kernel and system UIDs carry a large part of the modelled power",
        symptom="battery",
        severity="low",
        basis="modelled",
        window="on_battery",
        summary=(
            f"UID 0 (kernel) and UID 1000 (system) were charged "
            f"{metrics['system_uids_mah']:.0f} mAh, {share}% of all per-UID "
            f"estimates; {cpu:.0f} mAh of it is CPU. With the screen off this is "
            "usually work triggered by wakes (suspend and resume, network "
            "handling), so per-app rankings do not show the trigger (inferred)."
        ),
        metrics={
            "system_uids_mah": metrics["system_uids_mah"],
            "system_uids_pct_of_attributed": share,
            "system_uids_cpu_mah": round(cpu, 1),
        },
        evidence=[since.text.evidence(u.power.index) for u in system],
        recommendation=(
            "Look at what wakes the phone (wakeup reasons, network traffic, "
            "alarms) instead of at app rankings."
        ),
        followups=[
            (
                "Break UID 0 and 1000 CPU time down by process (per-UID 'Proc' "
                "lines) to see which daemons run on each wake."
            ),
        ],
    )


def _background_finding(
    ctx: Context,
    uids: list[_Uid],
    metrics: dict[str, Any],
    since: SinceCharge,
) -> Finding | None:
    discharge = metrics["discharge_mah"] or metrics["actual_drain_min_mah"]
    if not discharge:
        return None
    flagged = sorted(
        (
            (u.power, background, pct(background, discharge) or 0.0)
            for u in uids
            if u.power.uid % 100_000 >= _FIRST_APP_ID
            and (background := u.background_mah) * 100 / discharge >= APP_BACKGROUND_PCT
        ),
        key=lambda item: -item[1],
    )
    if not flagged:
        return None
    names = "; ".join(
        f"{ctx.packages.name(u.uid)} ({format_uid(u.uid)}) {bg:.1f} mAh, {share}%"
        for u, bg, share in flagged[:5]
    )
    return Finding(
        id="power_model.app_background_power",
        title="Apps were charged a noticeable share of the drain in the background",
        symptom="battery",
        severity="medium",
        basis="modelled",
        window="on_battery",
        summary=(
            f"Background model power (background, foreground-service and cached "
            f"states) of at least {APP_BACKGROUND_PCT}% of the discharge: {names}. "
            "These are model estimates (CPU, radio, Wi-Fi, GPS, sensors)."
        ),
        metrics={"apps": len(flagged)},
        evidence=[since.text.evidence(u.index) for u, *_ in flagged[:5]],
        recommendation=(
            "Open Settings > Apps > (app) > App battery usage and choose "
            "Restricted or Optimized if the app does not need to run in the "
            "background; check its sync and location settings."
        ),
        followups=[
            (
                "Compare the app's background CPU, wakelocks and network packets on "
                "battery."
            ),
        ],
    )


def _component_rows(
    model: PowerModel,
    components: dict[str, _Component],
    discharge: float | None,
    since: SinceCharge,
) -> list[dict[str, Any]]:
    """Rows of the components table; device rows for Android 11 and older."""
    if not components:
        return [
            {"component": name, "mah": mah, "ref": since.text.ref(i)}
            for name, (mah, i) in model.device_rows.items()
        ]
    return [
        {
            "component": name,
            "mah": round(c.mah, _MAH_DIGITS),
            "apps_mah": round(c.apps_mah, _MAH_DIGITS),
            "duration_s": c.duration_s,
            "pct_of_discharge": pct(c.mah, discharge),
            "ref": since.text.ref(c.index),
        }
        for name, c in sorted(components.items(), key=lambda kv: -kv[1].mah)
    ]


@analyzer("power_model")
def power_model(ctx: Context) -> Result:
    """Per-UID power estimates and the share of drain the model cannot see."""
    since = _since_charge(ctx)
    model = since.power
    components = _components(model) if model else {}
    if model is None or not (model.uids or components or model.device_rows):
        msg = "batterystats has no 'Estimated power use (mAh)' block"
        raise SkipError(msg)
    uids = _uids(model)
    result = Result("power_model", window="on_battery")
    m = result.metrics = _power_metrics(model, components, uids, since)
    if model.unparsed:
        result.notes.append(f"{model.unparsed} power-use lines could not be parsed.")
    discharge = m["discharge_mah"] or m["actual_drain_min_mah"]
    if m["discharge_mah"] is None and discharge is not None:
        result.notes.append(
            "No counter 'Discharge' line: shares use the lower bound of the "
            "level-based 'actual drain' (battery % x capacity) instead.",
        )
    result.tables["components"] = _component_rows(model, components, discharge, since)
    result.add_table("uids", _uid_power_rows(ctx, uids, m, since))
    if model.state_components:
        result.notes.append(
            "The model has per-state sub-blocks: components and UIDs are the sum "
            "of their '(on battery, ...)' lines, not the Global lines, which "
            "also count time on the charger.",
        )
    if m["computed_equals_discharge"] and components:
        result.notes.append(
            "'Computed drain' equals the counter discharge, so 'actual minus "
            "computed' is about 0 and says nothing about the model. The "
            "unmodelled share here is the discharge minus the sum of the "
            "components.",
        )
    result.notes.append(
        "Model mAh come from the OEM power profile (modelled); 'Discharge' is "
        "the fuel gauge counter (measured), in whole steps of the learned "
        "capacity, so it carries about one step of uncertainty.",
    )
    for finding in (
        _unmodelled_finding(m, model, components, since),
        _system_finding(m, uids, since),
        _background_finding(ctx, uids, m, since),
    ):
        if finding:
            result.findings.append(finding)
    return result


# Power profile: what the model can price, and on-device energy metering.

_PROFILE_LINE_RE = re.compile(r"^\s*(?P<key>[\w.:,-]+)=(?P<value>.+?)\s*$")
_PROFILE_SPEEDS_RE = re.compile(r"^cpu\.core_speeds\.(?:cluster|policy)(?P<n>\d+)$")
_PROFILE_POWER_RE = re.compile(
    r"^cpu\.(?:core_power|scaling_step_power)\.(?:cluster|policy)(?P<n>\d+)$",
)
_CPU_SCALING_RE = re.compile(r"^\s*CPU scaling:\s*(?P<body>.*)$")
_POLICY_RE = re.compile(r"policy(?P<n>\d+):(?P<freqs>(?:\s+\d+)+)")
_BRACKET_RE = re.compile(rf"(?P<cluster>\d+)/(?P<mhz>\d+)\((?P<ma>{_NUM})\)")
_FREQ_TIMES_RE = re.compile(
    r"^\s+Total (?P<off>screen-off )?cpu time per freq: (?P<values>[\d ]+?)\s*$",
)
_POWERSTATS_DATA_RE = re.compile(r"(?i)\b(?:channel|energy|rail|meter|consumer)")


def _parse_profile(text: Text) -> dict[str, tuple[float | list[float], int]]:
    profile: dict[str, tuple[float | list[float], int]] = {}
    for i, line in enumerate(text.lines):
        m = _PROFILE_LINE_RE.match(line)
        if not m:
            continue
        raw = m["value"]
        try:
            if raw.startswith("["):
                values = [parse_decimal(v) for v in raw.strip("[]").split(", ") if v]
                profile[m["key"]] = (values, i)
            else:
                profile[m["key"]] = (parse_decimal(raw), i)
        except ValueError:
            continue
    return profile


def _standby_items(
    profile: dict[str, tuple[float | list[float], int]],
) -> list[tuple[str, float, int]]:
    items = []
    for key, (value, i) in profile.items():
        standby = key in STANDBY_KEYS or key.startswith("drain:SLEEP")
        if standby and isinstance(value, float) and value < PROFILE_ZERO_MA:
            items.append((key, value, i))
    return items


def _cluster_rows(
    profile: dict[str, tuple[float | list[float], int]],
    policies: list[tuple[int, list[int]]],
) -> list[dict[str, Any]]:
    speeds = {
        int(m["n"]): value
        for key, (value, _) in profile.items()
        if (m := _PROFILE_SPEEDS_RE.match(key)) and isinstance(value, list)
    }
    rows = []
    for (cluster, steps), policy in zip(
        sorted(speeds.items()),
        policies + [(-1, [])] * len(speeds),
        strict=False,
    ):
        kernel = policy[1]
        rows.append(
            {
                "cluster": cluster,
                "profile_steps": len(steps),
                "profile_max_khz": max(steps, default=None),
                "kernel_policy": policy[0] if kernel else None,
                "kernel_steps": len(kernel) or None,
                "kernel_max_khz": max(kernel, default=None),
                "matches": bool(kernel) and len(steps) == len(kernel),
            },
        )
    return rows


def _brackets(
    text: Text, after: int
) -> tuple[list[tuple[int, int, float]], int | None]:
    """Parse "CPU power brackets" (cluster, MHz, mA) after the stats block."""
    lines = text.lines
    for i in range(after, len(lines)):
        if not lines[i].startswith("CPU power brackets"):
            continue
        found: list[tuple[int, int, float]] = []
        for j in range(i + 1, len(lines)):
            if not lines[j].strip() or lines[j][:1].strip():
                break
            found += [
                (int(m["cluster"]), int(m["mhz"]), parse_decimal(m["ma"]))
                for m in _BRACKET_RE.finditer(lines[j])
            ]
        return found, i
    return [], None


def _energy_consumers(text: Text, after: int) -> tuple[bool | None, int | None]:
    lines = text.lines
    for i in range(after, len(lines)):
        if lines[i].startswith("On-battery energy consumer stats"):
            following = next((x for x in lines[i + 1 : i + 4] if x.strip()), "")
            return "not supported" not in following.lower(), i
    return None, None


@dataclass
class _CpuEnergy:
    ms: list[int]
    off_ms: list[int]
    lines: int = 0
    mismatched: int = 0


def _cpu_times(since: SinceCharge, width: int) -> _CpuEnergy:
    energy = _CpuEnergy([0] * width, [0] * width)
    for _, line in since.lines():
        if not (m := _FREQ_TIMES_RE.match(line)):
            continue
        values = [int(v) for v in m["values"].split()]
        if len(values) != width:
            energy.mismatched += 1
            continue
        energy.lines += 1
        target = energy.off_ms if m["off"] else energy.ms
        for k, v in enumerate(values):
            target[k] += v
    return energy


def _cpu_energy_metrics(
    since: SinceCharge,
    brackets: list[tuple[int, int, float]],
    result: Result,
) -> list[tuple[int, int, float]]:
    """Recompute CPU core energy from per-frequency times and bracket currents."""
    energy = _cpu_times(since, len(brackets))
    if energy.mismatched:
        result.notes.append(
            f"{energy.mismatched} per-frequency CPU time lines did not have "
            f"{len(brackets)} values (one per power bracket) and were skipped.",
        )
    zero = [k for k, b in enumerate(brackets) if b[2] == 0]
    result.metrics["zero_priced_steps"] = len(zero)
    if not energy.lines:
        result.notes.append("No usable per-frequency CPU times; CPU energy skipped.")
        return [brackets[k] for k in zero]
    ma = [b[2] for b in brackets]

    def mah(ms: list[int]) -> float:
        return round(
            sum(t * c for t, c in zip(ms, ma, strict=True)) / _MS_MA_PER_MAH, 1
        )

    on_ms = [a - b for a, b in zip(energy.ms, energy.off_ms, strict=True)]
    result.metrics.update(
        {
            "cpu_min_on_battery": round(sum(energy.ms) / _MS_PER_MIN, 1),
            "cpu_min_screen_off": round(sum(energy.off_ms) / _MS_PER_MIN, 1),
            "cpu_core_mah_on_battery": mah(energy.ms),
            "cpu_core_mah_screen_off": mah(energy.off_ms),
            "cpu_core_mah_screen_on": mah(on_ms),
            "zero_priced_cpu_min": round(
                sum(energy.ms[k] for k in zero) / _MS_PER_MIN, 1
            ),
            "zero_priced_cpu_min_screen_off": round(
                sum(energy.off_ms[k] for k in zero) / _MS_PER_MIN, 1
            ),
        },
    )
    result.tables["cpu_brackets"] = [
        {
            "cluster": c,
            "mhz": mhz,
            "ma": cur,
            "cpu_min": round(energy.ms[k] / _MS_PER_MIN, 2),
            "cpu_min_screen_off": round(energy.off_ms[k] / _MS_PER_MIN, 2),
        }
        for k, (c, mhz, cur) in enumerate(brackets)
    ]
    return [brackets[k] for k in zero]


def _profile_metrics(
    ctx: Context,
    since: SinceCharge | None,
    result: Result,
) -> list[Evidence]:
    """Read the power profile constants; return evidence for zero-priced items."""
    text = ctx.sources.get("power_profile")
    if text is None:
        result.notes.append(
            "No power profile (dumpsys batterystats --power-profile is live-only); "
            "profile constants are unknown.",
        )
        return []
    profile = _parse_profile(text)
    for key in ("battery.capacity", "cpu.suspend", "cpu.idle", "cpu.active", "wifi.on"):
        if key in profile and isinstance(profile[key][0], float):
            result.metrics["profile_" + key.replace(".", "_")] = profile[key][0]
    zero = _standby_items(profile)
    result.metrics["profile_zero_standby_items"] = len(zero)
    result.tables["profile_zero_standby"] = [
        {"key": key, "ma": value, "ref": text.ref(i)} for key, value, i in zero
    ]
    policies: list[tuple[int, list[int]]] = []
    if since:
        for _, line in since.lines():
            if m := _CPU_SCALING_RE.match(line):
                policies = [
                    (int(p["n"]), [int(f) for f in p["freqs"].split()])
                    for p in _POLICY_RE.finditer(m["body"])
                ]
                break
    clusters = _cluster_rows(profile, policies)
    if clusters:
        result.tables["cpu_clusters"] = clusters
        result.metrics["profile_cluster_mismatches"] = sum(
            1 for c in clusters if not c["matches"]
        )
    return [text.evidence(i) for _, _, i in zero]


def _metering(
    ctx: Context,
    since: SinceCharge | None,
    result: Result,
) -> list[Evidence]:
    evidence = []
    if since:
        supported, index = _energy_consumers(since.text, since.end)
        result.metrics["energy_consumers_supported"] = supported
        if index is not None:
            evidence.append(since.text.evidence(index + 1))
    if powerstats := ctx.sources.get("powerstats"):
        has_data = any(_POWERSTATS_DATA_RE.search(x) for x in powerstats.lines)
        result.metrics["powerstats_has_data"] = has_data
        if not has_data:
            evidence.append(Evidence(powerstats.ref(0), "powerstats: no meter data"))
    return evidence


def _standby_finding(
    result: Result,
    components: dict[str, _Component],
    evidence: list[Evidence],
) -> Finding | None:
    rows = result.tables.get("profile_zero_standby", [])
    awake = _model_current_ma(components, "wakelock")
    model_blind = (
        awake is not None
        and awake[0] < MODEL_AWAKE_FLOOR_MA
        and awake[1] * _S_PER_H >= MIN_MODEL_AWAKE_S
    )
    if not rows and not model_blind:
        return None
    parts = []
    if rows:
        listed = ", ".join(f"{r['key']}={r['ma']:g}" for r in rows)
        parts.append(f"The power profile sets {listed} mA.")
    if awake is not None and model_blind:
        parts.append(
            f"The model charged {awake[0]} mA for "
            f"{fmt_duration(awake[1] * _S_PER_H)} "
            "of screen-off awake time ('wakelock' component).",
        )
    parts.append(
        "Real hardware draws milliamps suspended and tens of milliamps awake, so "
        "standby cost is missing from the model and from Settings > Battery usage.",
    )
    return Finding(
        id="power_profile.standby_unpriced",
        title="The power model prices sleep and awake-idle time at about 0 mA",
        symptom="battery",
        severity="medium",
        basis="modelled",
        window="on_battery",
        summary=" ".join(parts),
        metrics={
            "profile_zero_standby_items": len(rows),
            "awake_idle_model_ma": awake[0] if awake else None,
        },
        evidence=evidence[:6],
        recommendation=(
            "On this device do not rank battery fixes by per-app mAh; use "
            "measured counters (screen-off mAh per hour, awake time, wakeup "
            "counts). Only the vendor can correct the power profile."
        ),
        followups=[
            (
                "Compare the components of 'Estimated power use' with the "
                "counter 'Discharge' (power_model analyzer)."
            ),
            (
                "Run a controlled screen-off test and compare counter mAh per hour "
                "with the model."
            ),
        ],
    )


def _zero_step_finding(
    result: Result,
    zero: list[tuple[int, int, float]],
    evidence: list[Evidence],
) -> Finding | None:
    minutes = result.metrics.get("zero_priced_cpu_min") or 0
    mismatches = result.metrics.get("profile_cluster_mismatches") or 0
    if minutes < ZERO_STEP_MIN_MINUTES and not mismatches:
        return None
    parts = []
    if zero and minutes >= ZERO_STEP_MIN_MINUTES:
        steps = ", ".join(f"{c}/{mhz} MHz" for c, mhz, _ in zero)
        parts.append(
            f"{len(zero)} CPU frequency steps ({steps}) are priced at 0 mA; "
            f"{minutes} CPU-minutes on battery "
            f"({result.metrics['zero_priced_cpu_min_screen_off']} with the screen "
            "off) ran there and cost nothing in the model.",
        )
    if mismatches:
        parts.append(
            f"{mismatches} profile cluster table(s) list a different number of "
            "speeds than the kernel's frequency table, so prices are matched to "
            "the wrong frequencies.",
        )
    return Finding(
        id="power_profile.cpu_steps_unpriced",
        title="Some CPU frequencies are missing from the power profile",
        symptom="battery",
        severity="low",
        basis="modelled",
        window="on_battery",
        summary=" ".join(parts),
        metrics={
            "zero_priced_steps": len(zero),
            "zero_priced_cpu_min": minutes,
            "profile_cluster_mismatches": mismatches,
            "cpu_core_mah_on_battery": result.metrics.get("cpu_core_mah_on_battery"),
        },
        evidence=evidence[:4],
        recommendation=(
            "Treat the model's CPU mAh as a lower bound. Use CPU time (minutes) "
            "rather than CPU mAh to compare processes."
        ),
        followups=[
            (
                "Compare 'CPU scaling' (kernel steps) with cpu.core_speeds in the "
                "power profile."
            ),
        ],
    )


def _metering_finding(result: Result, evidence: list[Evidence]) -> Finding | None:
    consumers = result.metrics.get("energy_consumers_supported")
    rails = result.metrics.get("powerstats_has_data")
    if consumers is not False or rails is True:
        return None
    return Finding(
        id="power_profile.no_energy_metering",
        title="The phone has no on-device energy metering",
        symptom="info",
        severity="info",
        basis="measured",
        window="snapshot",
        summary=(
            "Batterystats reports energy consumer stats as not supported"
            + (" and the powerstats service has no rail data" if rails is False else "")
            + ". Drain the power model misses cannot be measured per subsystem on "
            "the phone; only the fuel gauge total is measured."
        ),
        metrics={"energy_consumers_supported": consumers, "powerstats_has_data": rails},
        evidence=evidence,
        recommendation=(
            "Use the fuel gauge counter (discharge mAh) and controlled A/B "
            "screen-off runs to measure the effect of a change."
        ),
        followups=[],
    )


@analyzer("power_profile")
def power_profile(ctx: Context) -> Result:
    """Audit what the power model can price and whether energy is metered."""
    since = load_since_charge(ctx)
    if since is None and not ctx.sources.has("power_profile"):
        msg = "no power profile and no batterystats since-charge block"
        raise SkipError(msg)
    result = Result("power_profile", window="on_battery")
    standby_evidence = _profile_metrics(ctx, since, result)
    cpu_evidence: list[Evidence] = []
    zero: list[tuple[int, int, float]] = []
    components: dict[str, _Component] = {}
    if since:
        brackets, index = _brackets(since.text, since.end)
        if brackets and index is not None:
            zero = _cpu_energy_metrics(since, brackets, result)
            cpu_evidence.append(since.text.evidence(index + 1))
            result.notes.append(
                "CPU core energy is recomputed as per-frequency CPU time x "
                "bracket current; the model's 'cpu' component also adds "
                "cluster and active base power, so compare ratios, not totals.",
            )
        components = _components(since.power) if since.power else {}
        if entry := components.get("wakelock"):
            standby_evidence.append(since.text.evidence(entry.index))
    for finding in (
        _standby_finding(result, components, standby_evidence),
        _zero_step_finding(result, zero, cpu_evidence),
        _metering_finding(result, _metering(ctx, since, result)),
    ):
        if finding:
            result.findings.append(finding)
    if not result.metrics:
        msg = "no power profile, CPU power brackets or metering information"
        raise SkipError(msg)
    return result


# Wakeup alarms and jobs per app.

_WAKEUP_ALARM_RE = re.compile(r"^\s+Wakeup alarm (?P<tag>.+): (?P<n>\d+) times\s*$")
_JOB_RE = re.compile(
    rf"^\s+Job (?P<comp>.+): (?P<dur>{_DUR})\s*realtime \((?P<n>\d+) times\)",
)
_ALARM_PKG_RE = re.compile(
    rf"^\s*(?P<uid>{_UID}):(?P<pkg>[\w.]+) \+(?P<run>{_COMPACT_DUR}) running, "
    r"(?P<wakeups>\d+) wakeups:",
)
_ALARM_TAG_STATS_RE = re.compile(
    r"^\s*\+(?P<run>\S+) (?P<wakes>\d+) wakes (?P<alarms>\d+) alarms, last",
)
_ALARM_TAG_RE = re.compile(r"^\s*(?P<tag>\*\w+\*:.*\S)\s*$")
_JOB_HISTORY_RE = re.compile(
    rf"^\s*(?P<ago>-{_COMPACT_DUR})\s+START(?:-P)?: #(?P<uid>{_UID})/-?\d+"
    r" (?P<comp>\S+)",
)


@dataclass
class _AlarmsJobs:
    alarms: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[dict[str, Any]] = field(default_factory=list)


def _batterystats_alarms_jobs(since: SinceCharge) -> _AlarmsJobs:
    found = _AlarmsJobs()
    for i, line, uid, apk in _uid_lines(since):
        if m := _WAKEUP_ALARM_RE.match(line):
            found.alarms.append(
                {
                    "uid": uid,
                    "apk": apk,
                    "tag": m["tag"],
                    "count": int(m["n"]),
                    "index": i,
                },
            )
        elif m := _JOB_RE.match(line):
            found.jobs.append(
                {
                    "uid": uid,
                    "component": m["comp"],
                    "runs": int(m["n"]),
                    "runtime_s": parse_duration_ms(m["dur"]) / _MS_PER_S,
                    "index": i,
                },
            )
    return found


def _alarm_stats(ctx: Context, result: Result) -> None:
    """Parse "Alarm Stats" of dumpsys alarm: wakeups per package since boot."""
    text = ctx.sources.get("alarm")
    if text is None:
        return
    start = next(
        (i for i, line in enumerate(text.lines) if line.strip() == "Alarm Stats:"),
        None,
    )
    if start is None:
        result.notes.append("dumpsys alarm has no 'Alarm Stats' section.")
        return
    indent = len(text.lines[start]) - len(text.lines[start].lstrip())
    packages: list[dict[str, Any]] = []
    pending_wakes: int | None = None
    for i in range(start + 1, len(text.lines)):
        line = text.lines[i]
        if not line.strip():
            continue
        if m := _ALARM_PKG_RE.match(line):
            packages.append(
                {
                    "uid": format_uid(parse_uid(m["uid"])),
                    "package": m["pkg"],
                    "wakeups": int(m["wakeups"]),
                    "running_s": parse_duration_ms(m["run"]) / _MS_PER_S,
                    "top_tag": None,
                    "top_tag_wakes": 0,
                    "ref": text.ref(i),
                },
            )
        elif len(line) - len(line.lstrip()) <= indent:
            break
        elif m := _ALARM_TAG_STATS_RE.match(line):
            pending_wakes = int(m["wakes"])
        elif (m := _ALARM_TAG_RE.match(line)) and packages and pending_wakes:
            if pending_wakes > packages[-1]["top_tag_wakes"]:
                packages[-1]["top_tag"] = m["tag"]
                packages[-1]["top_tag_wakes"] = pending_wakes
            pending_wakes = None
    _since_boot_alarm_metrics(ctx, packages, result)


def _since_boot_alarm_metrics(
    ctx: Context,
    packages: list[dict[str, Any]],
    result: Result,
) -> None:
    w = ctx.windows
    since_boot_s = (
        (w.dump_time - w.boot_time).total_seconds()
        if w.dump_time and w.boot_time
        else None
    )
    total = sum(p["wakeups"] for p in packages)
    result.metrics["alarm_wakeups_since_boot"] = total
    result.metrics["alarm_packages_since_boot"] = len(packages)
    result.metrics["since_boot_h"] = (
        round(since_boot_s / _S_PER_H, 2) if since_boot_s else None
    )
    result.metrics["alarm_wakeups_per_h_since_boot"] = _per_h(total, since_boot_s)
    for p in packages:
        p["running_s"] = round(p["running_s"], 1)
        p["wakeups_per_h"] = _per_h(p["wakeups"], since_boot_s)
    packages.sort(key=lambda p: -p["wakeups"])
    result.add_table("alarm_stats_since_boot", packages)


def _job_history(ctx: Context, result: Result) -> None:
    """Count job starts per UID in the jobscheduler's recent history ring."""
    text = ctx.sources.get("jobscheduler")
    if text is None:
        return
    starts: Counter[int] = Counter()
    oldest_ms = 0
    for _, m in text.find(_JOB_HISTORY_RE):
        starts[parse_uid(m["uid"])] += 1
        oldest_ms = max(oldest_ms, -parse_duration_ms(m["ago"]))
    if not starts:
        return
    result.metrics["job_history_starts"] = sum(starts.values())
    result.metrics["job_history_span_s"] = round(oldest_ms / _MS_PER_S, 1)
    result.add_table(
        "job_history_starts",
        [
            {"uid": format_uid(uid), "package": ctx.packages.name(uid), "starts": n}
            for uid, n in starts.most_common()
        ],
    )
    result.notes.append(
        f"jobscheduler 'Job history' covers only the last "
        f"{fmt_duration(oldest_ms / _MS_PER_S)} before capture (a ring buffer); its "
        "counts are lower bounds and may describe the phone on the charger.",
    )


def _battery_alarm_tables(
    ctx: Context,
    found: _AlarmsJobs,
    since: SinceCharge,
    result: Result,
) -> None:
    on_s = _durations(since, _ON_BATTERY)[0]
    off_s = _durations(since, _SCREEN_OFF)[0]
    alarm_rows = [
        {
            "uid": format_uid(a["uid"]),
            "package": a["apk"] or ctx.packages.name(a["uid"]),
            "tag": a["tag"],
            "count": a["count"],
            "per_screen_off_h": _per_h(a["count"], off_s),
            "ref": since.text.ref(a["index"]),
        }
        for a in sorted(found.alarms, key=lambda a: -a["count"])
        if a["count"]
    ]
    result.add_table("wakeup_alarms", alarm_rows)
    per_uid: dict[int, list[float]] = defaultdict(lambda: [0, 0.0])
    for job in found.jobs:
        per_uid[job["uid"]][0] += job["runs"]
        per_uid[job["uid"]][1] += job["runtime_s"]
    job_rows = [
        {
            "uid": format_uid(uid),
            "package": ctx.packages.name(uid),
            "runs": int(runs),
            "runtime_s": round(runtime, 1),
            "runtime_s_per_h": _per_h(runtime, on_s),
        }
        for uid, (runs, runtime) in sorted(per_uid.items(), key=lambda kv: -kv[1][0])
    ]
    result.add_table("jobs_by_uid", job_rows)
    alarms = sum(a["count"] for a in found.alarms)
    runs = sum(j["runs"] for j in found.jobs)
    result.metrics.update(
        {
            "wakeup_alarms_screen_off": alarms,
            "wakeup_alarms_per_screen_off_h": _per_h(alarms, off_s),
            "wakeup_alarm_uids": len({a["uid"] for a in found.alarms if a["count"]}),
            "job_runs_on_battery": runs,
            "job_runtime_s_on_battery": round(
                sum(j["runtime_s"] for j in found.jobs), 1
            ),
            "job_uids": len(per_uid),
            "on_battery_h": round(on_s / _S_PER_H, 2) if on_s else None,
            "screen_off_h": round(off_s / _S_PER_H, 2) if off_s else None,
        },
    )


def _resume_shares(ctx: Context, since: SinceCharge, result: Result) -> None:
    """Compare wakeup alarms with screen-off resumes and jobs with all resumes.

    Wakeup alarm counters run only with the screen off on battery, job
    counters all the time on battery (AOSP BatteryStatsImpl time bases). Their
    combined share divides both by the real resumes on battery.
    """
    m = result.metrics
    resumes = _resume_count(ctx, since)
    off_resumes = _screen_off_resumes(ctx)
    m["resumes_on_battery"] = resumes
    m["resumes_screen_off"] = off_resumes
    keys = (
        "alarms_pct_of_screen_off_resumes",
        "jobs_pct_of_resumes",
        "alarms_jobs_pct_of_resumes",
    )
    if not resumes:
        m |= dict.fromkeys(keys)
        return
    alarms = 100 * m["wakeup_alarms_screen_off"] / (off_resumes or resumes)
    jobs = 100 * m["job_runs_on_battery"] / resumes
    both = 100 * (m["wakeup_alarms_screen_off"] + m["job_runs_on_battery"]) / resumes
    m |= dict(zip(keys, (round(x, 1) for x in (alarms, jobs, both)), strict=True))


def _share_sentence(m: dict[str, Any]) -> str:
    """Return alarms and jobs against real resumes, or "" if too few resumes."""
    share = m.get("alarms_jobs_pct_of_resumes")
    resumes = m.get("resumes_on_battery")
    if share is None or not resumes or resumes < MIN_EVENTS:
        return ""
    verdict = (
        "not every job wakes the phone, so this is an upper bound"
        if share >= ALARM_JOB_SHARE_PCT
        else "they are not what keeps waking the phone"
    )
    return (
        f"{m['wakeup_alarms_screen_off']} wakeup alarms (counted with the screen "
        f"off) and {m['job_runs_on_battery']} job runs on battery equal {share}% "
        f"of the {resumes:,} real resumes on battery; {verdict}."
    )


def _alarm_rate_finding(result: Result) -> Finding | None:
    rows = [
        r
        for r in result.tables.get("wakeup_alarms", [])
        if (r["per_screen_off_h"] or 0) > ALARMS_PER_H
    ]
    if not rows:
        return None
    share = result.metrics.get("alarms_jobs_pct_of_resumes")
    big = share is not None and share >= ALARM_JOB_SHARE_PCT
    names = "; ".join(
        f"{r['package']} ({r['uid']}) '{r['tag']}' {r['count']} times "
        f"({r['per_screen_off_h']}/h)"
        for r in rows[:5]
    )
    # This finding also carries the share of resumes (_share_finding otherwise).
    together = _share_sentence(result.metrics)
    return Finding(
        id="alarms_jobs.frequent_wakeup_alarms",
        title="An app sets wakeup alarms more than once per 10 minutes",
        symptom="battery",
        severity="medium" if big else "low",
        basis="measured",
        window="screen_off_on_battery",
        summary=(
            f"Wakeup alarms above {ALARMS_PER_H} per screen-off hour on battery: "
            f"{names}. {together}"
        ).strip(),
        metrics={"alarm_tags": len(rows), "top_per_h": rows[0]["per_screen_off_h"]}
        | ({"alarms_jobs_pct_of_resumes": share} if together else {}),
        evidence=[
            Evidence(r["ref"], f"{r['uid']} {r['tag']}: {r['count']} times")
            for r in rows[:5]
        ],
        recommendation=(
            "Check the app's sync, refresh and notification-polling intervals; "
            "for widget updates (APPWIDGET_UPDATE), remove or reconfigure "
            "widgets that refresh often. Settings > Apps > (app) > App battery "
            "usage > Restricted defers most alarms in the background."
        ),
        followups=[
            "Compare with the since-boot 'Alarm Stats' table (alarm_stats_since_boot).",
            (
                "Check whether the app is exempt from battery optimisation "
                "(the deviceidle_whitelist dump)."
            ),
        ],
    )


def _share_finding(result: Result) -> Finding | None:
    m = result.metrics
    body = _share_sentence(m)
    if not body:
        return None
    share = m["alarms_jobs_pct_of_resumes"]
    keys = (
        "wakeup_alarms_screen_off",
        "job_runs_on_battery",
        "resumes_on_battery",
        "resumes_screen_off",
        "alarms_pct_of_screen_off_resumes",
        "jobs_pct_of_resumes",
        "alarms_jobs_pct_of_resumes",
    )
    evidence = [
        Evidence(r["ref"], f"{r['uid']} {r['tag']}: {r['count']} times")
        for r in result.tables.get("wakeup_alarms", [])[:3]
    ]
    if share >= ALARM_JOB_SHARE_PCT:
        return Finding(
            id="alarms_jobs.drive_wakeups",
            title="Wakeup alarms and jobs may drive a large share of wakeups",
            symptom="battery",
            severity="medium",
            basis="inferred",
            window="on_battery",
            summary=body,
            metrics={k: m.get(k) for k in keys},
            evidence=evidence,
            recommendation=(
                "Restrict the apps with the most wakeup alarms and jobs (Settings > "
                "Apps > (app) > App battery usage), starting from the tables."
            ),
            followups=[
                "Match alarm and job times with wake events in the battery history."
            ],
        )
    return Finding(
        id="alarms_jobs.not_the_driver",
        title="Wakeup alarms and jobs are a small share of wakeups",
        symptom="battery",
        severity="info",
        basis="inferred",
        window="on_battery",
        summary=body,
        metrics={k: m.get(k) for k in keys},
        evidence=evidence,
        recommendation=(
            "Look for the wake source in wakeup reasons and network traffic."
        ),
        followups=[
            (
                "Apps that keep a socket open can still be woken by incoming packets "
                "in Doze; low alarm and job counts do not clear them."
            ),
        ],
    )


def _heavy_jobs_finding(result: Result) -> Finding | None:
    rows = [
        r
        for r in result.tables.get("jobs_by_uid", [])
        if (r["runtime_s_per_h"] or 0) >= JOB_S_PER_H
    ]
    if not rows:
        return None
    names = "; ".join(
        f"{r['package']} ({r['uid']}) {r['runs']} runs, {fmt_duration(r['runtime_s'])}"
        for r in rows[:5]
    )
    return Finding(
        id="alarms_jobs.heavy_jobs",
        title="Background jobs ran for long on battery",
        symptom="battery",
        severity="low",
        basis="measured",
        window="on_battery",
        summary=(
            f"Job run time of at least {JOB_S_PER_H // 60} min per battery "
            f"hour: {names}."
        ),
        metrics={"uids": len(rows)},
        recommendation=(
            "Check the app's sync and backup settings; Settings > Apps > (app) > "
            "App battery usage > Restricted defers its jobs."
        ),
        followups=[
            "Look at the job components in batterystats 'Job' lines of the UID."
        ],
    )


@analyzer("alarms_jobs", after=("windows", "wakeup_reasons", "standby_wake"))
def alarms_jobs(ctx: Context) -> Result:
    """Wakeup alarms and jobs per app, compared with real resumes."""
    since = load_since_charge(ctx)
    if since is None and not (
        ctx.sources.has("alarm") or ctx.sources.has("jobscheduler")
    ):
        msg = "no batterystats, alarm or jobscheduler dump"
        raise SkipError(msg)
    result = Result("alarms_jobs", window="on_battery")
    if since:
        _battery_alarm_tables(ctx, _batterystats_alarms_jobs(since), since, result)
        _resume_shares(ctx, since, result)
    _alarm_stats(ctx, result)
    _job_history(ctx, result)
    result.notes.append(
        "batterystats counts wakeup alarms only with the screen off on battery "
        "and jobs all the time on battery since the last charge (AOSP "
        "BatteryStatsImpl time bases), so alarm rates are per screen-off hour "
        "and are compared with screen-off resumes. dumpsys alarm 'Alarm Stats' "
        "covers time since boot. They are not mixed.",
    )
    # One finding states the share of resumes: the alarm-rate one if it fires.
    rate = _alarm_rate_finding(result)
    for finding in (
        rate,
        None if rate else _share_finding(result),
        _heavy_jobs_finding(result),
    ):
        if finding:
            result.findings.append(finding)
    return result
