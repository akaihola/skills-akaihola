"""Combine the other analyzers into one drain budget and a bottom line.

These analyzers run last and read only ``ctx.results`` (plus ``ctx.windows``
and, for the coverage list, whether a few key inputs exist).

``drain_budget`` puts the measured discharge, the power model's share of it,
the screen-off awake share, the wake triggers and the effect of battery wear
in one place. ``bottom_line`` picks the strongest battery and slowness
findings for the top of the report and lists what the data could not show.

Causes are presented as layers, never as a sum. A packet sender is a trigger,
an aborted suspend multiplies the cost of each wake, and system CPU is a
consequence of the wakes. Per-cause mAh figures for these layers overlap: in
the diagnosis this skill was distilled from, such claims added up to more than
400 mAh against 282 mAh of measured screen-off drain. The budget therefore
gives shares of resumes with their denominators and no per-cause mAh.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from .catalog import LIVE_COMMANDS
from .common import fmt_duration, parse_decimal, pct, per_hour
from .model import (
    REGISTRY,
    SEVERITY_RANK,
    Context,
    Evidence,
    Finding,
    Result,
    SkipError,
    Symptom,
    analyzer,
)
from .readonly import check_adhoc

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# General knowledge, not a measurement on any phone analysed here: a phone
# that suspends properly with the screen off typically draws about 10-20 mA.
# Every text that quotes it must say so.
HEALTHY_STANDBY_MAH_PER_H = (10.0, 20.0)
REFERENCE_LABEL = "general knowledge, not measured on this phone"

# The bottom line lists at most this many items per symptom so that the top of
# the report stays readable for a phone owner.
MAX_ITEMS = 5
# With fewer medium or high items than this, low-severity items fill the list.
MIN_STRONG_ITEMS = 3
# The first sentence of a finding is cut at a word boundary beyond this length.
MAX_SENTENCE_CHARS = 240
# A power model that leaves more than this share of the drain in no component
# cannot explain the drain (research catalogue flag: about 30 %).
UNMODELLED_FLAG_PCT = 30.0
# Rows kept per source in the wake-chain table (top wake reasons, steady UIDs,
# busy system processes); the whole table stays far below its row cap.
TOP_PER_SOURCE = 3
# Wake reasons below this share of resumes are left out of the wake chain.
MIN_REASON_SHARE_PCT = 1.0
# Default length of a screen-off test when gauge_quantization gives none: the
# gauge moves in whole percent steps, so shorter tests cannot resolve a change.
DEFAULT_TEST_H = 2.0
# Skipped or failed analyzers listed by name in the coverage finding.
MAX_LISTED_GAPS = 12
SECONDS_PER_MINUTE = 60
# Per-hour drain rates need at least this much time: over a few minutes one
# gauge step of 20-50 mAh becomes hundreds of mAh/h.
MIN_RATE_WINDOW_S = 10 * SECONDS_PER_MINUTE

BASIS_RANK = {"measured": 0, "modelled": 1, "inferred": 2}
STRONG_SEVERITIES = frozenset({"high", "medium"})
# Within a theme, a finding about the battery period beats one about another
# window with the same severity and basis.
WINDOW_RANK = {
    "screen_off_on_battery": 0,
    "on_battery": 0,
    "since_charge": 0,
    "last_24h": 1,
    "daily": 1,
    "since_boot": 2,
    "log_coverage": 2,
    "snapshot": 2,
}
WINDOW_LABELS = {
    "since_charge": "since the last full charge",
    "on_battery": "on battery since the last full charge",
    "screen_off_on_battery": "screen off on battery",
    "since_boot": "since boot",
    "last_24h": "last 24 h",
    "daily": "daily history",
    "log_coverage": "log sample",
    "snapshot": "at capture",
}

# One mechanism is often reported by several analyzers in different windows.
# The bottom line shows the strongest finding per theme so that one mechanism
# does not fill the list. An entry is an analyzer name or, when it contains a
# dot, a finding-id prefix that overrides the analyzer's theme. Tuple order is
# the preference within the theme. Findings that another finding lists in its
# ``related`` ids are folded into that finding first (see :func:`owner_map`).
THEMES: dict[str, tuple[str, ...]] = {
    "standby drain": (
        "discharge_accounting",
        "gauge_quantization",
        "daily_steps",
        "battery_saver_drain",
    ),
    # standby_wake.awake_share owns the resume rate and the top wake reason.
    "wakeups": (
        "standby_wake",
        "wakeup_reasons",
        "wake_periodicity",
        "qcom_wow",
        "wifi_multicast",
        "vpn",
        "network_traffic",
        "alarms_jobs",
        "wakelocks",
    ),
    # wakeup_reasons.suspend_aborts owns the abort counts. A suspend lock held
    # for hours (previous_cycle.suspend_blocked) also kept the phone from
    # suspending; the suspend service's CPU is the cost of the attempts.
    "suspend failures": (
        "wakeup_reasons.suspend_aborts",
        "kernel_suspend",
        "suspend_stats",
        "previous_cycle.suspend_blocked",
        "wakelocks.suspend_lockout",
        "system_process_cpu_churn.android-system-suspend-service",
    ),
    "previous charge period": (
        "previous_cycle.heavier_period",
        "previous_cycle.mobile_radio_busy",
        "previous_cycle",
    ),
    "battery wear": (
        "battery_capacity",
        "low_battery_shutdowns",
        "daily_steps.low_level_collapse",
        "qcom_charging",
    ),
    "radio": (
        "cellular_radio",
        "ims_handover",
        "wifi_roaming",
        "background_scanning_sensors_location",
    ),
    "power model": ("power_model", "power_profile"),
    "apps": (
        "app_background_activity",
        "third_party_apps",
        "battery_proc_cpu",
        "screen_off_cpu_by_uid",
        "uid_package_map",
        "exit_info_audit.excessive_cpu_kills",
    ),
    # system_process_cpu_churn owns busy system daemons; the since-boot and
    # cpuinfo views list only the daemons it did not report.
    "background CPU": (
        "system_process_cpu_churn",
        "process_cpu_since_boot",
        "cpuinfo_window",
        "top_samples",
        "am_cpu_intervals",
        "thread_cpu",
        "logcat_volume",
    ),
    "memory": (
        "exit_info_audit",
        "kills_vs_screen_events",
        "lmkd_kills",
        "zone_watermarks_offline",
        "am_memory_config",
        "memory_snapshot",
        "process_churn",
        "psi_pressure",
    ),
    # vmstat_reclaim_io.page_cache_thrashing owns the flash reads since boot.
    "page cache and storage": (
        "vmstat_reclaim_io",
        "storage_io_per_uid",
        "cpuinfo_window.major-fault-thrash",
        "dexopt_status",
    ),
    "frame drawing": ("frame_jank", "app_launch_times"),
    "settings": ("battery_saver_state", "settings_audit"),
    "heat": ("thermal_status",),
    "crashes": ("crash_anr_audit",),
    "build": ("build_identity",),
}
# Order of themes when their best findings tie on severity and basis.
THEME_PRIORITY = {
    "battery": (
        "standby drain",
        "wakeups",
        "suspend failures",
        "previous charge period",
        "battery wear",
        "radio",
        "power model",
        "apps",
        "background CPU",
        "settings",
        "heat",
        "memory",
        "page cache and storage",
        "crashes",
        "frame drawing",
        "build",
    ),
    "slowness": (
        "memory",
        "frame drawing",
        "page cache and storage",
        "settings",
        "background CPU",
        "apps",
        "heat",
        "crashes",
        "build",
        "suspend failures",
        "wakeups",
    ),
}

_ANALYZER_THEME = {
    entry: (theme, i)
    for theme, entries in THEMES.items()
    for i, entry in enumerate(entries)
    if "." not in entry
}
_PREFIX_THEME = sorted(
    (
        (entry, theme, i)
        for theme, entries in THEMES.items()
        for i, entry in enumerate(entries)
        if "." in entry
    ),
    key=lambda item: -len(item[0]),
)

# Inputs whose absence leaves a gap no other source fills, with what is lost.
KEY_INPUTS = {
    "power_profile": (
        "the power profile (mA per component), so the model's blind spots are "
        "inferred from its output instead of read from the profile"
    ),
    "clock": (
        "the phone's clock and UTC offset at capture, so UTC log times are "
        "aligned by estimate"
    ),
    "dmesg": (
        "the kernel log, so there is no per-packet Wi-Fi wake attribution and "
        "no suspend-abort detail"
    ),
    "packages_uid": "the full UID-to-package list, so some apps show as UIDs",
    "logcat_events": (
        "the event log, so process starts and kills around unlock and plug-in "
        "are not visible"
    ),
    "start_info": "app start records, so launch times come only from the log",
    "cpufreq": "CPU frequency limits, so thermal or saver CPU caps are unchecked",
}

COLLECT_COMMANDS = {c.key: c.shell for c in LIVE_COMMANDS}

# Analyzers whose absence matters most, listed first among the gaps.
KEY_ANALYZERS = (
    "discharge_accounting",
    "standby_wake",
    "wakeup_reasons",
    "power_model",
    "battery_capacity",
    "exit_info_audit",
    "frame_jank",
    "kernel_suspend",
    "qcom_wow",
)

# Interrupt-name fragments and what they usually stand for. Names are
# SoC-specific, so a hint is a guess from the name, labelled as such.
_IRQ_HINTS = (
    (re.compile(r"wlan|wifi|wcnss|icnss", re.IGNORECASE), "Wi-Fi"),
    (re.compile(r"modem|ipa|rmnet|qmi|mpss", re.IGNORECASE), "mobile data"),
    (re.compile(r"alarm|rtc", re.IGNORECASE), "an alarm timer"),
    (re.compile(r"pon|kpdpwr|gpio.?key", re.IGNORECASE), "a button"),
    (re.compile(r"typec|usb|charger|pmic", re.IGNORECASE), "the charger or USB"),
    (re.compile(r"\bbt\b|bluetooth|hs_uart", re.IGNORECASE), "Bluetooth"),
)
# Readable names for the sender roles of the Wi-Fi wake attribution.
SENDER_ROLES = {
    "lan_peer": "a device on the local network",
    "gateway": "the router",
    "unknown": "an unidentified sender",
}
_SENTENCE_RE = re.compile(r"^(.+?[.!?])(?=\s+[A-Z0-9'(\"])", re.DOTALL)

OWN_ANALYZERS = frozenset({"drain_budget", "bottom_line"})

BUDGET_INPUTS = (
    "windows",
    "battery_history",
    "discharge_accounting",
    "power_model",
    "standby_wake",
    "wakeup_reasons",
    "wake_periodicity",
    "wifi_multicast",
    "qcom_wow",
    "vpn",
    "network_traffic",
    "alarms_jobs",
    "kernel_suspend",
    "wakelocks",
    "system_process_cpu_churn",
    "screen_off_cpu_by_uid",
    "battery_capacity",
    "gauge_quantization",
    "previous_cycle",
    "daily_steps",
)

Value = float | int | str | bool | list | dict | None


# --------------------------------------------------------------------------
# Ranking helpers, also used by report.py
# --------------------------------------------------------------------------


def theme_of(finding_id: str) -> tuple[str, int]:
    """Return ``(theme, preference)`` for a finding id; unknown ids get their own."""
    for prefix, theme, pref in _PREFIX_THEME:
        if finding_id.startswith(prefix):
            return theme, pref
    name = finding_id.split(".", 1)[0]
    return _ANALYZER_THEME.get(name, (name, 0))


def theme_priority(symptom: str, theme: str) -> int:
    """Return the position of ``theme`` for ``symptom``; unlisted themes go last."""
    order = THEME_PRIORITY.get(symptom, THEME_PRIORITY["battery"])
    return order.index(theme) if theme in order else len(order)


def rank_key(
    finding_id: str,
    severity: str,
    basis: str,
    symptom: str = "battery",
) -> tuple[int, int, int, int, str]:
    """Sort key: severity, then basis (measured first), then theme order."""
    theme, pref = theme_of(finding_id)
    return (
        SEVERITY_RANK.get(severity, len(SEVERITY_RANK)),
        BASIS_RANK.get(basis, len(BASIS_RANK)),
        theme_priority(symptom, theme),
        pref,
        finding_id,
    )


def strength(severity: str, basis: str, window: str) -> tuple[int, int, int]:
    """Sort key of a finding's weight, independent of theme: lower is stronger."""
    return (
        SEVERITY_RANK.get(severity, len(SEVERITY_RANK)),
        BASIS_RANK.get(basis, len(BASIS_RANK)),
        WINDOW_RANK.get(window, len(WINDOW_RANK)),
    )


def owner_map(
    findings: Sequence[tuple[str, tuple[int, int, int], Sequence[str]]],
) -> dict[str, str]:
    """Return ``{member id: owner id}`` from the ``related`` links of findings.

    ``findings`` holds ``(id, strength, related ids)``. Two linked findings
    state one fact, so the weaker one is folded into the stronger. On a tie
    the finding that lists the other owns it, as its analyzer declared.
    Links to ids that were not emitted are ignored.
    """
    weight = {fid: rank for fid, rank, _ in findings}
    listed = {(fid, other) for fid, _, related in findings for other in related}
    parent: dict[str, str] = {}
    for fid, rank, related in findings:
        for other in related:
            if other == fid or other not in weight:
                continue
            if rank != weight[other]:
                owner, member = (fid, other) if rank < weight[other] else (other, fid)
            elif (other, fid) in listed:  # both list each other: the lower id owns
                owner, member = sorted((fid, other))
            else:
                owner, member = fid, other
            current = parent.get(member)
            if current is None or weight[owner] < weight[current]:
                parent[member] = owner
    roots: dict[str, str] = {}
    for member in parent:
        root, seen = member, set()
        while root in parent and root not in seen:
            seen.add(root)
            root = parent[root]
        if root != member:
            roots[member] = root
    return roots


def window_label(window: str) -> str:
    """Return a short readable label for a window key."""
    return WINDOW_LABELS.get(window, window.replace("_", " "))


def first_sentence(text: str, limit: int = MAX_SENTENCE_CHARS) -> str:
    """Return the first sentence of ``text``, cut at a word boundary if long."""
    text = " ".join(text.split())
    m = _SENTENCE_RE.match(text)
    sentence = m.group(1) if m else text
    if len(sentence) <= limit:
        return sentence
    cut = sentence[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{cut} ..."


def irq_hint(reason: str) -> str:
    """Return what a wake-reason name suggests (``Wi-Fi``), or an empty string."""
    for pattern, hint in _IRQ_HINTS:
        if pattern.search(reason):
            return hint
    return ""


def fmt_span(seconds: float | None) -> str:
    """Format a time span as ``5h02m`` or ``38m``; under a minute as ``27s``."""
    short = seconds is not None and abs(seconds) < SECONDS_PER_MINUTE
    return fmt_duration(seconds, resolution="s" if short else "m")


def fmt_num(value: float | None, digits: int = 1) -> str:
    """Format a number with ``digits`` decimals and thousands separators."""
    if value is None:
        return "?"
    return f"{value:,.{digits}f}"


# --------------------------------------------------------------------------
# Reading the results of other analyzers
# --------------------------------------------------------------------------


def _result(ctx: Context, name: str) -> Result | None:
    result = ctx.results.get(name)
    return result if result is not None and result.status == "ok" else None


def _num(ctx: Context, name: str, key: str) -> float | None:
    """Return a numeric metric, tolerating decimal-comma strings; else None."""
    result = _result(ctx, name)
    if result is None:
        return None
    value = result.metrics.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return parse_decimal(value)
        except ValueError:
            return None
    return None


def _text(ctx: Context, name: str, key: str) -> str | None:
    result = _result(ctx, name)
    value = result.metrics.get(key) if result else None
    return value if isinstance(value, str) and value else None


def _first_num(ctx: Context, *candidates: tuple[str, str]) -> float | None:
    for name, key in candidates:
        if (value := _num(ctx, name, key)) is not None:
            return value
    return None


def _finding(ctx: Context, finding_id: str) -> Finding | None:
    result = _result(ctx, finding_id.split(".", 1)[0])
    if result is None:
        return None
    return next((f for f in result.findings if f.id == finding_id), None)


def _table(ctx: Context, name: str, table: str) -> list[dict]:
    result = _result(ctx, name)
    rows = result.tables.get(table, []) if result else []
    return [row for row in rows if isinstance(row, dict)]


def _cite(ctx: Context, finding_ids: Iterable[str], per_finding: int = 1) -> list:
    """Copy the first evidence entries of upstream findings."""
    evidence: dict[str, Evidence] = {}
    for finding_id in finding_ids:
        if finding := _finding(ctx, finding_id):
            for e in finding.evidence[:per_finding]:
                evidence.setdefault(e.ref, Evidence(e.ref, e.excerpt))
    return list(evidence.values())


def _rate(mah: float | None, seconds: float | None) -> float | None:
    """Return mAh per hour, or None when the window is too short for a rate."""
    if seconds is None or seconds < MIN_RATE_WINDOW_S:
        return None
    return per_hour(mah, seconds)


def _hours(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 3600, 2)


# --------------------------------------------------------------------------
# The measured discharge and the model's share of it
# --------------------------------------------------------------------------

COUNTER_SOURCE = "fuel-gauge counter"
LEVEL_SOURCE = "battery level"


def _positive(ctx: Context, name: str, key: str) -> float | None:
    value = _num(ctx, name, key)
    return value if value is not None and value > 0 else None


def _discharge_total(ctx: Context) -> tuple[float, float, float, str] | None:
    """Return ``(mAh, low, high, source)`` of the discharge since the last charge.

    The fuel-gauge counter ('Discharge: N mAh') comes first. A counter of 0
    means the gauge counted nothing (no coulomb counter, or a capture right
    after unplugging), not that nothing was used. Then the level-based
    'actual drain' range (level change x capacity) gives the midpoint. Its
    'Computed drain' is not used: since Android 12 it is that counter, or
    the same midpoint when the counter is 0, and before that the model's sum.
    """
    for name in ("discharge_accounting", "power_model"):
        if (counter := _positive(ctx, name, "discharge_mah")) is not None:
            return counter, counter, counter, COUNTER_SOURCE
    for name, low_key, high_key in (
        ("power_model", "actual_drain_min_mah", "actual_drain_max_mah"),
        ("discharge_accounting", "actual_drain_low_mah", "actual_drain_high_mah"),
    ):
        low = _num(ctx, name, low_key)
        high = _positive(ctx, name, high_key)
        if high is None or low is None:
            continue
        low = min(max(low, 0.0), high)
        return round((low + high) / 2, 1), low, high, LEVEL_SOURCE
    return None


def _discharge_inputs(ctx: Context) -> dict[str, float | str | None] | None:
    """Gather the discharge split, preferring discharge_accounting."""
    windows = ctx.windows
    on_s = _first_num(
        ctx,
        ("discharge_accounting", "on_battery_s"),
        ("battery_history", "on_battery_s"),
    )
    on_s = on_s if on_s is not None else windows.on_battery_s
    off_s = _num(ctx, "discharge_accounting", "screen_off_s")
    off_s = off_s if off_s is not None else windows.screen_off_on_battery_s
    total = _discharge_total(ctx)
    if total is None or not on_s:
        return None
    mah, low, high, source = total
    on_screen_s = _num(ctx, "discharge_accounting", "screen_on_s")
    if on_screen_s is None and off_s is not None:
        on_screen_s = on_s - off_s
    # The screen and Doze parts come from the same counter as the total.
    counted = source == COUNTER_SOURCE
    parts = {
        part: _num(ctx, "discharge_accounting", key) if counted else None
        for part, key in (
            ("screen_on", "screen_on_mah"),
            ("screen_off", "screen_off_mah"),
            ("deep", "deep_doze_mah"),
            ("light", "light_doze_mah"),
        )
    }
    return {
        "on_s": on_s,
        "off_s": off_s,
        "screen_on_s": on_screen_s,
        "total": mah,
        "total_low": low,
        "total_high": high,
        "source": source,
        **parts,
        "deep_s": _first_num(
            ctx,
            ("discharge_accounting", "idle_mode_full_s"),
            ("discharge_accounting", "device_full_idling_s"),
        ),
        "step": _first_num(
            ctx,
            ("discharge_accounting", "gauge_step_mah"),
            ("gauge_quantization", "step_mah"),
        ),
    }


def _discharge_row(
    part: str,
    mah: float | None,
    seconds: float | None,
    total: float | None,
    basis: str = "measured",
) -> dict:
    return {
        "part": part,
        "hours": _hours(seconds),
        "mah": mah,
        "mah_per_h": _rate(mah, seconds),
        "pct_of_discharge": pct(mah, total),
        "basis": basis,
    }


def _measured_split(d: dict, result: Result) -> None:
    total = d["total"]
    m = result.metrics
    m.update(
        on_battery_s=d["on_s"],
        screen_on_s=d["screen_on_s"],
        screen_off_s=d["off_s"],
        deep_doze_s=d["deep_s"],
        discharge_mah=total,
        discharge_source=d["source"],
        discharge_mah_per_h=_rate(total, d["on_s"]),
        screen_on_mah=d["screen_on"],
        screen_on_mah_per_h=_rate(d["screen_on"], d["screen_on_s"]),
        screen_off_mah=d["screen_off"],
        screen_off_mah_per_h=_rate(d["screen_off"], d["off_s"]),
        deep_doze_mah=d["deep"],
        deep_doze_mah_per_h=_rate(d["deep"], d["deep_s"]),
        light_doze_mah=d["light"],
        gauge_step_mah=d["step"],
    )
    whole = "all time on battery"
    if d["source"] == LEVEL_SOURCE:
        m.update(discharge_mah_low=d["total_low"], discharge_mah_high=d["total_high"])
        whole += (
            f" (from the battery level: {fmt_num(d['total_low'], 0)}-"
            f"{fmt_num(d['total_high'], 0)} mAh)"
        )
        result.notes.append(
            "The fuel gauge counted no discharge, so the total is the midpoint "
            "of the level-based 'actual drain' range (level change x capacity), "
            "and the screen and Doze parts are unknown.",
        )
    if d["step"] and d["screen_off"] is not None:
        low = max(d["screen_off"] - d["step"], 0.0)
        m["screen_off_mah_per_h_low"] = _rate(low, d["off_s"])
        m["screen_off_mah_per_h_high"] = _rate(d["screen_off"] + d["step"], d["off_s"])
    rows = [_discharge_row(whole, total, d["on_s"], total)]
    rows += [
        _discharge_row(part, mah, seconds, total)
        for part, mah, seconds in (
            ("screen on", d["screen_on"], d["screen_on_s"]),
            ("screen off", d["screen_off"], d["off_s"]),
            ("screen off: deep Doze", d["deep"], d["deep_s"]),
            ("screen off: light Doze", d["light"] or None, None),
        )
        if mah is not None
    ]
    result.tables["discharge"] = rows
    short = [
        name
        for name, seconds in (
            ("on battery", d["on_s"]),
            ("screen on", d["screen_on_s"]),
            ("screen off", d["off_s"]),
        )
        if seconds is not None and 0 < seconds < MIN_RATE_WINDOW_S
    ]
    if short:
        result.notes.append(
            f"No mAh/h for {', '.join(short)}: less than "
            f"{MIN_RATE_WINDOW_S // SECONDS_PER_MINUTE} min, where one gauge step "
            "would dominate the rate.",
        )


def _model_split(ctx: Context, result: Result) -> None:
    """Add the power model's share; the remainder is what no component explains.

    A model above the measured drain overestimates on this phone (or the
    counter is coarse): then nothing is left unexplained, the excess is
    reported, and no share of the drain is given.
    """
    total = result.metrics.get("discharge_mah")
    modelled = _num(ctx, "power_model", "modelled_mah")
    if modelled is None or not total:
        return
    attributed = _num(ctx, "power_model", "attributed_mah")
    excess = round(modelled - total, 1) if modelled > total else None
    unmodelled = per_awake_h = None
    if excess is None:
        # Against this budget's total, which may be level-based where
        # power_model used the lower bound.
        unmodelled = round(total - modelled, 1)
        per_awake_h = per_hour(unmodelled, ctx.windows.on_battery_uptime_s)
        if per_awake_h is None and result.metrics["discharge_source"] == COUNTER_SOURCE:
            per_awake_h = _num(ctx, "power_model", "unmodelled_ma_per_awake_h")
    result.metrics.update(
        modelled_mah=modelled,
        modelled_pct=pct(modelled, total),
        attributed_mah=attributed,
        unmodelled_mah=unmodelled,
        unmodelled_pct=pct(unmodelled, total),
        unmodelled_ma_per_awake_h=per_awake_h,
        model_excess_mah=excess,
    )
    rows = result.tables["discharge"]
    on_s = ctx.windows.on_battery_s
    for part, mah in (
        ("power model: components", modelled),
        ("power model: billed to UIDs", attributed),
        ("in no model component", unmodelled),
        ("power model above the measured drain", excess),
    ):
        if mah is not None:
            row = _discharge_row(part, mah, on_s, total, "modelled")
            if excess is not None:
                row["pct_of_discharge"] = None
            rows.append(row)
    components = _table(ctx, "power_model", "components")
    if components:
        result.add_table(
            "model_components",
            [
                {
                    "component": row.get("component"),
                    "mah": row.get("mah"),
                    "apps_mah": row.get("apps_mah"),
                    "pct_of_discharge": row.get("pct_of_discharge"),
                }
                for row in components
            ],
        )


def _reference(result: Result) -> None:
    """Compare screen-off drain with the general-knowledge healthy range."""
    low, high = HEALTHY_STANDBY_MAH_PER_H
    m = result.metrics
    m["reference_standby_mah_per_h_low"] = low
    m["reference_standby_mah_per_h_high"] = high
    rate = m.get("screen_off_mah_per_h")
    if rate is not None:
        m["screen_off_vs_reference_high_x"] = round(rate / high, 1)


def _previous_period(ctx: Context, result: Result) -> None:
    rate = _num(ctx, "previous_cycle", "discharge_mah_per_h")
    if rate is None:
        return
    prev = _result(ctx, "previous_cycle")
    window = prev.window if prev else "daily"
    off_rate = _num(ctx, "previous_cycle", "screen_off_mah_per_h")
    result.metrics.update(
        previous_discharge_mah_per_h=rate,
        previous_screen_off_mah_per_h=off_rate,
    )
    for part, mah_key, s_key in (
        ("previous charge period: on battery", "discharge_mah", "on_battery_s"),
        ("previous charge period: screen off", "screen_off_mah", "screen_off_s"),
    ):
        mah = _num(ctx, "previous_cycle", mah_key)
        seconds = _num(ctx, "previous_cycle", s_key)
        if mah is not None and seconds:
            row = _discharge_row(part, mah, seconds, mah)
            row["pct_of_discharge"] = None
            row["window"] = window
            result.tables["discharge"].append(row)


# --------------------------------------------------------------------------
# The wake chain, in layers that must not be added up
# --------------------------------------------------------------------------

LAYER_ORDER = ("trigger", "enabler", "multiplier", "consequence")


@dataclass
class _Link:
    """One row of the wake chain; ``value`` is in ``unit``, never in mAh."""

    layer: str
    item: str
    value: float | None
    unit: str
    source: str
    window: str
    basis: str = "measured"


def _awake_metrics(ctx: Context, result: Result) -> None:
    m = result.metrics
    m["screen_off_awake_share_pct"] = _first_num(
        ctx,
        ("standby_wake", "awake_share_pct"),
        ("discharge_accounting", "screen_off_awake_share_pct"),
        ("wakelocks", "screen_off_awake_pct"),
    )
    rph = _num(ctx, "standby_wake", "resumes_per_h")
    if rph is not None:
        m["resumes_per_h"] = rph
        m["resumes"] = _num(ctx, "standby_wake", "resumes")
        m["resumes_window"] = "screen_off_on_battery"
    elif (rph := _num(ctx, "wakeup_reasons", "resumes_per_h")) is not None:
        m["resumes_per_h"] = rph
        m["resumes"] = _num(ctx, "wakeup_reasons", "resumes")
        m["resumes_window"] = "on_battery"
    m["awake_per_resume_median_s"] = _num(
        ctx,
        "standby_wake",
        "awake_per_resume_median_s",
    )
    m["awake_without_wakelock_share_pct"] = _first_num(
        ctx,
        ("standby_wake", "awake_without_wakelock_share_pct"),
    )
    m["deep_idle_share_pct"] = _num(ctx, "standby_wake", "deep_idle_share_pct")


def _reason_rows(ctx: Context, result: Result) -> list[_Link]:
    """Top wake reasons as shares of resumes (screen-off history first)."""
    rows = _table(ctx, "standby_wake", "wake_reasons")
    window, source = "screen_off_on_battery", "standby_wake"
    shares = [
        (str(r.get("reason")), r.get("share_pct"))
        for r in rows
        if isinstance(r.get("share_pct"), int | float)
    ]
    if not shares:
        resumes = _num(ctx, "wakeup_reasons", "resumes")
        window, source = "on_battery", "wakeup_reasons"
        shares = [
            (str(r.get("reason")), pct(r["count"], resumes))
            for r in _table(ctx, "wakeup_reasons", "reasons")
            if r.get("class") == "resume" and isinstance(r.get("count"), int | float)
        ]
    shares = [
        (reason, float(share))
        for reason, share in shares
        if isinstance(share, int | float) and share >= MIN_REASON_SHARE_PCT
    ][:TOP_PER_SOURCE]
    if shares:
        top, share = shares[0]
        result.metrics.update(
            top_wake_reason=top,
            top_wake_reason_share_pct=share,
            top_wake_reason_hint=irq_hint(top) or None,
        )
    out = []
    for reason, share in shares:
        hint = irq_hint(reason)
        label = f"wake reason '{reason}'" + (f" (name suggests {hint})" if hint else "")
        out.append(
            _Link("trigger", label, share, "% of resumes", source, window=window),
        )
    return out


def _periodic_rows(ctx: Context, result: Result) -> list[_Link]:
    if _finding(ctx, "wake_periodicity.periodic_sender") is None:
        return []
    period = _num(ctx, "wake_periodicity", "period_s")
    excess = _num(ctx, "wake_periodicity", "grid_excess_pp")
    if period is None or excess is None:
        return []
    result.metrics.update(periodic_period_s=period, periodic_excess_pp=excess)
    return [
        _Link(
            "trigger",
            f"wakes on a {period:.2f} s grid (timer-driven sender), above a "
            "shifted control grid",
            excess,
            "percentage points of resumes (rough upper bound)",
            "wake_periodicity",
            window="screen_off_on_battery",
            basis="inferred",
        ),
    ]


def _alarm_rows(ctx: Context, result: Result) -> list[_Link]:
    share = _num(ctx, "alarms_jobs", "alarms_jobs_pct_of_resumes")
    if share is None:
        return []
    result.metrics["alarms_jobs_pct_of_resumes"] = share
    return [
        _Link(
            "trigger",
            "wakeup alarms and job runs",
            share,
            "% of resumes (at most)",
            "alarms_jobs",
            window="on_battery",
        ),
    ]


def _sample_rows(ctx: Context, result: Result) -> list[_Link]:
    """Per-packet Wi-Fi wake attribution, which covers only a kernel-log sample."""
    packets = _num(ctx, "qcom_wow", "wake_packets")
    if not packets:
        return []
    span = _num(ctx, "qcom_wow", "sample_span_s")
    of = f"% of {packets:.0f} Wi-Fi wake packets in a {fmt_num(span, 0)} s log sample"
    top = _num(ctx, "qcom_wow", "top_sender_share_pct")
    role = _text(ctx, "qcom_wow", "top_sender_role") or "unknown"
    who = SENDER_ROLES.get(role, role.replace("_", " "))
    period = _num(ctx, "qcom_wow", "top_sender_period_s")
    multicast = _num(ctx, "qcom_wow", "multicast_broadcast_pct")
    result.metrics.update(
        sample_wake_packets=packets,
        sample_span_s=span,
        sample_top_sender_share_pct=top,
        sample_top_sender_role=role,
        sample_multicast_pct=multicast,
    )
    rows = []
    if top is not None:
        every = f", every {period:g} s" if period else ""
        rows.append(
            _Link(
                "trigger",
                f"one sender: {who}{every}",
                top,
                of,
                "qcom_wow",
                window="log_coverage",
            ),
        )
    if multicast is not None:
        rows.append(
            _Link(
                "trigger",
                "multicast or broadcast frames",
                multicast,
                of,
                "qcom_wow",
                window="log_coverage",
            ),
        )
    return rows


def _packet_rows(ctx: Context) -> list[_Link]:
    """Steady received packets per app: a packet count, not a share of resumes."""
    finding = _finding(ctx, "network_traffic.steady_background_packets")
    names = finding.metrics.get("uids", []) if finding else []
    traffic = _table(ctx, "network_traffic", "batterystats_traffic")
    by_name = {row.get("name"): row for row in traffic}
    rows = []
    for name in names[:TOP_PER_SOURCE]:
        row = by_name.get(name)
        rate = row.get("rx_pkts_per_s") if row else None
        if isinstance(rate, int | float):
            rows.append(
                _Link(
                    "trigger",
                    f"packets received by {name}",
                    round(rate * 3600),
                    "packets/h (a packet that arrives while awake wakes nothing)",
                    "network_traffic",
                    window="on_battery",
                ),
            )
    if rows or not _result(ctx, "vpn"):
        return rows
    rate = _num(ctx, "vpn", "vpn_app_rx_pkts_per_s")
    if rate is None:
        return rows
    return [
        _Link(
            "trigger",
            "packets received by the VPN app",
            round(rate * 3600),
            "packets/h (a packet that arrives while awake wakes nothing)",
            "vpn",
            window="on_battery",
        ),
    ]


def _enabler_rows(ctx: Context, result: Result) -> list[_Link]:
    held = _num(ctx, "wifi_multicast", "multicast_pct_of_battery")
    rows = []
    if held:
        holder = _text(ctx, "wifi_multicast", "top_package") or "an app"
        result.metrics["multicast_lock_pct_of_battery"] = held
        rows.append(
            _Link(
                "enabler",
                f"Wi-Fi multicast lock held (mostly by {holder})",
                held,
                "% of time on battery",
                "wifi_multicast",
                window="on_battery",
            ),
        )
    fw = _num(ctx, "wifi_multicast", "fw_multicast_broadcast_pct")
    if fw is not None:
        rows.append(
            _Link(
                "enabler",
                "multicast and broadcast frames among Wi-Fi firmware host wakes",
                fw,
                "% of firmware wakes since the Wi-Fi driver started",
                "wifi_multicast",
                window="since_boot",
            ),
        )
    return rows


def _multiplier_rows(ctx: Context, result: Result) -> list[_Link]:
    ratio = _num(ctx, "wakeup_reasons", "abort_to_resume_ratio")
    if ratio is None:
        ratio = _num(ctx, "standby_wake", "suspend_aborts_per_resume")
    result.metrics["aborts_per_resume"] = ratio
    specs = (
        (
            ratio,
            "aborted suspend attempts per real resume",
            "per resume",
            "wakeup_reasons",
            "on_battery",
        ),
        (
            _num(ctx, "wakeup_reasons", "awake_after_aborts_pct_of_uptime"),
            "awake time that followed an aborted suspend attempt",
            "% of awake time on battery",
            "wakeup_reasons",
            "on_battery",
        ),
        (
            result.metrics.get("awake_per_resume_median_s"),
            "awake time per screen-off resume (median)",
            "s",
            "standby_wake",
            "screen_off_on_battery",
        ),
        (
            _num(ctx, "kernel_suspend", "abort_overhead_pct"),
            "kernel-awake time spent in aborted attempts and their back-off",
            "% of kernel-awake time in the log sample",
            "kernel_suspend",
            "log_coverage",
        ),
    )
    return [
        _Link("multiplier", item, value, unit, source, window=window)
        for value, item, unit, source, window in specs
        if value is not None
    ]


def _consequence_rows(ctx: Context) -> list[_Link]:
    rows = []
    for proc in _table(ctx, "system_process_cpu_churn", "processes")[:TOP_PER_SOURCE]:
        cpu = proc.get("cpu_s")
        if isinstance(cpu, int | float):
            core = proc.get("core_pct_on_battery")
            unit = "s CPU" + (f" ({core}% of one core)" if core is not None else "")
            rows.append(
                _Link(
                    "consequence",
                    f"{proc.get('process')} CPU on battery",
                    cpu,
                    unit,
                    "system_process_cpu_churn",
                    window="on_battery",
                ),
            )
    core = _num(ctx, "screen_off_cpu_by_uid", "core_share_pct")
    if core is not None:
        rows.append(
            _Link(
                "consequence",
                "screen-off CPU used by kernel and system UIDs",
                core,
                "% of screen-off CPU time",
                "screen_off_cpu_by_uid",
                window="screen_off_on_battery",
            ),
        )
    return rows


def _wake_chain(ctx: Context, result: Result) -> bool:
    _awake_metrics(ctx, result)
    rows = (
        _reason_rows(ctx, result)
        + _periodic_rows(ctx, result)
        + _alarm_rows(ctx, result)
        + _sample_rows(ctx, result)
        + _packet_rows(ctx)
        + _enabler_rows(ctx, result)
        + _multiplier_rows(ctx, result)
        + _consequence_rows(ctx)
    )
    rows.sort(key=lambda r: LAYER_ORDER.index(r.layer))
    if rows:
        result.add_table("wake_chain", [asdict(r) for r in rows])
    m = result.metrics
    return bool(rows) or m.get("screen_off_awake_share_pct") is not None


# --------------------------------------------------------------------------
# Battery capacity and runtime
# --------------------------------------------------------------------------


def _capacity(ctx: Context, result: Result) -> bool:
    learned = _num(ctx, "battery_capacity", "learned_capacity_mah")
    design = _first_num(
        ctx,
        ("battery_capacity", "design_capacity_mah"),
        ("battery_capacity", "power_profile_capacity_mah"),
    )
    if not learned or not design:
        return False
    m = result.metrics
    m.update(
        learned_capacity_mah=learned,
        design_capacity_mah=design,
        state_of_health_pct=round(100 * learned / design, 1),
        runtime_lost_pct=round(100 * (1 - learned / design), 1),
        new_pack_runtime_factor=round(design / learned, 2),
    )
    for key, rate_key in (
        ("runtime_h_at_average_rate", "discharge_mah_per_h"),
        ("standby_runtime_h", "screen_off_mah_per_h"),
    ):
        if rate := m.get(rate_key):
            m[key] = round(learned / rate, 1)
            m[f"{key}_new_pack"] = round(design / rate, 1)
    daily = _num(ctx, "daily_steps", "median_total_h")
    if daily:
        m["daily_median_runtime_h"] = daily
        m["daily_median_runtime_h_new_pack"] = round(daily * design / learned, 1)
    return True


# --------------------------------------------------------------------------
# The findings of the drain budget
# --------------------------------------------------------------------------


def _reference_sentence(rate: float | None) -> str:
    low, high = HEALTHY_STANDBY_MAH_PER_H
    text = (
        f"A phone that sleeps properly typically uses {low:g}-{high:g} mAh/h with "
        f"the screen off ({REFERENCE_LABEL})"
    )
    if rate is not None:
        text += f"; this phone used {rate / high:.1f}x the upper figure"
    return text + "."


def _rate_text(rate: float | None) -> str:
    return f"{fmt_num(rate)} mAh/h" if rate is not None else "too short for a rate"


def _screen_off_sentence(m: dict) -> str:
    text = (
        f"Screen off: {fmt_num(m['screen_off_mah'], 0)} mAh in "
        f"{fmt_span(m.get('screen_off_s'))} "
        f"({_rate_text(m.get('screen_off_mah_per_h'))}"
    )
    if m.get("screen_off_mah_per_h_low") is not None:
        text += (
            f"; {fmt_num(m['screen_off_mah_per_h_low'])}-"
            f"{fmt_num(m['screen_off_mah_per_h_high'])} with one gauge step "
            "either way"
        )
    text += ")"
    if m.get("deep_doze_mah") is not None:
        text += f", {fmt_num(m['deep_doze_mah'], 0)} mAh of it in deep Doze"
        if m.get("deep_doze_mah_per_h") is not None:
            text += f" ({fmt_num(m['deep_doze_mah_per_h'])} mAh/h)"
    return text + "."


def _total_sentence(m: dict) -> str:
    rate = _rate_text(m.get("discharge_mah_per_h"))
    head = f"On battery for {fmt_span(m.get('on_battery_s'))}: "
    if m.get("discharge_source") == LEVEL_SOURCE:
        return (
            f"{head}about {fmt_num(m['discharge_mah'], 0)} mAh, {rate} "
            f"({fmt_num(m.get('discharge_mah_low'), 0)}-"
            f"{fmt_num(m.get('discharge_mah_high'), 0)} mAh from the battery "
            "level; the fuel gauge counted none)."
        )
    used = fmt_num(m["discharge_mah"], 0)
    return f"{head}{used} mAh ({rate}, counted by the fuel gauge)."


def _model_sentence(m: dict) -> str:
    modelled = fmt_num(m["modelled_mah"], 0)
    if m.get("model_excess_mah") is not None:
        return (
            f"Android's power model bills {modelled} mAh, "
            f"{fmt_num(m['model_excess_mah'], 0)} mAh more than the "
            f"{fmt_num(m['discharge_mah'], 0)} mAh measured, so it overestimates on "
            "this phone or the measurement is coarse; its per-app and per-component "
            "shares are relative to the model, not to the battery."
        )
    return (
        f"Android's power model accounts for {modelled} mAh "
        f"({fmt_num(m['modelled_pct'], 0)}%); {fmt_num(m['unmodelled_mah'], 0)} mAh "
        f"({fmt_num(m['unmodelled_pct'], 0)}%) is in no component, so Settings "
        "> Battery usage cannot show it."
    )


def _budget_sentences(m: dict) -> list[str]:
    parts = [_total_sentence(m)]
    if m.get("screen_on_mah") is not None:
        parts.append(
            f"Screen on: {fmt_num(m['screen_on_mah'], 0)} mAh in "
            f"{fmt_span(m.get('screen_on_s'))} "
            f"({_rate_text(m.get('screen_on_mah_per_h'))}).",
        )
    if m.get("screen_off_mah") is not None:
        parts.append(_screen_off_sentence(m))
    if m.get("modelled_mah") is not None:
        parts.append(_model_sentence(m))
    parts.append(_reference_sentence(m.get("screen_off_mah_per_h")))
    if m.get("previous_discharge_mah_per_h") is not None:
        off = m.get("previous_screen_off_mah_per_h")
        parts.append(
            "The charge period before this one averaged "
            f"{fmt_num(m['previous_discharge_mah_per_h'])} mAh/h"
            + (f" ({fmt_num(off)} mAh/h screen off)" if off is not None else "")
            + ".",
        )
    return parts


def adb_ro_followup(key: str, command: str, look_for: str) -> str:
    """Return a follow-up that saves ``command`` with adb_ro.py and greps it."""
    return (
        f"`adb_ro.py --save {key} --workdir WORKDIR -- {command}`, then "
        f"`grep -E '{look_for}' WORKDIR/live/{key}.txt`"
    )


def _where_it_went(ctx: Context, m: dict) -> Finding:
    test_h = _num(ctx, "gauge_quantization", "min_screen_off_test_h") or DEFAULT_TEST_H
    test_h = max(test_h, DEFAULT_TEST_H)
    keys = (
        "discharge_mah",
        "discharge_source",
        "discharge_mah_per_h",
        "screen_off_mah_per_h",
        "deep_doze_mah_per_h",
        "unmodelled_pct",
        "model_excess_mah",
        "screen_off_vs_reference_high_x",
    )
    about = "about " if m.get("discharge_source") == LEVEL_SOURCE else ""
    return Finding(
        id="drain_budget.where_it_went",
        title=(
            f"Where the charge went: {about}{fmt_num(m['discharge_mah'], 0)} mAh in "
            f"{fmt_span(m.get('on_battery_s'))} on battery"
        ),
        symptom="battery",
        severity="info",
        basis="measured",
        window="on_battery",
        summary=" ".join(_budget_sentences(m)),
        metrics={k: m[k] for k in keys if m.get(k) is not None},
        evidence=_cite(
            ctx,
            ("discharge_accounting.standby_drain", "power_model.unmodelled_drain"),
            per_finding=2,
        ),
        recommendation=(
            "Judge each fix by the measured screen-off mAh/h and the awake share "
            f"over a screen-off test of at least {test_h:g} h on battery, not by "
            "the per-app list in Settings > Battery usage."
        ),
        followups=[
            (
                "After a full charge, leave the phone screen-off on battery for at "
                f"least {test_h:g} h, then save the counters with "
                + adb_ro_followup(
                    "batterystats_retest",
                    "dumpsys batterystats --charged",
                    "Screen off discharge|deep doze discharge",
                )
                + " and compare them with this capture."
            ),
        ],
    )


def _awake_sentences(m: dict) -> list[str]:
    parts = []
    if m.get("screen_off_awake_share_pct") is not None:
        parts.append(
            "With the screen off on battery the processor was awake "
            f"{fmt_num(m['screen_off_awake_share_pct'])}% of the time.",
        )
    if m.get("resumes_per_h") is not None:
        where = (
            "with the screen off"
            if m.get("resumes_window") == "screen_off_on_battery"
            else "on battery"
        )
        rate = fmt_num(m["resumes_per_h"], 0)
        parts.append(f"It resumed {rate} times per hour {where}.")
    return parts


def _trigger_sentence(m: dict) -> list[str]:
    triggers = []
    if m.get("top_wake_reason"):
        hint = m.get("top_wake_reason_hint")
        share = fmt_num(m["top_wake_reason_share_pct"])
        triggers.append(
            f"'{m['top_wake_reason']}' started {share}% of resumes"
            + (f" (the name suggests {hint})" if hint else ""),
        )
    if m.get("periodic_period_s") is not None:
        triggers.append(
            f"a {m['periodic_period_s']:.2f} s timer pattern explains up to "
            f"{fmt_num(m['periodic_excess_pp'])} percentage points of them "
            "(inferred, rough upper bound)",
        )
    if m.get("alarms_jobs_pct_of_resumes") is not None:
        share = fmt_num(m["alarms_jobs_pct_of_resumes"])
        triggers.append(f"alarms and jobs at most {share}%")
    return ["Triggers: " + "; ".join(triggers) + "."] if triggers else []


def _sample_sentence(m: dict) -> list[str]:
    if not m.get("sample_wake_packets"):
        return []
    text = (
        f"In a {fmt_num(m.get('sample_span_s'), 0)} s kernel-log sample of "
        f"{fmt_num(m['sample_wake_packets'], 0)} Wi-Fi wake packets"
    )
    if (top := m.get("sample_top_sender_share_pct")) is not None:
        role = str(m.get("sample_top_sender_role", "unknown"))
        who = SENDER_ROLES.get(role, role.replace("_", " "))
        text += f", one sender ({who}) caused {fmt_num(top)}%"
    if (multicast := m.get("sample_multicast_pct")) is not None:
        text += f" and multicast or broadcast frames {fmt_num(multicast)}%"
    return [text + "; this is a sample of minutes, not the whole period."]


def _multiplier_sentence(m: dict) -> list[str]:
    parts = []
    if m.get("multicast_lock_pct_of_battery"):
        held = fmt_num(m["multicast_lock_pct_of_battery"])
        parts.append(
            "A Wi-Fi multicast lock, which lets LAN multicast through to a sleeping "
            f"phone, was held {held}% of the time on battery.",
        )
    if m.get("aborts_per_resume") is not None:
        ratio = fmt_num(m["aborts_per_resume"], 2)
        text = f"Multiplier: {ratio} aborted suspend attempts per real resume"
        if m.get("awake_per_resume_median_s") is not None:
            awake = fmt_num(m["awake_per_resume_median_s"], 2)
            text += f"; each resume keeps the processor up a median {awake} s"
        parts.append(text + ".")
    return parts


def _wake_finding(ctx: Context, m: dict) -> Finding:
    parts = (
        _awake_sentences(m)
        + _trigger_sentence(m)
        + _sample_sentence(m)
        + _multiplier_sentence(m)
    )
    parts.append(
        "These layers overlap (a trigger starts a wake, aborts stretch it, system "
        "CPU is its cost), so their shares and costs must not be added up.",
    )
    keys = (
        "screen_off_awake_share_pct",
        "resumes_per_h",
        "top_wake_reason",
        "top_wake_reason_share_pct",
        "aborts_per_resume",
    )
    return Finding(
        id="drain_budget.wake_chain",
        title="What keeps the phone awake with the screen off (layers, not a sum)",
        symptom="battery",
        severity="info",
        basis="measured",
        window="screen_off_on_battery",
        summary=" ".join(parts),
        metrics={k: m[k] for k in keys if m.get(k) is not None},
        evidence=_cite(
            ctx,
            (
                "standby_wake.awake_share",
                "wakeup_reasons.suspend_aborts",
                "wake_periodicity.periodic_sender",
                "qcom_wow.dominant-sender",
                "wifi_multicast.lock_held",
            ),
        ),
        recommendation=(
            "Remove triggers first (network senders, multicast locks, alarms): "
            "fewer wakes shrink the multiplier and the system CPU in proportion. "
            "Test one change at a time with a screen-off run on battery."
        ),
        followups=[
            (
                "Run separate screen-off tests on battery with one suspected sender "
                "stopped each time (a VPN paused, a companion app force-stopped, "
                "Wi-Fi off) and compare resumes per hour and the awake share."
            ),
        ],
    )


def _runtime_sentences(m: dict) -> list[str]:
    parts = []
    if m.get("runtime_h_at_average_rate") is not None:
        parts.append(
            f"At this period's average drain ({fmt_num(m['discharge_mah_per_h'])} "
            "mAh/h) a full charge lasts about "
            f"{fmt_num(m['runtime_h_at_average_rate'])} h; a new battery would "
            f"last about {fmt_num(m['runtime_h_at_average_rate_new_pack'])} h.",
        )
    if m.get("standby_runtime_h") is not None:
        parts.append(
            f"In screen-off standby at {fmt_num(m['screen_off_mah_per_h'])} mAh/h: "
            f"{fmt_num(m['standby_runtime_h'])} h against "
            f"{fmt_num(m['standby_runtime_h_new_pack'])} h with a new battery.",
        )
    if m.get("daily_median_runtime_h") is not None:
        new = fmt_num(m["daily_median_runtime_h_new_pack"])
        parts.append(
            "Over the daily history a full charge lasted a median "
            f"{fmt_num(m['daily_median_runtime_h'])} h (level-based); a new "
            f"battery would stretch that to about {new} h.",
        )
    return parts


def _capacity_finding(ctx: Context, m: dict) -> Finding:
    parts = [
        (
            f"The battery holds {fmt_num(m['state_of_health_pct'])}% of its design "
            f"capacity ({fmt_num(m['learned_capacity_mah'], 0)} of "
            f"{fmt_num(m['design_capacity_mah'], 0)} mAh)."
        ),
        *_runtime_sentences(m),
        (
            "Wear shortens runtime by the same factor whatever the drain; it does "
            "not raise the drain in mAh/h."
        ),
    ]
    keys = (
        "state_of_health_pct",
        "new_pack_runtime_factor",
        "runtime_h_at_average_rate",
        "standby_runtime_h",
        "daily_median_runtime_h",
    )
    return Finding(
        id="drain_budget.capacity_effect",
        title=(
            f"Battery wear cuts runtime by {fmt_num(m['runtime_lost_pct'], 0)}%; "
            "it does not raise the drain"
        ),
        symptom="battery",
        severity="info",
        basis="measured",
        window="on_battery",
        summary=" ".join(parts),
        metrics={k: m[k] for k in keys if m.get(k) is not None},
        evidence=_cite(ctx, ("battery_capacity.worn",), per_finding=2),
        recommendation=(
            "Lower the drain rate first; a new battery multiplies whatever runtime "
            "the drain leaves by the same factor."
        ),
        followups=[
            (
                "After two or three full charges on a new battery, read the learned "
                "capacity: "
                + adb_ro_followup(
                    "batterystats_capacity",
                    "dumpsys batterystats --charged",
                    "learned battery capacity",
                )
                + "."
            ),
        ],
    )


@analyzer("drain_budget", after=BUDGET_INPUTS)
def drain_budget(ctx: Context) -> Result:
    """Combine measured discharge, model share, wake chain and battery wear."""
    result = Result("drain_budget", window="on_battery")
    inputs = _discharge_inputs(ctx)
    if inputs is not None:
        _measured_split(inputs, result)
        _model_split(ctx, result)
        _reference(result)
        _previous_period(ctx, result)
    has_chain = _wake_chain(ctx, result)
    has_capacity = _capacity(ctx, result)
    if inputs is None and not has_chain and not has_capacity:
        msg = "no discharge, wake or capacity results to combine"
        raise SkipError(msg)
    m = result.metrics
    if inputs is not None:
        result.findings.append(_where_it_went(ctx, m))
    else:
        result.notes.append("No counter-based discharge on battery was found.")
    if has_chain:
        result.findings.append(_wake_finding(ctx, m))
    if has_capacity:
        result.findings.append(_capacity_finding(ctx, m))
    result.metrics = {k: v for k, v in m.items() if v is not None}
    low, high = HEALTHY_STANDBY_MAH_PER_H
    result.notes += [
        f"The {low:g}-{high:g} mAh/h healthy standby range is {REFERENCE_LABEL}.",
        (
            "wake_chain rows have different denominators (resumes, log-sample "
            "packets, time) and overlapping causes; they are not additive and "
            "carry no per-cause mAh."
        ),
    ]
    return result


# --------------------------------------------------------------------------
# The bottom line
# --------------------------------------------------------------------------


def pick_top(findings: Iterable[Finding], symptom: str) -> list[Finding]:
    """Return the strongest finding per theme for ``symptom``, best first.

    A finding folded into a stronger one through ``related`` is left out:
    its owner already states the fact.
    """
    findings = list(findings)
    folded = owner_map(
        [(f.id, strength(f.severity, f.basis, f.window), f.related) for f in findings],
    )
    best: dict[str, tuple[tuple, Finding]] = {}
    for f in findings:
        if f.id in folded or f.severity == "info" or f.symptom not in {symptom, "both"}:
            continue
        theme, pref = theme_of(f.id)
        key = (
            SEVERITY_RANK.get(f.severity, len(SEVERITY_RANK)),
            BASIS_RANK.get(f.basis, len(BASIS_RANK)),
            pref,
            WINDOW_RANK.get(f.window, len(WINDOW_RANK)),
            f.id,
        )
        if theme not in best or key < best[theme][0]:
            best[theme] = (key, f)
    ranked = sorted(
        (f for _, f in best.values()),
        key=lambda f: rank_key(f.id, f.severity, f.basis, symptom),
    )
    strong = [f for f in ranked if f.severity in STRONG_SEVERITIES]
    if len(strong) >= MIN_STRONG_ITEMS:
        ranked = strong
    return ranked[:MAX_ITEMS]


def finding_window_label(finding_id: str, window: str) -> str:
    """Return the window label, naming the previous charge period explicitly."""
    if finding_id.startswith("previous_cycle."):
        return "previous charge period"
    return window_label(window)


def item_line(n: int, f: Finding, mechanism: str = "") -> str:
    """Return one bottom-line item: title, first sentence, window and basis."""
    return (
        f"{n}. {f.title}: {first_sentence(f.summary)}{mechanism} "
        f"[{finding_window_label(f.id, f.window)}; {f.basis}]"
    )


def _mechanism(ctx: Context, f: Finding) -> str:
    """Name what kept the phone busy in a picked finding's window, if measured.

    Only a share of the same window is added, never mAh across causes.
    """
    radio = ctx.finding("previous_cycle.mobile_radio_busy")
    share = radio.metrics.get("mobile_radio_share_pct") if radio else None
    if f.id != "previous_cycle.heavier_period" or share is None:
        return ""
    return (
        f" The mobile radio was active {fmt_num(share)}% of that period's time on "
        "battery (previous_cycle.mobile_radio_busy)."
    )


def _screen_off_headline(m: dict) -> str:
    text = (
        f"With the screen off it used {fmt_num(m['screen_off_mah_per_h'])} mAh/h "
        f"over {fmt_span(m.get('screen_off_s'))}"
    )
    if (awake := m.get("screen_off_awake_share_pct")) is not None:
        text += f", and the processor was awake {fmt_num(awake)}% of that time"
    if (rate := m.get("resumes_per_h")) is not None:
        text += f", waking {fmt_num(rate, 0)} times per hour"
    if m.get("top_wake_reason"):
        hint = m.get("top_wake_reason_hint")
        text += (
            f" ({fmt_num(m['top_wake_reason_share_pct'])}% of wakes from "
            f"'{m['top_wake_reason']}'" + (f", likely {hint}" if hint else "") + ")"
        )
    return text + "."


def _battery_headline(ctx: Context) -> str | None:
    budget = _result(ctx, "drain_budget")
    if budget is None:
        return None
    m = budget.metrics
    parts = []
    if m.get("discharge_mah") is not None:
        level = m.get("discharge_source") == LEVEL_SOURCE
        used = f"{fmt_num(m['discharge_mah'], 0)} mAh"
        if level:
            used = (
                f"about {used} ({fmt_num(m.get('discharge_mah_low'), 0)}-"
                f"{fmt_num(m.get('discharge_mah_high'), 0)} mAh by the battery level)"
            )
        rate = m.get("discharge_mah_per_h")
        about = "about " if level else ""
        rate_text = f" ({about}{fmt_num(rate)} mAh/h)" if rate is not None else ""
        parts.append(
            f"On battery since the last full charge the phone used {used} in "
            f"{fmt_span(m.get('on_battery_s'))}{rate_text}.",
        )
    if m.get("screen_off_mah_per_h") is not None:
        parts.extend((_screen_off_headline(m), _reference_sentence(None)))
    return " ".join(parts) or None


def _summary_finding(ctx: Context, symptom: Symptom, picked: list[Finding]) -> Finding:
    lines = []
    if symptom == "battery" and (headline := _battery_headline(ctx)):
        lines.append(headline)
    if picked:
        lines += [item_line(n, f, _mechanism(ctx, f)) for n, f in enumerate(picked, 1)]
    else:
        lines.append(f"No {symptom} problem was found by the analyzers that ran.")
    label = "Battery" if symptom == "battery" else "Slowness"
    top = picked[0] if picked else None
    followups: list[str] = []
    for f in picked:
        if f.followups and f.followups[0] not in followups:
            followups.append(f.followups[0])
    recommendation = (
        "Work through the items in order; each finding below has its own "
        "recommendation."
    )
    if symptom == "battery":
        recommendation += (
            " Judge battery fixes by measured screen-off drain and awake share, not "
            "by the per-app list in Settings > Battery usage."
        )
    return Finding(
        id=f"bottom_line.{symptom}",
        title=f"{label}: the main problems" if picked else f"{label}: nothing found",
        symptom=symptom,
        severity="info",
        basis=top.basis if top else "measured",
        window=top.window if top else "on_battery",
        summary="\n".join(lines),
        metrics={
            "finding_ids": [f.id for f in picked],
            "severities": [f.severity for f in picked],
        },
        evidence=[
            Evidence(f.evidence[0].ref, f.evidence[0].excerpt)
            for f in picked
            if f.evidence
        ],
        recommendation=recommendation,
        followups=followups,
    )


def _gap_order(name: str) -> tuple[int, str]:
    if name in KEY_ANALYZERS:
        return KEY_ANALYZERS.index(name), name
    return len(KEY_ANALYZERS), name


def _gap_lines(ctx: Context) -> tuple[list[str], list[str], list[str]]:
    """Return (lines, missing input keys, follow-ups) for the coverage finding."""
    lines: list[str] = []
    gaps = sorted(
        (name for name, r in ctx.results.items() if r.status != "ok"),
        key=_gap_order,
    )
    gaps = [name for name in gaps if name not in OWN_ANALYZERS]
    for name in gaps[:MAX_LISTED_GAPS]:
        r = ctx.results[name]
        verb = "failed" if r.status == "error" else "skipped"
        lines.append(f"Analyzer {name} {verb}: {r.reason or 'no reason given'}.")
    if len(gaps) > MAX_LISTED_GAPS:
        lines.append(f"{len(gaps) - MAX_LISTED_GAPS} more analyzers did not run.")
    missing: list[str] = []
    followups: list[str] = []
    for key, lost in KEY_INPUTS.items():
        try:
            present = ctx.sources.has(key)
        except KeyError:
            continue
        if not present:
            missing.append(key)
            lines.append(f"Missing input {key}: {lost}.")
            if key in COLLECT_COMMANDS:
                followups.append(collect_followup(key))
    return lines, missing, followups


def collect_followup(key: str) -> str:
    """Return how to add the missing input ``key`` to the workdir."""
    command = COLLECT_COMMANDS[key]
    try:
        check_adhoc(command)
    except ValueError:
        # A loop or a sequence that only collect.py may run.
        return (
            f"Collect {key} with `collect.py --only {key}`, copy live/{key}.txt "
            "from the new workdir into WORKDIR/live/, then run analyze.py again."
        )
    return (
        f"Collect {key} with `adb_ro.py --save {key} --workdir WORKDIR -- "
        f"{command}`, then run analyze.py again."
    )


def _caveat_lines(ctx: Context) -> list[str]:
    w = ctx.windows
    lines = []
    if w.on_battery_at_capture is False:
        lines.append(
            "The phone was on external power at capture, so live states (battery "
            "saver, Doze, thermal status, memory pressure) describe charging, not "
            "use on battery.",
        )
    if w.on_battery_s is None:
        lines.append("No time on battery since the last charge was found.")
    if w.utc_offset is None:
        lines.append(
            "The UTC offset at capture is not recorded; analyzers that align UTC "
            "logs estimated it.",
        )
    if packets := _num(ctx, "qcom_wow", "wake_packets"):
        span = fmt_num(_num(ctx, "qcom_wow", "sample_span_s"), 0)
        lines.append(
            f"Per-packet Wi-Fi wake attribution covers a {span} s kernel-log sample "
            f"({fmt_num(packets, 0)} wake packets), not the whole battery period.",
        )
    unmodelled = _num(ctx, "power_model", "unmodelled_pct")
    if unmodelled is not None and unmodelled > UNMODELLED_FLAG_PCT:
        lines.append(
            f"{fmt_num(unmodelled)}% of the measured drain is in no power-model "
            "component. Without energy metering its split cannot be measured; "
            "linking it to awake time is inferred.",
        )
    if (excess := _num(ctx, "drain_budget", "model_excess_mah")) is not None:
        lines.append(
            f"Android's power model bills {fmt_num(excess, 0)} mAh more than the "
            "measured drain, so per-app shares are shares of the model, not of the "
            "battery.",
        )
    if _text(ctx, "drain_budget", "discharge_source") == LEVEL_SOURCE:
        lines.append(
            "The fuel gauge counted no discharge since the last charge, so the "
            "drain comes from the battery level, which moves in whole percent "
            "steps, and the screen-on and screen-off split is unknown.",
        )
    ring_buffers = ("exit_info_audit", "lmkd_kills", "process_churn")
    if any(_result(ctx, name) for name in ring_buffers):
        lines.append(
            "Counts from ring buffers (exit records, logs, the kernel log) are "
            "lower bounds.",
        )
    return lines


def _not_determined(ctx: Context) -> Finding:
    gap_lines, missing, followups = _gap_lines(ctx)
    lines = gap_lines + _caveat_lines(ctx)
    if not lines:
        lines.append("Every analyzer ran and every key input was present.")
    return Finding(
        id="bottom_line.not_determined",
        title="What this analysis could not determine",
        symptom="info",
        severity="info",
        basis="inferred",
        window="snapshot",
        summary="\n".join(lines),
        metrics={"missing_inputs": missing},
        recommendation=(
            "To close the gaps, collect again on battery (over wireless debugging, "
            "or before plugging in) after at least two hours with the screen off, "
            "and include the missing inputs."
        ),
        followups=followups,
    )


def _upstream() -> tuple[str, ...]:
    """Every analyzer registered before this module (budget is imported last)."""
    known = (*BUDGET_INPUTS, *_ANALYZER_THEME)
    registered = tuple(name for name in REGISTRY if name not in OWN_ANALYZERS)
    return (*dict.fromkeys((*registered, *known)), "drain_budget")


@analyzer("bottom_line", after=_upstream())
def bottom_line(ctx: Context) -> Result:
    """Pick the top battery and slowness findings and list what is unknown."""
    upstream = {n: r for n, r in ctx.results.items() if n not in OWN_ANALYZERS}
    if not any(n != "windows" for n in upstream):
        msg = "no analyzer results to summarise"
        raise SkipError(msg)
    findings = [f for r in upstream.values() for f in r.findings]
    result = Result("bottom_line", window="on_battery")
    symptoms: tuple[Symptom, ...] = ("battery", "slowness")
    for symptom in symptoms:
        picked = pick_top(findings, symptom)
        result.findings.append(_summary_finding(ctx, symptom, picked))
        result.tables[f"top_{symptom}"] = [
            {
                "rank": n,
                "id": f.id,
                "theme": theme_of(f.id)[0],
                "severity": f.severity,
                "basis": f.basis,
                "window": f.window,
                "title": f.title,
            }
            for n, f in enumerate(picked, 1)
        ]
    result.findings.append(_not_determined(ctx))
    statuses = [r.status for r in upstream.values()]
    result.metrics = {
        "findings_considered": len(findings),
        "high_findings": sum(f.severity == "high" for f in findings),
        "analyzers_ok": statuses.count("ok"),
        "analyzers_skipped": statuses.count("skipped"),
        "analyzers_failed": statuses.count("error"),
        "battery_items": len(result.tables["top_battery"]),
        "slowness_items": len(result.tables["top_slowness"]),
    }
    return result
