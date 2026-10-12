"""Performance and configuration analyzers.

Each analyzer reads one family of dumps:

- ``frame_jank``: janky frames and frame-time percentiles per app, from the
  daily buckets of ``dumpsys graphicsstats``.
- ``app_launch_times``: launch durations from the event and system logs, and
  start types and first-frame times from ``dumpsys activity start-info``.
- ``battery_saver_state``: how much of the battery time Battery Saver was on,
  its policy, and the settings that keep it on.
- ``settings_audit``: settings and developer options that slow the UI or
  keep radios scanning.
- ``thermal_status``: thermal status, sensor readings, trip points, cooling
  devices, thermal job restrictions and CPU frequency caps.
- ``storage_io_per_uid``: flash reads and writes per UID from storaged, and
  free space and write latency from diskstats.
- ``dexopt_status``: ART compiler filter per app and the background dexopt job.
- ``build_identity``: OS, vendor-image and kernel versions and the last OTA
  install, for matching known issues (boot reasons are low_battery_shutdowns').

Locale matters: graphicsstats prints a decimal point while ``dumpsys power``
drain stats and batterystats print decimal commas on some phones, so every
number goes through the parser that fits its field.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, Any

from .batterystats import load_since_charge
from .common import (
    iter_logcat,
    load_event_log,
    load_settings,
    log_span,
    parse_decimal,
    parse_duration_ms,
)
from .model import Context, Evidence, Finding, Result, SkipError, analyzer

if TYPE_CHECKING:
    from .common import LogLine, Settings
    from .model import Basis, Severity, Symptom
    from .source import Text

# Findings that name apps list at most this many; the rest stay in the tables.
MAX_LISTED = 5

GIB = 1024**3
MIB = 1024**2
SECONDS_PER_DAY = 86_400
SECONDS_PER_HOUR = 3600
MS_PER_S = 1000
PERCENT = 100


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _note_skipped(result: Result, text: Text, skipped: int) -> None:
    if skipped:
        result.notes.append(
            f"{skipped} unrecognised lines in {text.origin} were skipped.",
        )


def _adb_ro(key: str, command: str, search: str) -> str:
    """Phrase a follow-up as a read-only capture and a local search of it."""
    return (
        f"adb_ro.py --save {key} --workdir WORKDIR -- {command}, then {search} "
        f"WORKDIR/live/{key}.txt"
    )


# Prints "path:value" for the current and hardware CPU frequency limits.
_CPUFREQ_MAX_COMMAND = (
    "grep -H . /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq "
    "/sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq"
)


def _uptime_s(ctx: Context) -> float | None:
    dump, boot = ctx.windows.dump_time, ctx.windows.boot_time
    if dump and boot and dump > boot:
        return (dump - boot).total_seconds()
    return None


def _strptime(text: str, fmt: str) -> datetime | None:
    """Parse a timestamp, returning None for impossible dates."""
    try:
        return datetime.strptime(text, fmt)
    except ValueError:
        return None


def _from_epoch(seconds: float) -> datetime | None:
    """Return the UTC time of an epoch value, or None if it is out of range."""
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _charging_caveat(ctx: Context) -> str:
    if ctx.windows.on_battery_at_capture is False:
        return (
            " The phone was on external power at capture, so this state "
            "describes charging, not use on battery."
        )
    return ""


def _system_log_lines(
    ctx: Context,
    needles: tuple[str, ...],
) -> tuple[Text | None, list[tuple[int, LogLine]]]:
    """Return the system log and ``(index, line)`` of lines with any needle."""
    text = ctx.sources.get("logcat_system")
    if text is None:
        return None, []
    reference = ctx.windows.log_reference()
    found = [
        (i, entry)
        for i, line in enumerate(text.lines)
        if any(needle in line for needle in needles)
        for entry in iter_logcat(line, reference, text.first_line + i)
    ]
    return text, found


def _events(
    ctx: Context, tags: tuple[str, ...]
) -> tuple[Text | None, list[tuple[int, LogLine]]]:
    """Return the event log and ``(index, line)`` of its lines with these tags."""
    log = load_event_log(ctx)
    if log.text is None:
        return None, []
    first = log.text.first_line
    return log.text, [(x.lineno - first, x) for x in log.lines if x.tag in tags]


# Samsung appends restore flags to dumpsys settings rows, after the value.
_RESTORE_FLAG_RE = re.compile(
    r" (?:isValuePreservedInRestore:\S*|notPreservedInRestore)$"
)


def _setting(settings: Settings, key: str, namespace: str = "") -> str | None:
    """Return a setting's value; ``{null}`` (dumpsys settings) is None."""
    value = settings.value(key, namespace)
    value = _RESTORE_FLAG_RE.sub("", value) if value else value
    return None if value == "{null}" else value


_HOME_RE = re.compile(r"^([A-Za-z][\w.]*)/\S+$")


def _home_package(ctx: Context) -> str | None:
    """Return the default launcher from ``cmd package resolve-activity``."""
    text = ctx.sources.get("home_activity")
    if text is None:
        return None
    for line in reversed(text.lines):
        if m := _HOME_RE.match(line.strip()):
            return m[1]
    return None


def key_packages(ctx: Context) -> dict[str, str]:
    """Return ``{package: role}`` for system UI, launcher, keyboard and TTS."""
    roles = {"com.android.systemui": "system UI"}
    if home := _home_package(ctx):
        roles[home] = "home launcher"
    settings = load_settings(ctx)
    if settings:
        for key, role in (
            ("default_input_method", "keyboard"),
            ("tts_default_synth", "text-to-speech"),
        ):
            if value := _setting(settings, key, "secure"):
                roles.setdefault(value.split("/", 1)[0], role)
    return roles


def _role(package: str, roles: dict[str, str]) -> str:
    if package in roles:
        return roles[package]
    return "launcher" if "launcher" in package.lower() else ""


# --------------------------------------------------------------------------
# frame_jank
# --------------------------------------------------------------------------

# A 60 Hz display refreshes every 16.7 ms; graphicsstats does not record the
# refresh rate, so the 60 Hz period is the lenient choice. Frame durations run
# from the intended vsync to completion and include pipelining (hwui
# JankTracker), so a long frame can still meet its deadline: a median of 20 ms
# or more with few janky frames means continuous redrawing, not late frames.
MEDIAN_FRAME_FLAG_MS = 20
# Daily buckets with fewer frames are left out of the per-day janky range.
RANGE_MIN_FRAMES = 100
# Janky percentages of fewer frames are dominated by a few slow resume frames.
MIN_FRAMES = 300
# More than one janky frame in five is visible stutter.
JANKY_PCT_FLAG = 20.0
# One in three janky frames makes an app feel broken, if it is used enough.
JANKY_PCT_HIGH = 30.0
# A high share counts as high severity only with this many janky frames (about
# half a minute of missed frames at 60 Hz over the buckets) or for an app on
# screen every day; a short phone call with a janky in-call screen is not.
JANKY_FRAMES_HIGH = 2000
EVERYDAY_ROLES = frozenset({"system UI", "home launcher", "launcher", "keyboard"})
# GPU work overlaps the next frame, so only a GPU p95 beyond 1.5 refresh
# periods at 60 Hz marks the GPU itself as the bottleneck.
GPU_BOUND_P95_MS = 24
# The last GPU histogram bucket collects every frame over 25 ms.
GPU_OVERFLOW_MS = 4950
# The tail percentile used to judge whether the GPU keeps up.
TAIL_PERCENTILE = 95
# Daily bucket rows are shown for the flagged apps, then the worst others, up
# to this many apps.
BUCKET_TABLE_APPS = 6
_NS_THRESHOLD = 10**15  # larger "Stats since" values are true nanoseconds
_SECONDS_THRESHOLD = 10**11  # smaller values are epoch seconds

_GFX_PACKAGE_RE = re.compile(r"^Package: (\S+)")
_GFX_SINCE_RE = re.compile(r"^Stats since: (\d+)ns")
_GFX_END_RE = re.compile(r"^Stats end: (\d+)ns")
_GFX_TOTAL_RE = re.compile(r"^Total frames rendered: (\d+)")
_GFX_JANKY_RE = re.compile(r"^Janky frames: (\d+) \(")
_GFX_PCT_RE = re.compile(r"^(\d+)th (gpu )?percentile: (\d+)ms")
_GFX_COUNTER_RE = re.compile(r"^Number ([A-Za-z ]+): (\d+)")
_GFX_HIST_RE = re.compile(r"^(GPU )?HISTOGRAM: (.*)")
_GFX_BUCKET_RE = re.compile(r"(\d+)ms=(\d+)")
_GFX_KNOWN_PREFIXES = ("Version:", "Pipeline")


def _epoch_ms(value: int) -> int:
    """Normalise graphicsstats stamps: printed with ``ns`` but in milliseconds."""
    if value > _NS_THRESHOLD:
        return value // 1_000_000
    if value < _SECONDS_THRESHOLD:
        return value * MS_PER_S
    return value


@dataclass
class GfxBlock:
    """One package's stats for one daily graphicsstats bucket."""

    package: str
    index: int
    since_ms: int | None = None
    end_ms: int | None = None
    frames: int = 0
    janky: int = 0
    percentiles: dict[int, int] = field(default_factory=dict)
    gpu_percentiles: dict[int, int] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    histogram: dict[int, int] = field(default_factory=dict)
    gpu_histogram: dict[int, int] = field(default_factory=dict)
    refs: dict[str, int] = field(default_factory=dict)

    @property
    def janky_pct(self) -> float:
        """Janky share recomputed from counts (the dump may print ``nan``)."""
        return PERCENT * self.janky / self.frames if self.frames else 0.0

    @property
    def day_utc(self) -> str:
        """The UTC day the bucket starts on; buckets are UTC-day aligned."""
        if self.since_ms is None:
            return ""
        day = _from_epoch(self.since_ms / MS_PER_S)
        return day.date().isoformat() if day else ""


def _gfx_percentile(block: GfxBlock, m: re.Match[str], index: int) -> None:
    target = block.gpu_percentiles if m[2] else block.percentiles
    target[int(m[1])] = int(m[3])
    block.refs.setdefault(f"{'gpu_' if m[2] else ''}p{m[1]}", index)


def _gfx_counter(block: GfxBlock, m: re.Match[str], index: int) -> None:
    key = _slug(m[1])
    block.counters[key] = int(m[2])
    block.refs[key] = index


def _gfx_histogram(block: GfxBlock, m: re.Match[str], _index: int) -> None:
    histogram = {int(a): int(b) for a, b in _GFX_BUCKET_RE.findall(m[2])}
    if m[1]:
        block.gpu_histogram = histogram
    else:
        block.histogram = histogram


def _gfx_janky(block: GfxBlock, m: re.Match[str], index: int) -> None:
    block.janky = int(m[1])
    block.refs["janky"] = index


def _gfx_total(block: GfxBlock, m: re.Match[str], _index: int) -> None:
    block.frames = int(m[1])


def _gfx_since(block: GfxBlock, m: re.Match[str], _index: int) -> None:
    block.since_ms = _epoch_ms(int(m[1]))


def _gfx_end(block: GfxBlock, m: re.Match[str], _index: int) -> None:
    block.end_ms = _epoch_ms(int(m[1]))


_GFX_HANDLERS = (
    (_GFX_PCT_RE, _gfx_percentile),
    (_GFX_COUNTER_RE, _gfx_counter),
    (_GFX_HIST_RE, _gfx_histogram),
    (_GFX_JANKY_RE, _gfx_janky),
    (_GFX_TOTAL_RE, _gfx_total),
    (_GFX_SINCE_RE, _gfx_since),
    (_GFX_END_RE, _gfx_end),
)


def _parse_gfx_line(block: GfxBlock, line: str, index: int) -> bool:
    """Fill ``block`` from one line; return False if the line is unknown."""
    for regex, handler in _GFX_HANDLERS:
        if m := regex.match(line):
            handler(block, m, index)
            return True
    return line.startswith(_GFX_KNOWN_PREFIXES)


def parse_graphicsstats(text: Text) -> tuple[list[GfxBlock], int]:
    """Return the package blocks and the number of unrecognised lines."""
    blocks: list[GfxBlock] = []
    current: GfxBlock | None = None
    skipped = 0
    for i, line in enumerate(text.lines):
        if m := _GFX_PACKAGE_RE.match(line):
            current = GfxBlock(m[1], i)
            blocks.append(current)
        elif current and line.strip() and not _parse_gfx_line(current, line, i):
            skipped += 1
    return blocks, skipped


def load_graphicsstats(ctx: Context) -> tuple[Text | None, list[GfxBlock], int]:
    """Return the graphicsstats text, its package blocks and the skipped lines."""

    def build() -> tuple[Text | None, list[GfxBlock], int]:
        text = ctx.sources.get("graphicsstats")
        if text is None:
            return None, [], 0
        return text, *parse_graphicsstats(text)

    return ctx.sources.memo("graphicsstats_blocks", build)


def hist_percentile(histogram: dict[int, int], pct: int) -> int | None:
    """Return a percentile the way graphicsstats prints it.

    AOSP ``GraphicsStatsService`` ``findPercentile`` takes the integer position
    ``pct * total / 100`` and walks down from the slowest bucket until the
    frames above that position are used up.
    """
    total = sum(histogram.values())
    if not total:
        return None
    remaining = total - pct * total // PERCENT
    for ms in sorted(histogram, reverse=True):
        remaining -= histogram[ms]
        if remaining <= 0:
            return ms
    return None


def _merged_percentiles(
    blocks: list[GfxBlock],
    *,
    gpu: bool = False,
) -> dict[int, int | None]:
    """Percentiles over all buckets, from the summed frame-time histograms.

    Without histograms, fall back to the worst per-bucket percentile.
    """
    merged: dict[int, int] = {}
    for block in blocks:
        for ms, count in (block.gpu_histogram if gpu else block.histogram).items():
            merged[ms] = merged.get(ms, 0) + count
    if merged:
        return {p: hist_percentile(merged, p) for p in (50, 90, 95, 99)}
    return {
        p: max(
            ((b.gpu_percentiles if gpu else b.percentiles).get(p, 0) for b in blocks),
            default=None,
        )
        for p in (50, 90, 95, 99)
    }


def _bottleneck(counters: dict[str, int], gpu_p95: int | None) -> str:
    """Name the dominant slow stage of janky frames."""
    if gpu_p95 is not None and gpu_p95 > GPU_BOUND_P95_MS:
        return "gpu"
    stages = {
        "ui_thread": counters.get("slow_ui_thread", 0),
        "bitmap_uploads": counters.get("slow_bitmap_uploads", 0),
        "draw_commands": counters.get("slow_issue_draw_commands", 0),
    }
    if not any(stages.values()):
        return ""
    return max(stages, key=lambda k: stages[k])


def _sum_counters(blocks: list[GfxBlock]) -> dict[str, int]:
    total: dict[str, int] = {}
    for block in blocks:
        for key, value in block.counters.items():
            total[key] = total.get(key, 0) + value
    return total


def _latest(blocks: list[GfxBlock]) -> GfxBlock:
    return max(blocks, key=lambda b: (b.end_ms or 0, b.since_ms or 0))


def _app_row(package: str, blocks: list[GfxBlock], role: str) -> dict[str, Any]:
    frames = sum(b.frames for b in blocks)
    janky = sum(b.janky for b in blocks)
    counted = [b for b in blocks if b.frames >= RANGE_MIN_FRAMES] or [
        b for b in blocks if b.frames
    ]
    pcts = [b.janky_pct for b in counted]
    gpu_p95 = _merged_percentiles(blocks, gpu=True)[TAIL_PERCENTILE] or None
    counters = _sum_counters(blocks)
    merged = _merged_percentiles(blocks)
    latest = _latest(blocks)
    return {
        "package": package,
        "role": role,
        "daily_buckets": len(blocks),
        "frames": frames,
        "janky_frames": janky,
        "janky_pct": _round(PERCENT * janky / frames if frames else 0.0),
        "janky_pct_min_day": _round(min(pcts)) if pcts else None,
        "janky_pct_max_day": _round(max(pcts)) if pcts else None,
        "p50_ms": merged[50],
        "p90_ms": merged[90],
        "p95_ms": merged[95],
        "p99_ms": merged[99],
        "gpu_p95_ms": gpu_p95,
        "slow_ui_thread": counters.get("slow_ui_thread", 0),
        "slow_bitmap_uploads": counters.get("slow_bitmap_uploads", 0),
        "slow_issue_draw_commands": counters.get("slow_issue_draw_commands", 0),
        "high_input_latency": counters.get("high_input_latency", 0),
        "bottleneck": _bottleneck(counters, gpu_p95),
        "latest_day_utc": latest.day_utc,
        "latest_frames": latest.frames,
        "latest_janky_pct": _round(latest.janky_pct),
        "latest_p95_ms": latest.percentiles.get(95),
        "latest_p99_ms": latest.percentiles.get(99),
    }


def _jank_rank(row: dict[str, Any]) -> tuple[bool, int, float]:
    """Rank apps by exposure: janky frames, then the janky share."""
    return (
        row["frames"] >= MIN_FRAMES,
        row["janky_frames"],
        row["janky_pct"] or 0.0,
    )


def _app_severity(row: dict[str, Any]) -> Severity:
    """High needs a high janky share and either many janky frames or a role."""
    exposed = row["janky_frames"] >= JANKY_FRAMES_HIGH or row["role"] in EVERYDAY_ROLES
    return "high" if row["janky_pct"] >= JANKY_PCT_HIGH and exposed else "medium"


def _label(row: dict[str, Any]) -> str:
    return f"{row['package']} ({row['role']})" if row["role"] else row["package"]


def _peak(blocks: list[GfxBlock], key: str) -> GfxBlock:
    """Return the bucket with the highest ``key`` count (``frames``, ``janky``)."""
    return max(blocks, key=lambda b: (getattr(b, key), b.end_ms or 0))


_BOTTLENECK_TEXT = {
    "ui_thread": (
        "most janky frames had a slow UI thread while the GPU kept up, so the "
        "time goes on the CPU side (app code, memory or I/O stalls), not the GPU"
    ),
    "gpu": "the GPU itself is slow on the worst frames, so rendering is GPU-bound",
    "bitmap_uploads": (
        "slow bitmap uploads dominate (images decoded or uploaded late, a CPU "
        "and memory cost), not GPU rendering"
    ),
    "draw_commands": (
        "slow issuing of draw commands dominates (the render thread on the CPU "
        "is late), not GPU rendering"
    ),
}


def _janky_summary(apps: list[dict[str, Any]], key: dict[str, Any]) -> str:
    """List the apps by exposure, then describe the one that sets the severity."""
    head = [
        f"{_label(r)} {r['janky_pct']}% of {r['frames']:,} frames" for r in apps[:3]
    ]
    summary = "Most janky frames: " + (
        f"{', '.join(head[:-1])} and {head[-1]}." if len(head) > 1 else f"{head[0]}."
    )
    if rest := apps[3:]:
        summary += (
            f" Also over {JANKY_PCT_FLAG:.0f}%: "
            + ", ".join(
                f"{_label(r)} {r['janky_pct']}% of {r['frames']:,}" for r in rest
            )
            + "."
        )
    summary += (
        f" For {key['package']}, the slowest 5% / 1% of frames took at least "
        f"{key['p95_ms']} / {key['p99_ms']} ms"
    )
    if key["bottleneck"] in _BOTTLENECK_TEXT:
        gpu = key["gpu_p95_ms"]
        gpu = "over 25" if gpu == GPU_OVERFLOW_MS else gpu
        summary += f" and GPU p95 is {gpu} ms; "
        summary += _BOTTLENECK_TEXT[key["bottleneck"]]
    return summary + "."


def _janky_finding(
    apps: list[dict[str, Any]],
    by_package: dict[str, list[GfxBlock]],
    text: Text,
) -> Finding:
    """One finding for every app over the janky threshold, worst exposure first."""
    severities = [_app_severity(r) for r in apps]
    severity: Severity = "high" if "high" in severities else "medium"
    # The details describe the app that sets the severity.
    key = apps[severities.index(severity)]
    cited = apps[:3] + ([key] if key not in apps[:3] else [])
    evidence = []
    for row in cited:
        peak = _peak(by_package[row["package"]], "janky")
        evidence += [text.evidence(peak.refs[k]) for k in ("janky",) if k in peak.refs]
    peak = _peak(by_package[key["package"]], "janky")
    evidence += [
        text.evidence(peak.refs[k]) for k in ("p99", "gpu_p95") if k in peak.refs
    ]
    return Finding(
        id="frame_jank.janky_apps",
        title=f"{len(apps)} apps drew over {JANKY_PCT_FLAG:.0f}% janky frames",
        symptom="slowness",
        severity=severity,
        basis="measured",
        window="daily",
        summary=_janky_summary(apps, key),
        metrics={
            "apps": len(apps),
            "packages": [r["package"] for r in apps],
            "janky_frames": {r["package"]: r["janky_frames"] for r in cited},
            "janky_pct": {r["package"]: r["janky_pct"] for r in cited},
            "severity_from": key["package"],
            "p95_ms": key["p95_ms"],
            "p99_ms": key["p99_ms"],
            "gpu_p95_ms": key["gpu_p95_ms"],
        },
        evidence=evidence,
        recommendation=(
            "Start with the apps at the top of the list: they stutter most "
            "often. Check what competes with them while they stutter: memory "
            "pressure (low-memory kills, swap, page-cache refaults), background "
            "CPU bursts after unlock, or the app itself (update it, or try an "
            "alternative such as the stock launcher or keyboard). Compare the "
            "graphicsstats dump a day apart after each change."
        ),
        followups=[
            (
                "Right after a stutter, run "
                + _adb_ro(
                    f"gfxinfo_{_slug(key['package'])}",
                    f"dumpsys gfxinfo {key['package']} framestats",
                    "grep -E 'Janky|Slow|percentile'",
                )
                + " to see which frame stage is slow"
            ),
            "Record a Perfetto trace while reproducing the stutter",
            (
                "Compare with the memory findings: do low-memory kills or refaults "
                "coincide with the janky days?"
            ),
        ],
    )


def _slow_frames_finding(
    apps: list[dict[str, Any]],
    by_package: dict[str, list[GfxBlock]],
    text: Text,
) -> Finding:
    """One finding for apps whose median frame is long though few are janky."""
    listed = "; ".join(
        f"{r['package']} {r['p50_ms']} ms over {r['frames']:,} frames "
        f"({r['janky_pct']}% janky)"
        for r in apps[:MAX_LISTED]
    )
    if len(apps) > MAX_LISTED:
        listed += f"; and {len(apps) - MAX_LISTED} more"
    evidence = []
    for row in apps[:3]:
        peak = _peak(by_package[row["package"]], "frames")
        evidence += [text.evidence(peak.refs[k]) for k in ("p50",) if k in peak.refs]
    first = apps[0]["package"]
    return Finding(
        id="frame_jank.slow_frames",
        title=(
            f"{len(apps)} apps take {MEDIAN_FRAME_FLAG_MS} ms or more for half "
            "their frames"
        ),
        symptom="both",
        severity="low",
        basis="measured",
        window="daily",
        summary=(
            f"Median frame times of {MEDIAN_FRAME_FLAG_MS} ms or more, over the "
            f"16.7 ms refresh period of a 60 Hz display: {listed}. A frame time "
            "runs from the intended vsync to completion and overlaps the next "
            f"frames, so with under {JANKY_PCT_FLAG:.0f}% janky most of these "
            "frames were still shown on time. Long frames that meet their "
            "deadline point to an app that redraws continuously, which costs "
            "CPU and GPU time and adds touch latency while it is open "
            "(inferred)."
        ),
        metrics={
            "apps": len(apps),
            "packages": [r["package"] for r in apps],
            "p50_ms": {r["package"]: r["p50_ms"] for r in apps[:MAX_LISTED]},
        },
        evidence=evidence,
        recommendation=(
            "Check whether the app animates or redraws while idle (for example "
            "a live view that refreshes constantly); update it or report it to "
            "its developer."
        ),
        followups=[
            (
                "With the app idle on screen, run "
                + _adb_ro(
                    f"gfxinfo_{_slug(first)}",
                    f"dumpsys gfxinfo {first}",
                    "grep 'Total frames rendered'",
                )
                + "; repeat a minute later under a second key. A rising count "
                "means the app redraws while idle"
            ),
        ],
    )


def _animation_note(ctx: Context) -> str | None:
    settings = load_settings(ctx)
    if settings is None:
        return None
    scales = [_setting(settings, k, "global") for k in ANIMATION_KEYS]
    if any(s is not None and _float_or_none(s) == 0 for s in scales):
        return (
            "Animation scales are set to 0: animations are skipped, so frame "
            "counts are lower and jank percentages are not comparable with "
            "phones that animate."
        )
    return None


@analyzer("frame_jank", requires=("graphicsstats",))
def frame_jank(ctx: Context) -> Result:
    """Rank apps by janky frames in the daily graphicsstats buckets."""
    text, blocks, skipped = load_graphicsstats(ctx)
    if text is None:
        msg = "no graphicsstats dump"
        raise SkipError(msg)
    if not blocks:
        msg = "graphicsstats has no package blocks"
        raise SkipError(msg)
    result = Result("frame_jank", window="daily")
    _note_skipped(result, text, skipped)
    by_package: dict[str, list[GfxBlock]] = {}
    for block in blocks:
        by_package.setdefault(block.package, []).append(block)
    roles = key_packages(ctx)
    rows = sorted(
        (_app_row(p, bs, _role(p, roles)) for p, bs in by_package.items()),
        key=_jank_rank,
        reverse=True,
    )
    janky = [
        r
        for r in rows
        if r["frames"] >= MIN_FRAMES and r["janky_pct"] >= JANKY_PCT_FLAG
    ]
    slow = sorted(
        (
            r
            for r in rows
            if r not in janky
            and r["frames"] >= MIN_FRAMES
            and (r["p50_ms"] or 0) >= MEDIAN_FRAME_FLAG_MS
        ),
        key=lambda r: -r["frames"],
    )
    result.metrics = {
        "buckets": len(blocks),
        "packages": len(by_package),
        "first_day_utc": min((b.day_utc for b in blocks if b.day_utc), default=None),
        "last_day_utc": max((b.day_utc for b in blocks if b.day_utc), default=None),
        "packages_over_janky_threshold": len(janky),
    }
    for row in rows:
        if row["role"]:
            result.metrics[f"janky_pct_{_slug(row['package'])}"] = row["janky_pct"]
    result.add_table("per_package", rows)
    if janky:
        result.findings.append(_janky_finding(janky, by_package, text))
    if slow:
        result.findings.append(_slow_frames_finding(slow, by_package, text))
    flagged = [r["package"] for r in janky + slow]
    ranked = [r["package"] for r in rows if r["package"] not in flagged]
    worst = (flagged + ranked)[:BUCKET_TABLE_APPS]
    buckets = [
        {
            "package": b.package,
            "day_utc": b.day_utc,
            "frames": b.frames,
            "janky_pct": _round(b.janky_pct),
            "p50_ms": b.percentiles.get(50),
            "p95_ms": b.percentiles.get(95),
            "p99_ms": b.percentiles.get(99),
            "gpu_p95_ms": b.gpu_percentiles.get(95),
            "slow_ui_thread": b.counters.get("slow_ui_thread", 0),
            "ref": text.ref(b.index),
        }
        for package in worst
        for b in sorted(by_package[package], key=lambda b: -(b.since_ms or 0))
    ]
    result.add_table("daily_buckets", buckets)
    if note := _animation_note(ctx):
        result.notes.append(note)
    result.notes.append(
        "Buckets are UTC days and restart at boot; percentiles across buckets "
        "come from the summed frame-time histograms.",
    )
    return result


# --------------------------------------------------------------------------
# app_launch_times
# --------------------------------------------------------------------------

# Android vitals call launches excessive at these times to first frame.
COLD_LAUNCH_SLOW_MS = 5000
WARM_LAUNCH_SLOW_MS = 2000
HOT_LAUNCH_SLOW_MS = 1500
# A process start this close before a launch belongs to that launch.
COLD_PAIR_SLACK = timedelta(seconds=2)
# ActivityManager logs every startProcess step over 50 ms; 200 ms per start
# means process forks are queueing behind CPU or memory pressure.
SLOW_PROCESS_START_MS = 200
# Steps of one process start are logged within milliseconds of each other.
SLOW_START_GAP = timedelta(seconds=1)
# start-info first-frame deltas above this are clock artefacts, not launches.
START_INFO_MAX_TTFF_NS = 60 * 10**9
NS_PER_MS = 1_000_000
# A share of slow launches above this makes the start-info finding medium.
SLOW_LAUNCH_SHARE_PCT = 10.0
_LAUNCH_THRESHOLDS = {
    "cold": COLD_LAUNCH_SLOW_MS,
    "warm_or_hot": WARM_LAUNCH_SLOW_MS,
    "unknown": COLD_LAUNCH_SLOW_MS,
    "COLD": COLD_LAUNCH_SLOW_MS,
    "WARM": WARM_LAUNCH_SLOW_MS,
    "HOT": HOT_LAUNCH_SLOW_MS,
}
_ACTIVITY_REASONS = {"LAUNCHER", "LAUNCHER_RECENTS", "START_ACTIVITY"}

_LAUNCH_EVENT_RE = re.compile(r"^\[\d+,\d+,([^,\]]+),(\d+)")
_PROC_START_RE = re.compile(r"^\[\d+,\d+,\d+,([^,]*),([^,]*),")
_DISPLAYED_RE = re.compile(r"^Displayed (\S+?)(?: for user \d+)?: \+((?:\d+s)?\d+ms)")
_FULLY_DRAWN_RE = re.compile(
    r"^Fully drawn (\S+?)(?: for user \d+)?: \+((?:\d+s)?\d+ms)",
)
_SLOW_START_RE = re.compile(r"^Slow operation: (\d+)ms so far, now at startProcess")


@dataclass
class Launch:
    """One activity launch with its duration to first frame."""

    ts: datetime
    component: str
    ms: int
    source: str
    evidence: Evidence
    start_type: str = "unknown"

    @property
    def package(self) -> str:
        """The package part of the component."""
        return self.component.split("/", 1)[0]


@dataclass
class LaunchLogs:
    """Launch-related lines found in the event and system logs."""

    launches: list[Launch] = field(default_factory=list)
    proc_starts: dict[str, list[datetime]] = field(default_factory=dict)
    fully_drawn: list[Launch] = field(default_factory=list)
    slow_starts: list[dict[str, Any]] = field(default_factory=list)
    slow_lines: int = 0
    coverage: tuple[datetime, datetime] | None = None


def _parse_event_launches(ctx: Context, logs: LaunchLogs) -> None:
    tags = ("wm_activity_launch_time", "am_activity_launch_time", "am_proc_start")
    text, found = _events(ctx, tags)
    if text is None:
        return
    for i, entry in found:
        if entry.tag == "am_proc_start":
            m = _PROC_START_RE.match(entry.message)
            if m and "activity" in m[2]:
                package = m[1].split(":", 1)[0]
                logs.proc_starts.setdefault(package, []).append(entry.ts)
        elif m := _LAUNCH_EVENT_RE.match(entry.message):
            logs.launches.append(
                Launch(entry.ts, m[1], int(m[2]), "events", text.evidence(i)),
            )


def _add_slow_step(
    logs: LaunchLogs,
    open_starts: dict[int, dict[str, Any]],
    entry: LogLine,
    ms: int,
    evidence: Evidence,
) -> None:
    """Group the per-step "Slow operation" lines of one process start.

    ActivityManager logs each startProcess step that is over 50 ms with the
    elapsed time so far, so one start yields rising values on one thread. A
    falling value or a pause starts a new process start.
    """
    group = open_starts.get(entry.tid)
    if (
        group is None
        or ms < group["last_ms"]
        or entry.ts - group["last_ts"] > SLOW_START_GAP
    ):
        group = {"time": entry.ts, "ms": ms, "evidence": evidence}
        logs.slow_starts.append(group)
        open_starts[entry.tid] = group
    elif ms > group["ms"]:
        group["ms"], group["evidence"] = ms, evidence
    group["last_ms"], group["last_ts"] = ms, entry.ts


def _parse_system_launches(ctx: Context, logs: LaunchLogs) -> None:
    needles = ("Displayed ", "Fully drawn ", "Slow operation: ")
    open_starts: dict[int, dict[str, Any]] = {}
    text, found = _system_log_lines(ctx, needles)
    if text is None:
        return
    for i, entry in found:
        message = entry.message
        if m := _SLOW_START_RE.match(message):
            logs.slow_lines += 1
            _add_slow_step(logs, open_starts, entry, int(m[1]), text.evidence(i))
        elif m := _DISPLAYED_RE.match(message) or _FULLY_DRAWN_RE.match(message):
            launch = Launch(
                entry.ts,
                m[1],
                parse_duration_ms(m[2]),
                "displayed" if message.startswith("Displayed") else "fully_drawn",
                text.evidence(i),
            )
            target = logs.launches if launch.source == "displayed" else logs.fully_drawn
            target.append(launch)


def _dedupe_launches(launches: list[Launch]) -> list[Launch]:
    """Drop ``Displayed`` lines that repeat an event-log launch."""
    events = [x for x in launches if x.source == "events"]
    kept = list(events)
    for launch in launches:
        if launch.source == "events":
            continue
        if not any(
            e.component == launch.component and abs(e.ts - launch.ts) <= COLD_PAIR_SLACK
            for e in events
        ):
            kept.append(launch)
    return sorted(kept, key=lambda x: x.ts)


def _classify_launch(launch: Launch, logs: LaunchLogs) -> str:
    begin = launch.ts - timedelta(milliseconds=launch.ms) - COLD_PAIR_SLACK
    starts = logs.proc_starts.get(launch.package, [])
    if any(begin <= t <= launch.ts for t in starts):
        return "cold"
    if logs.coverage and logs.coverage[0] <= begin:
        return "warm_or_hot"
    return "unknown"


def _launch_logs(ctx: Context) -> LaunchLogs:
    logs = LaunchLogs()
    _parse_event_launches(ctx, logs)
    if events := ctx.sources.get("logcat_events"):
        logs.coverage = log_span(events, ctx.windows.log_reference())
    _parse_system_launches(ctx, logs)
    logs.launches = _dedupe_launches(logs.launches)
    for launch in logs.launches:
        launch.start_type = _classify_launch(launch, logs)
    return logs


@dataclass
class StartInfo:
    """Summary of ``dumpsys activity start-info`` records."""

    records: int = 0
    histogram: dict[str, int] = field(default_factory=dict)
    launches: list[dict[str, Any]] = field(default_factory=list)


_SI_PACKAGE_RE = re.compile(r"^\s*package: (\S+)")
# Reasons may contain spaces ("START ACTIVITY", "CONTENT PROVIDER").
_SI_RECORD_RE = re.compile(r"process=(\S+) .*?reason=(.+?) startType=(\S+)")
_SI_TIMESTAMPS_RE = re.compile(r"^\s*timestamps: (.*)")
_SI_PAIR_RE = re.compile(r"(\d+)=(\d+)")
_SI_LAUNCH = 0
_SI_FIRST_FRAME = 4


def parse_start_info(text: Text) -> StartInfo:
    """Count start reasons and types; time launches from launch to first frame."""
    info = StartInfo()
    package = ""
    pending: tuple[str, str, int] | None = None
    for i, line in enumerate(text.lines):
        if m := _SI_PACKAGE_RE.match(line):
            package = m[1]
        elif m := _SI_RECORD_RE.search(line):
            info.records += 1
            reason = m[2].strip().replace(" ", "_")
            key = f"{reason}/{m[3]}"
            info.histogram[key] = info.histogram.get(key, 0) + 1
            pending = (reason, m[3], i) if reason in _ACTIVITY_REASONS else None
        elif pending and (m := _SI_TIMESTAMPS_RE.match(line)):
            stamps = {int(k): int(v) for k, v in _SI_PAIR_RE.findall(m[1])}
            delta = stamps.get(_SI_FIRST_FRAME, 0) - stamps.get(_SI_LAUNCH, 0)
            if _SI_LAUNCH in stamps and 0 < delta < START_INFO_MAX_TTFF_NS:
                info.launches.append(
                    {
                        "package": package,
                        "reason": pending[0],
                        "start_type": pending[1],
                        "ms": round(delta / NS_PER_MS),
                        "ref": text.ref(pending[2]),
                    },
                )
            pending = None
    return info


def _start_info_summary(info: StartInfo, result: Result) -> list[dict[str, Any]]:
    """Add start-info metrics; return the launches over the vitals thresholds."""
    result.metrics["start_info_records"] = info.records
    result.metrics["start_info_timed_launches"] = len(info.launches)
    for start_type in ("COLD", "WARM", "HOT"):
        times = [x["ms"] for x in info.launches if x["start_type"] == start_type]
        if times:
            result.metrics[f"start_info_{start_type.lower()}_launches"] = len(times)
            result.metrics[f"start_info_{start_type.lower()}_median_ms"] = round(
                statistics.median(times),
            )
            result.metrics[f"start_info_{start_type.lower()}_max_ms"] = max(times)
    hist = sorted(info.histogram.items(), key=lambda kv: -kv[1])
    result.add_table(
        "start_info_reasons",
        [{"reason_type": k, "records": v} for k, v in hist],
    )
    slow = [
        x
        for x in info.launches
        if x["ms"] >= _LAUNCH_THRESHOLDS.get(x["start_type"], COLD_LAUNCH_SLOW_MS)
    ]
    slow.sort(key=lambda x: -x["ms"])
    result.add_table("start_info_slow_launches", slow)
    return slow


def _launch_finding(slow: list[Launch]) -> Finding:
    worst = slow[:3]
    listed = "; ".join(
        f"{x.package} {x.ms:,} ms ({x.start_type.replace('_', ' ')})" for x in worst
    )
    return Finding(
        id="app_launch_times.slow_launches",
        title=f"{len(slow)} slow app launches in the log window",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{len(slow)} launches took longer than the Android vitals limits "
            f"(cold {COLD_LAUNCH_SLOW_MS:,} ms, warm {WARM_LAUNCH_SLOW_MS:,} ms): "
            f"{listed}. Cold means a new process was started for the launch."
        ),
        metrics={"slow_launches": len(slow), "max_ms": max(x.ms for x in slow)},
        evidence=[x.evidence for x in worst],
        recommendation=(
            "Repeated cold starts of apps you use often mean they are killed "
            "in the background; check the memory findings (low-memory kills) "
            "and whether Battery Saver was on (its default policy turns off "
            "the launch boost)."
        ),
        followups=[
            (
                "Open the same app a few times with Battery Saver on, then off; "
                "after each round run "
                + _adb_ro(
                    "events_launches",
                    "logcat -b events -d",
                    "grep wm_activity_launch_time",
                )
            ),
        ],
    )


def _slow_start_finding(groups: list[dict[str, Any]], lines: int) -> Finding:
    worst = max(groups, key=itemgetter("ms"))
    return Finding(
        id="app_launch_times.slow_process_starts",
        title=f"{len(groups)} process starts took over {SLOW_PROCESS_START_MS} ms",
        symptom="slowness",
        severity="low",
        basis="measured",
        window="log_coverage",
        summary=(
            f"ActivityManager logged {len(groups)} process starts that took "
            f"over {SLOW_PROCESS_START_MS} ms inside system_server (max "
            f"{worst['ms']} ms; {lines} 'Slow operation' lines). Every app start "
            "waits for this step, so bursts of starts make launches and the "
            "UI lag."
        ),
        metrics={"slow_process_starts": len(groups), "max_ms": worst["ms"]},
        evidence=[g["evidence"] for g in sorted(groups, key=lambda g: -g["ms"])[:3]],
        recommendation=(
            "Slow process starts usually come from CPU or memory pressure at that "
            "moment, often a burst of background job starts after unlock or "
            "plug-in. Restrict background activity of apps you do not need "
            "(Settings > Apps > app > App battery usage > Restricted)."
        ),
        followups=[
            (
                "Check whether the slow starts cluster at screen-on or plug-in "
                "times (am_proc_start bursts in the event log)"
            ),
        ],
    )


def _start_info_finding(slow: list[dict[str, Any]], timed: int) -> Finding:
    share = PERCENT * len(slow) / timed if timed else 0.0
    listed = "; ".join(
        f"{x['package']} {x['ms']:,} ms ({x['start_type'].lower()})" for x in slow[:3]
    )
    return Finding(
        id="app_launch_times.start_info_slow",
        title=f"{len(slow)} of {timed} recorded app launches were slow",
        symptom="slowness",
        severity="medium" if share >= SLOW_LAUNCH_SHARE_PCT else "low",
        basis="measured",
        window="snapshot",
        summary=(
            f"In the start-info history ({timed} launches with a first-frame "
            f"time; records persist across reboots), {len(slow)} ({share:.0f}%) "
            f"exceeded the Android vitals limits: {listed}."
        ),
        metrics={"slow_launches": len(slow), "timed_launches": timed},
        evidence=[
            Evidence(x["ref"], f"{x['package']} {x['start_type']}") for x in slow[:3]
        ],
        recommendation=(
            "Check whether the slow launches are cold starts of apps that keep "
            "getting killed (memory findings) and whether Battery Saver was on."
        ),
        followups=["Repeat the launch with the phone idle and compare times"],
    )


def _launch_metrics(result: Result, logs: LaunchLogs) -> None:
    times = [x.ms for x in logs.launches]
    result.metrics.update(
        {
            "launches_logged": len(logs.launches),
            "cold_launches": sum(1 for x in logs.launches if x.start_type == "cold"),
            "launch_ms_median": round(statistics.median(times)) if times else None,
            "launch_ms_max": max(times) if times else None,
            "fully_drawn_lines": len(logs.fully_drawn),
            "slow_operation_lines": logs.slow_lines,
            "slow_process_starts": len(logs.slow_starts),
            "slow_process_start_max_ms": max(
                (g["ms"] for g in logs.slow_starts),
                default=None,
            ),
        },
    )
    if logs.coverage:
        start, end = logs.coverage
        result.metrics["events_log_start"] = start.isoformat(sep=" ")
        result.metrics["events_log_end"] = end.isoformat(sep=" ")
        result.metrics["events_log_minutes"] = round(
            (end - start).total_seconds() / 60, 1
        )


@analyzer("app_launch_times")
def app_launch_times(ctx: Context) -> Result:
    """Time app launches from the logs and from start-info."""
    has_logs = ctx.sources.has("logcat_events") or ctx.sources.has("logcat_system")
    start_info = ctx.sources.get("start_info")
    if not has_logs and start_info is None:
        msg = "no event log, system log or start-info dump"
        raise SkipError(msg)
    result = Result("app_launch_times", window="log_coverage")
    logs = _launch_logs(ctx)
    _launch_metrics(result, logs)
    rows = [
        {
            "time": x.ts.isoformat(sep=" "),
            "component": x.component,
            "ms": x.ms,
            "start_type": x.start_type,
            "source": x.source,
            "ref": x.evidence.ref,
        }
        for x in sorted(logs.launches, key=lambda x: -x.ms)
    ]
    result.add_table("launches", rows)
    slow = [x for x in logs.launches if x.ms >= _LAUNCH_THRESHOLDS[x.start_type]]
    if slow:
        result.findings.append(_launch_finding(sorted(slow, key=lambda x: -x.ms)))
    big = [g for g in logs.slow_starts if g["ms"] >= SLOW_PROCESS_START_MS]
    if big:
        result.findings.append(_slow_start_finding(big, logs.slow_lines))
    if start_info:
        info = parse_start_info(start_info)
        slow_info = _start_info_summary(info, result)
        if slow_info:
            result.findings.append(_start_info_finding(slow_info, len(info.launches)))
    result.notes.append(
        "Log-based launches cover only the log buffer; Displayed lines sit in "
        "the fast-rotating main buffer, so the event log is preferred.",
    )
    return result


# --------------------------------------------------------------------------
# battery_saver_state
# --------------------------------------------------------------------------

# Saver on for most of the battery time means its policy shaped everything
# measured on battery (launch boost, standby, deferred jobs).
SAVER_MOSTLY_ON_PCT = 80.0
# Saver on for practically all battery time leaves no "off" baseline.
SAVER_ALWAYS_ON_PCT = 99.0
# Drain-stat rows shorter than this have meaningless mAh/h rates.
DRAIN_MIN_ROW_MINUTES = 5
# Clock slack when comparing saver ON/OFF times with plug events.
SAVER_TIME_SLACK = timedelta(minutes=2)
# Policy flags that change speed or background work, reported as metrics.
SAVER_POLICY_KEYS = (
    "disable_launch_boost",
    "force_all_apps_standby",
    "force_background_check",
    "enable_quick_doze",
    "disable_animation",
    "enable_datasaver",
    "enable_firewall",
    "defer_full_backup",
    "location_mode",
    "disable_optional_sensors",
    "adjust_brightness_factor",
)
# AOSP BatterySaverController REASON_* codes seen in battery_saver_mode events.
SAVER_REASONS = {
    0: "percentage on",
    1: "percentage off",
    2: "manual on",
    3: "manual off",
    4: "sticky restore",
    5: "interactive changed",
    6: "policy changed",
    7: "plugged in",
    8: "setting changed",
}

_SAVER_STATE_RE = re.compile(r"Battery Saver is currently: (ON|OFF)")
_SAVER_TIME_RE = re.compile(
    r"Last (ON|OFF) time: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)",
)
_SAVER_TIMES_RE = re.compile(r"Times (full|adaptive) enabled: (\d+)")
_SAVER_POLICY_RE = re.compile(r"^\s*Policy '([^']+)'")
_SAVER_KV_RE = re.compile(r"^\s+(\w+)=(\S*)\s*$")
_SAVER_FIELD_RE = re.compile(
    r"^\s*(mSettingBatterySaverEnabledSticky|"
    r"mSettingBatterySaverStickyAutoDisableEnabled|"
    r"mSettingBatterySaverStickyAutoDisableThreshold|mSettingAutomaticBatterySaver|"
    r"mSettingBatterySaverTriggerThreshold|mLastChangedStrReason)=(.*)$",
)
_DRAIN_ROW_RE = re.compile(
    r"^\s*(?:(NonDoze|Deep|Light)\s+)?(NonIntr|Intr):\s+"
    r"(\d+)m\s+(\d+)mAh\(\s*(\d+)%\)\s+([\d.,]+)mAh/h\s+"
    r"(\d+)m\s+(\d+)mAh\(\s*(\d+)%\)\s+([\d.,]+)mAh/h",
)
_POWER_SAVE_PCT_RE = re.compile(r"\(([\d.,]+)%\)")
_SAVER_EVENT_RE = re.compile(r"^\[(\d),(\d),(\d),(\d),(\d),[^,]*,(\d+)\]")
_SAVER_SETTINGS = (
    "low_power",
    "low_power_sticky",
    "low_power_sticky_auto_disable_enabled",
    "low_power_sticky_auto_disable_level",
    "low_power_manual_activation_count",
    "automatic_power_save_mode",
    "low_power_trigger_level",
)


@dataclass
class SaverDump:
    """The Battery Saver parts of ``dumpsys power``."""

    text: Text
    state: str | None = None
    last_on: datetime | None = None
    last_off: datetime | None = None
    times_enabled: dict[str, int] = field(default_factory=dict)
    policies: dict[str, dict[str, str]] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)
    drain: list[dict[str, Any]] = field(default_factory=list)
    refs: dict[str, int] = field(default_factory=dict)


def _drain_row(m: re.Match[str], doze: str) -> dict[str, Any]:
    row: dict[str, Any] = {"doze": doze, "interactive": m[2] == "Intr"}
    for prefix, start in (("saver_off", 3), ("saver_on", 7)):
        minutes = int(m[start])
        row[f"{prefix}_min"] = minutes
        row[f"{prefix}_mah"] = int(m[start + 1])
        row[f"{prefix}_pct"] = int(m[start + 2])
        rate = _float_or_none(m[start + 3])
        row[f"{prefix}_mah_per_h"] = rate if minutes >= DRAIN_MIN_ROW_MINUTES else None
    return row


def _parse_saver_line(
    dump: SaverDump, line: str, i: int, policy: str | None
) -> str | None:
    """Parse one ``dumpsys power`` line; return the policy block now open."""
    if m := _SAVER_POLICY_RE.match(line):
        dump.policies[m[1]] = {}
        dump.refs[f"policy {m[1]}"] = i
        return m[1]
    if policy and (m := _SAVER_KV_RE.match(line)):
        dump.policies[policy][m[1]] = m[2]
        dump.refs.setdefault(f"{policy}:{m[1]}", i)
        return policy
    if m := _SAVER_STATE_RE.search(line):
        dump.state = m[1]
        dump.refs["state"] = i
    elif m := _SAVER_TIME_RE.search(line):
        stamp = _strptime(m[2], "%Y-%m-%d %H:%M:%S")
        setattr(dump, f"last_{m[1].lower()}", stamp)
        dump.refs[f"last_{m[1].lower()}"] = i
    elif m := _SAVER_TIMES_RE.search(line):
        dump.times_enabled[m[1]] = int(m[2])
        dump.refs[f"times_{m[1]}"] = i
    elif m := _SAVER_FIELD_RE.match(line):
        dump.fields[m[1]] = m[2].strip()
        dump.refs[m[1]] = i
    return None


def parse_power_saver(text: Text) -> SaverDump:
    """Parse saver state, times, policies, state machine and drain stats."""
    dump = SaverDump(text)
    policy: str | None = None
    doze = ""
    for i, line in enumerate(text.lines):
        if m := _DRAIN_ROW_RE.match(line):
            doze = m[1] or doze
            dump.drain.append(_drain_row(m, doze))
            dump.refs.setdefault("drain", i)
            continue
        if not line.strip():
            policy = None
            continue
        policy = _parse_saver_line(dump, line, i, policy)
    return dump


def _active_policy(dump: SaverDump) -> tuple[str, dict[str, str]]:
    for name in ("current full", "default full", "effective"):
        if name in dump.policies:
            return name, dump.policies[name]
    return "", {}


def _power_save_pct(ctx: Context) -> tuple[float, Evidence] | None:
    """Return the on-battery share with Battery Saver on, from batterystats."""
    since = load_since_charge(ctx)
    found = since.header("Power save mode enabled") if since else None
    m = _POWER_SAVE_PCT_RE.search(found[0]) if found else None
    if since is None or found is None or m is None:
        return None
    pct = _float_or_none(m[1])
    return None if pct is None else (pct, since.text.evidence(found[1]))


def _inferred_coverage(ctx: Context, dump: SaverDump) -> float | None:
    """Infer 100% coverage when saver went on at unplug and off at plug-in."""
    start = ctx.windows.since_charge_start
    if start is None or dump.last_on is None:
        return None
    on_at_unplug = dump.last_on <= start + SAVER_TIME_SLACK
    still_on = dump.state == "ON"
    off_at_plug = (
        dump.last_off is not None
        and ctx.windows.plugged_at is not None
        and dump.last_off >= ctx.windows.plugged_at - SAVER_TIME_SLACK
    )
    return PERCENT if on_at_unplug and (still_on or off_at_plug) else None


def _saver_events(ctx: Context) -> dict[str, Any]:
    text, found = _events(ctx, ("battery_saver_mode",))
    if text is None:
        return {}
    counts: dict[str, int] = {}
    turned_on = turned_off = 0
    for _, entry in found:
        m = _SAVER_EVENT_RE.match(entry.message)
        if not m:
            continue
        before, after = m[1] == "1", m[3] == "1"
        turned_on += not before and after
        turned_off += before and not after
        reason = _slug(SAVER_REASONS.get(int(m[6]), f"reason {m[6]}"))
        counts[f"log_saver_events_{reason}"] = (
            counts.get(f"log_saver_events_{reason}", 0) + 1
        )
    return {
        "log_saver_turned_on": turned_on,
        "log_saver_turned_off": turned_off,
        **counts,
    }


def _saver_settings_metrics(settings: Settings | None) -> dict[str, Any]:
    if settings is None:
        return {}
    metrics: dict[str, Any] = {}
    for key in _SAVER_SETTINGS:
        value = _setting(settings, key)
        metrics[f"setting_{key}"] = value
    return metrics


def _saver_finding(
    pct: float,
    basis: Basis,
    evidence: list[Evidence],
    metrics: dict[str, Any],
) -> Finding:
    sticky = metrics.get("setting_low_power_sticky") == "1" or (
        metrics.get("sticky") == "true"
    )
    auto_off = metrics.get("setting_low_power_sticky_auto_disable_enabled")
    count = metrics.get("setting_low_power_manual_activation_count")
    flags = [k for k in SAVER_POLICY_KEYS[:4] if metrics.get(f"policy_{k}") == "true"]
    summary = (
        f"Battery Saver was on for {pct:.0f}% of the time on battery since the "
        "last full charge."
    )
    if sticky:
        summary += " It is sticky (turns itself back on after unplugging)"
        summary += " with auto-disable off." if auto_off == "0" else "."
    if count:
        summary += f" It has been switched on by hand {count} times."
    if flags:
        summary += f" Its policy sets {', '.join(flags)}."
        summary += (
            " Per AOSP, disable_launch_boost suppresses the Power HAL launch "
            "boost, so app starts run without it (inferred; the vendor power "
            "HAL may differ)."
        )
    if pct >= SAVER_ALWAYS_ON_PCT:
        summary += (
            " Because it was never off on battery, this data cannot show what it saves."
        )
    return Finding(
        id="battery_saver_state.mostly_on",
        title=f"Battery Saver on for {pct:.0f}% of battery time",
        symptom="slowness",
        severity="medium",
        basis=basis,
        window="on_battery",
        summary=summary,
        metrics={
            "saver_on_battery_pct": pct,
            **{k: metrics[k] for k in metrics if k.startswith("policy_disable")},
        },
        evidence=evidence,
        recommendation=(
            "Settings > Battery > Battery Saver: instead of keeping it on all "
            "the time, use 'Set a schedule' (based on percentage) and 'Turn "
            "off when charged', then compare app launch speed and drain over a "
            "day each. Expect some idle drain increase with it off; background "
            "work it deferred also runs in a burst when it switches off."
        ),
        followups=[
            (
                "Measure launches (wm_activity_launch_time in the event log) with "
                "Battery Saver on and off"
            ),
            (
                "Unplugged with Battery Saver on, run "
                + _adb_ro("cpufreq_saver", _CPUFREQ_MAX_COMMAND, "grep max_freq")
                + ": a scaling_max_freq below cpuinfo_max_freq means the vendor "
                "power HAL caps CPU frequency"
            ),
            "Compare screen-off drain over two nights with it on and off",
        ],
    )


def _saver_metrics(dump: SaverDump | None, result: Result) -> list[Evidence]:
    """Fill metrics from ``dumpsys power``; return evidence for the finding."""
    if dump is None:
        return []
    name, policy = _active_policy(dump)
    result.metrics.update(
        {
            "saver_state_at_capture": dump.state,
            "saver_last_on": dump.last_on.isoformat(sep=" ") if dump.last_on else None,
            "saver_last_off": dump.last_off.isoformat(sep=" ")
            if dump.last_off
            else None,
            "saver_times_full_enabled_since_boot": dump.times_enabled.get("full"),
            "saver_times_adaptive_enabled_since_boot": dump.times_enabled.get(
                "adaptive"
            ),
            "sticky": dump.fields.get("mSettingBatterySaverEnabledSticky"),
            "sticky_auto_disable": dump.fields.get(
                "mSettingBatterySaverStickyAutoDisableEnabled",
            ),
            "last_change_reason": dump.fields.get("mLastChangedStrReason"),
            "active_policy": name,
        },
    )
    for key in SAVER_POLICY_KEYS:
        if key in policy:
            result.metrics[f"policy_{key}"] = policy[key]
    result.add_table("policy", [{"key": k, "value": v} for k, v in policy.items()])
    refs = [
        "last_on",
        "last_off",
        f"{name}:disable_launch_boost",
        "mSettingBatterySaverEnabledSticky",
    ]
    return [dump.text.evidence(dump.refs[r]) for r in refs if r in dump.refs]


def _drain_metrics(dump: SaverDump | None, result: Result) -> None:
    if dump is None or not dump.drain:
        return
    result.add_table("drain_stats_since_boot", dump.drain)
    on_min = sum(r["saver_on_min"] for r in dump.drain)
    off_min = sum(r["saver_off_min"] for r in dump.drain)
    result.metrics["drain_saver_on_min_since_boot"] = on_min
    result.metrics["drain_saver_off_min_since_boot"] = off_min
    if on_min + off_min:
        result.metrics["drain_saver_on_share_pct_since_boot"] = round(
            PERCENT * on_min / (on_min + off_min),
            1,
        )
    result.notes.append(
        "Drain stats cover all battery time since boot and mix days and "
        f"regimes; rates of rows under {DRAIN_MIN_ROW_MINUTES} min are omitted.",
    )


@analyzer("battery_saver_state")
def battery_saver_state(ctx: Context) -> Result:
    """Report how long Battery Saver was on, its policy and settings."""
    power = ctx.sources.get("power")
    settings = load_settings(ctx)
    if power is None and settings is None:
        msg = "no power dump and no settings"
        raise SkipError(msg)
    dump = parse_power_saver(power) if power else None
    result = Result("battery_saver_state", window="on_battery")
    evidence = _saver_metrics(dump, result)
    _drain_metrics(dump, result)
    result.metrics.update(_saver_settings_metrics(settings))
    result.metrics.update(_saver_events(ctx))
    if settings:
        evidence += settings.evidence("low_power_sticky")
        evidence += settings.evidence("low_power_manual_activation_count")
    measured = _power_save_pct(ctx)
    pct: float | None = None
    basis: Basis = "measured"
    if measured:
        pct = measured[0]
        evidence.insert(0, measured[1])
    elif dump and (pct := _inferred_coverage(ctx, dump)) is not None:
        basis = "inferred"
    result.metrics["saver_on_battery_pct"] = pct
    if pct is not None and pct >= SAVER_MOSTLY_ON_PCT:
        result.findings.append(_saver_finding(pct, basis, evidence, result.metrics))
    if caveat := _charging_caveat(ctx):
        result.notes.append(caveat.strip())
    return result


# --------------------------------------------------------------------------
# settings_audit
# --------------------------------------------------------------------------

ANIMATION_KEYS = (
    "window_animation_scale",
    "transition_animation_scale",
    "animator_duration_scale",
)
# Screen timeouts above ten minutes keep the display on long after use.
LONG_SCREEN_TIMEOUT_MS = 600_000
# (namespace, key, AOSP default or None when the device decides, meaning)
AUDITED_SETTINGS: tuple[tuple[str, str, str | None, str], ...] = (
    ("global", "window_animation_scale", "1.0", "window animation speed factor"),
    ("global", "transition_animation_scale", "1.0", "transition animation factor"),
    ("global", "animator_duration_scale", "1.0", "animator duration factor"),
    ("global", "always_finish_activities", "0", "destroy activities on leave"),
    ("global", "wait_for_debugger", "0", "apps wait for a debugger"),
    ("global", "debug_app", None, "app selected for debugging"),
    ("global", "development_settings_enabled", "0", "developer options shown"),
    ("global", "adb_enabled", "0", "USB debugging"),
    ("global", "stay_on_while_plugged_in", "0", "screen stays on while charging"),
    ("system", "show_touches", "0", "touch points drawn"),
    ("system", "pointer_location", "0", "pointer location overlay"),
    ("global", "disable_window_blurs", "0", "window blurs disabled"),
    ("system", "screen_off_timeout", None, "screen timeout (ms)"),
    ("global", "wifi_scan_always_enabled", None, "Wi-Fi scans while Wi-Fi is off"),
    ("global", "ble_scan_always_enabled", None, "Bluetooth scans while it is off"),
    ("secure", "location_mode", None, "location mode (0 off, 3 on)"),
    ("global", "mobile_data_always_on", "1", "mobile data kept up on Wi-Fi"),
    ("global", "adaptive_battery_management_enabled", "1", "Adaptive Battery"),
    ("global", "app_standby_enabled", "1", "app standby buckets"),
    ("global", "cached_apps_freezer", "device_default", "cached-app freezer"),
    ("global", "low_power", "0", "Battery Saver on now"),
    ("global", "low_power_sticky", "0", "Battery Saver re-enabled after unplug"),
    ("secure", "low_power_manual_activation_count", "0", "manual saver activations"),
    ("secure", "default_input_method", None, "keyboard"),
    ("secure", "tts_default_synth", None, "text-to-speech engine"),
)
# Values that mean a problem, with the verdict shown in the table.
FLAGGED_VALUES: dict[str, tuple[frozenset[str], str]] = {
    "always_finish_activities": (frozenset({"1"}), "forces cold starts"),
    "wait_for_debugger": (frozenset({"1"}), "apps pause at start"),
    "adaptive_battery_management_enabled": (frozenset({"0"}), "app standby off"),
    "app_standby_enabled": (frozenset({"0"}), "app standby off"),
    "cached_apps_freezer": (frozenset({"disabled"}), "freezer forced off"),
    "wifi_scan_always_enabled": (frozenset({"1"}), "background Wi-Fi scans"),
    "ble_scan_always_enabled": (frozenset({"1"}), "background BLE scans"),
}
COUNTED_LISTS = (
    "enabled_accessibility_services",
    "enabled_notification_listeners",
    "enabled_input_methods",
)


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return parse_decimal(value)
    except ValueError:
        return None


def _animation_verdict(value: str) -> str:
    scale = _float_or_none(value)
    if scale is not None and scale > 1:
        return "flag: slows every animation"
    return "note: animations off" if scale == 0 else "ok"


def _verdict(key: str, value: str | None, default: str | None) -> str:
    if value is None:
        return "absent (platform default)"
    if key in ANIMATION_KEYS:
        return _animation_verdict(value)
    if key in FLAGGED_VALUES and value in FLAGGED_VALUES[key][0]:
        return f"flag: {FLAGGED_VALUES[key][1]}"
    timeout = _float_or_none(value) if key == "screen_off_timeout" else None
    if timeout and timeout > LONG_SCREEN_TIMEOUT_MS:
        return "flag: screen stays on long"
    if default is not None and value != default:
        return "note: changed from default"
    return "ok"


def _list_count(value: str | None) -> int:
    if not value:
        return 0
    return len([x for x in value.split(":") if x.strip()])


# Per finding: the settings it covers, title, symptom, severity, summary and
# recommendation.
_SETTING_FINDINGS: dict[
    str, tuple[tuple[str, ...], str, Symptom, Severity, str, str]
] = {
    "animation": (
        ANIMATION_KEYS,
        "Animation scale above 1x slows the UI",
        "slowness",
        "medium",
        "An animation scale above 1 makes every transition take longer.",
        (
            "Settings > System > Developer options > Window/Transition/Animator "
            "animation scale: set them to 1x (or 0.5x)."
        ),
    ),
    "always_finish_activities": (
        ("always_finish_activities",),
        "'Don't keep activities' is on",
        "slowness",
        "high",
        (
            "Every activity is destroyed when the user leaves it, so each return "
            "to an app is a cold or warm start."
        ),
        "Settings > System > Developer options > Don't keep activities: off.",
    ),
    "wait_for_debugger": (
        ("wait_for_debugger",),
        "Apps wait for a debugger at start",
        "slowness",
        "low",
        "A debug app is set to wait for a debugger, which stalls its start.",
        "Settings > System > Developer options > Wait for debugger: off.",
    ),
    "standby": (
        ("adaptive_battery_management_enabled", "app_standby_enabled"),
        "Adaptive Battery or app standby is off",
        "battery",
        "medium",
        (
            "Without app standby buckets, rarely used apps keep running jobs and "
            "alarms as often as frequently used ones."
        ),
        "Settings > Battery > Adaptive Battery (or Adaptive preferences): on.",
    ),
    "freezer": (
        ("cached_apps_freezer",),
        "Cached-app freezer forced off",
        "both",
        "medium",
        (
            "The cached_apps_freezer setting disables freezing of cached apps, "
            "so they keep using CPU in the background."
        ),
        (
            "Settings > System > Developer options > Suspend execution for cached "
            "apps: Device default or Enabled."
        ),
    ),
    "scanning": (
        ("wifi_scan_always_enabled", "ble_scan_always_enabled"),
        "Wi-Fi or Bluetooth scanning stays on while the radio is off",
        "battery",
        "low",
        (
            "Location scanning lets apps scan Wi-Fi and/or Bluetooth for "
            "location even when the radio is switched off. It only matters while "
            "the radio is off, and the cost depends on how often apps ask for "
            "location (inferred, not measured here)."
        ),
        (
            "Settings > Location > Location services > Wi-Fi scanning / Bluetooth "
            "scanning: off, if location accuracy indoors is not needed."
        ),
    ),
    "screen_timeout": (
        ("screen_off_timeout",),
        "Long screen timeout",
        "battery",
        "low",
        (
            "The screen stays on long after the last touch, and the display is "
            "the largest consumer while on."
        ),
        "Settings > Display > Screen timeout: 30 s to 2 min.",
    ),
}


def _setting_finding(
    slug: str, settings: Settings, keys: list[str], values: str
) -> Finding:
    _, title, symptom, severity, summary, recommendation = _SETTING_FINDINGS[slug]
    evidence = [e for key in keys for e in settings.evidence(key)]
    return Finding(
        id=f"settings_audit.{slug}",
        title=title,
        symptom=symptom,
        severity=severity,
        basis="measured" if symptom == "slowness" else "inferred",
        window="snapshot",
        summary=f"{summary} Current values: {values}.",
        metrics={key: _setting(settings, key) for key in keys},
        evidence=evidence,
        recommendation=recommendation,
        followups=["Re-check the setting after the next OS update or restore"],
    )


def _flagged_keys(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    flagged = {r["key"] for r in rows if str(r["verdict"]).startswith("flag")}
    return {
        slug: [k for k in spec[0] if k in flagged]
        for slug, spec in _SETTING_FINDINGS.items()
        if flagged.intersection(spec[0])
    }


@analyzer("settings_audit", requires=("settings",))
def settings_audit(ctx: Context) -> Result:
    """Check settings and developer options that affect speed or drain."""
    settings = load_settings(ctx)
    if settings is None:
        msg = "no settings dump"
        raise SkipError(msg)
    result = Result("settings_audit", window="snapshot")
    # dumpsys settings also prints change history; only settings list lines
    # that fail to parse are worth a note.
    if settings.text.origin.startswith("live/"):
        _note_skipped(result, settings.text, settings.skipped)
    if not settings.namespaced:
        result.notes.append(
            "Settings namespaces are not marked; lookups search all of them.",
        )
    rows: list[dict[str, Any]] = []
    for namespace, key, default, meaning in AUDITED_SETTINGS:
        value = _setting(settings, key, namespace)
        rows.append(
            {
                "namespace": namespace,
                "key": key,
                "value": value,
                "default": default,
                "verdict": _verdict(key, value, default),
                "meaning": meaning,
            },
        )
        result.metrics[key] = value
    for key in COUNTED_LISTS:
        result.metrics[f"{key}_count"] = _list_count(_setting(settings, key, "secure"))
    rows.sort(
        key=lambda r: (
            not r["verdict"].startswith("flag"),
            not r["verdict"].startswith("note"),
        )
    )
    result.add_table("settings", rows)
    for slug, keys in _flagged_keys(rows).items():
        values = ", ".join(f"{k}={_setting(settings, k)}" for k in keys)
        result.findings.append(_setting_finding(slug, settings, keys, values))
    if any(
        _float_or_none(_setting(settings, k, "global")) == 0 for k in ANIMATION_KEYS
    ):
        result.notes.append(
            "Animation scales of 0 make the UI faster, not slower; they are "
            "not a slowness cause.",
        )
    return result


# --------------------------------------------------------------------------
# thermal_status
# --------------------------------------------------------------------------

THERMAL_STATUS = (
    "NONE",
    "LIGHT",
    "MODERATE",
    "SEVERE",
    "CRITICAL",
    "EMERGENCY",
    "SHUTDOWN",
)
# android.os.Temperature TYPE_* codes; 6-8 are battery-limit (BCL) readings
# such as volts, amps or percent, not temperatures.
SENSOR_TYPES = {
    0: "CPU",
    1: "GPU",
    2: "BATTERY",
    3: "SKIN",
    4: "USB_PORT",
    5: "POWER_AMPLIFIER",
    6: "BCL_VOLTAGE",
    7: "BCL_CURRENT",
    8: "BCL_PERCENTAGE",
    9: "NPU",
    10: "TPU",
    11: "DISPLAY",
    12: "MODEM",
    13: "SOC",
}
BCL_TYPES = frozenset({6, 7, 8})
# MODERATE and above: the platform and apps start limiting work.
THERMAL_FLAG_STATUS = 2
# SEVERE and above: noticeable throttling, jobs restricted.
THERMAL_SEVERE_STATUS = 3
# CRITICAL and above: the device is about to shut work down.
THERMAL_CRITICAL_STATUS = 4
# Thermal zones in millidegrees; outside this range the value is a sentinel
# (for example -273000) or not a temperature at all.
ZONE_MIN_MDEG = 1000
ZONE_MAX_MDEG = 150_000
ZONE_NOT_TEMPERATURE = re.compile(r"lvl|bcl|vph|ibat|vbat|^soc$|-step$", re.IGNORECASE)
ZONES_SHOWN = 10

_THERMAL_STATUS_RE = re.compile(r"^Thermal Status: (\d+)")
_THERMAL_OVERRIDE_RE = re.compile(r"^IsStatusOverride: (true|false)")
_TEMPERATURE_RE = re.compile(
    r"Temperature\{mValue=([^,]+), mType=(-?\d+), mName=([^,]+), mStatus=(\d+)\}",
)
_COOLING_RE = re.compile(r"CoolingDevice\{mValue=(\d+), mType=(\d+), mName=([^}]+)\}")
_THRESHOLD_RE = re.compile(
    r"TemperatureThreshold\{mType=(-?\d+), mName=([^,]+), "
    r"mHotThrottlingThresholds=\[([^\]]*)\]",
)
_THERMAL_SECTIONS = {
    "Cached temperatures:": "cached",
    "Current temperatures from HAL:": "current",
}
_JOB_THERMAL_RE = re.compile(r"^Thermal status: (\d+)")
_JOB_RESTRICTED_RE = re.compile(r"^\s*Restricted due to: ([\w ]+)\.")
_THERMAL_EVENT_RE = re.compile(r"^\[([^,]+),(-?\d+),([-\d.]+),(\d+)")
_CLAMPER_RE = re.compile(r"New thermal throttling status = (\d+)")
_CPUFREQ_RE = re.compile(r"/cpu(\d+)/cpufreq (\d+) (\d+) (\d+) (\d+)\s*$")
_ZONE_RE = re.compile(r"^(\S+) (-?\d+)\s*$")


@dataclass
class ThermalDump:
    """Parsed ``dumpsys thermalservice``."""

    text: Text
    status: int | None = None
    status_index: int | None = None
    override: bool = False
    sensors: list[dict[str, Any]] = field(default_factory=list)
    cooling: list[dict[str, Any]] = field(default_factory=list)
    thresholds: dict[str, dict[str, float]] = field(default_factory=dict)
    threshold_refs: dict[str, int] = field(default_factory=dict)


def _status_name(status: int) -> str:
    if 0 <= status < len(THERMAL_STATUS):
        return THERMAL_STATUS[status]
    return str(status)


def _hot_thresholds(raw: str) -> dict[str, float]:
    levels: dict[str, float] = {}
    for status, item in enumerate(raw.split(",")):
        value = _float_or_none(item.strip())
        if value is not None and not math.isnan(value) and status < len(THERMAL_STATUS):
            levels[THERMAL_STATUS[status]] = value
    return levels


def _parse_thermal_line(dump: ThermalDump, line: str, i: int, section: str) -> None:
    if m := _TEMPERATURE_RE.search(line):
        value = _float_or_none(m[1])
        kind = int(m[2])
        dump.sensors.append(
            {
                "source": section or "other",
                "name": m[3],
                "type": SENSOR_TYPES.get(kind, str(kind)),
                "value": value,
                "is_temperature": kind not in BCL_TYPES,
                "status": int(m[4]),
                "index": i,
            },
        )
    elif m := _COOLING_RE.search(line):
        dump.cooling.append({"name": m[3], "value": int(m[1]), "index": i})
    elif m := _THRESHOLD_RE.search(line):
        dump.thresholds[m[2]] = _hot_thresholds(m[3])
        dump.threshold_refs[m[2]] = i


def parse_thermalservice(text: Text) -> ThermalDump:
    """Parse status, temperatures, cooling devices and hot thresholds."""
    dump = ThermalDump(text)
    section = ""
    for i, line in enumerate(text.lines):
        stripped = line.strip()
        if m := _THERMAL_STATUS_RE.match(stripped):
            dump.status, dump.status_index = int(m[1]), i
        elif m := _THERMAL_OVERRIDE_RE.match(stripped):
            dump.override = m[1] == "true"
        elif stripped in _THERMAL_SECTIONS:
            section = _THERMAL_SECTIONS[stripped]
        elif stripped.endswith(":") and not stripped.startswith(
            ("Temperature", "Cooling")
        ):
            section = ""
        else:
            _parse_thermal_line(dump, line, i, section)
    return dump


def _jobs_thermal(ctx: Context) -> dict[str, Any]:
    text = ctx.sources.get("jobscheduler")
    if text is None:
        return {}
    reasons: dict[str, int] = {}
    status = None
    first: dict[str, int] = {}
    for i, line in enumerate(text.lines):
        if m := _JOB_RESTRICTED_RE.match(line):
            reasons[m[1]] = reasons.get(m[1], 0) + 1
            first.setdefault(m[1], i)
        elif status is None and (m := _JOB_THERMAL_RE.match(line)):
            status = int(m[1])
            first["status"] = i
    evidence = [text.evidence(first[k]) for k in ("status", "thermal") if k in first]
    return {
        "jobscheduler_thermal_status": status,
        "jobs_restricted_thermal": reasons.get("thermal", 0),
        "jobs_restricted_total": sum(reasons.values()),
        "reasons": reasons,
        "evidence": evidence,
    }


def _thermal_log_events(ctx: Context) -> tuple[list[dict[str, Any]], list[Evidence]]:
    events: list[dict[str, Any]] = []
    evidence: list[Evidence] = []
    for text, found in (
        _events(ctx, ("thermal_changed",)),
        _system_log_lines(ctx, ("BrightnessThermalClamper",)),
    ):
        if text is None:
            continue
        for i, entry in found:
            event = _thermal_event(entry)
            if event:
                event["ref"] = text.ref(i)
                events.append(event)
                if (
                    event["status"] >= THERMAL_FLAG_STATUS
                    and len(evidence) < MAX_LISTED
                ):
                    evidence.append(text.evidence(i))
    return events, evidence


def _thermal_event(entry: LogLine) -> dict[str, Any] | None:
    if entry.tag == "thermal_changed" and (m := _THERMAL_EVENT_RE.match(entry.message)):
        return {
            "time": entry.ts.isoformat(sep=" "),
            "sensor": m[1],
            "value": _float_or_none(m[3]),
            "status": int(m[4]),
        }
    if m := _CLAMPER_RE.search(entry.message):
        return {
            "time": entry.ts.isoformat(sep=" "),
            "sensor": "brightness clamper",
            "value": None,
            "status": int(m[1]),
        }
    return None


def _cpufreq_caps(ctx: Context) -> tuple[list[dict[str, Any]], Text | None]:
    text = ctx.sources.get("cpufreq")
    if text is None:
        return [], None
    rows = []
    for i, line in enumerate(text.lines):
        if m := _CPUFREQ_RE.search(line):
            cur, low, high, hw_max = (int(m[k]) for k in range(2, 6))
            rows.append(
                {
                    "cpu": int(m[1]),
                    "cur_khz": cur,
                    "min_khz": low,
                    "max_khz": high,
                    "hw_max_khz": hw_max,
                    "capped": high < hw_max,
                    "index": i,
                },
            )
    return rows, text


def _thermal_zones(ctx: Context) -> list[dict[str, Any]]:
    text = ctx.sources.get("thermal_zones")
    if text is None:
        return []
    zones: list[dict[str, Any]] = []
    for i, line in enumerate(text.lines):
        m = _ZONE_RE.match(line.strip())
        if not m or ZONE_NOT_TEMPERATURE.search(m[1]):
            continue
        value = int(m[2])
        if ZONE_MIN_MDEG <= value <= ZONE_MAX_MDEG:
            zones.append(
                {"zone": m[1], "celsius": value / MS_PER_S, "ref": text.ref(i)}
            )
    zones.sort(key=lambda z: -z["celsius"])
    return zones


def _hot_sensors(dump: ThermalDump) -> list[dict[str, Any]]:
    """Sensors at MODERATE or worse, with their trip point and hysteresis."""
    hot = []
    for sensor in dump.sensors:
        if sensor["status"] < THERMAL_FLAG_STATUS or not sensor["is_temperature"]:
            continue
        trip = dump.thresholds.get(sensor["name"], {}).get(
            _status_name(sensor["status"])
        )
        hot.append(
            {
                **sensor,
                "trip": trip,
                "below_trip": trip is not None
                and sensor["value"] is not None
                and sensor["value"] < trip,
            },
        )
    return hot


def _thermal_summary(
    dump: ThermalDump, hot: list[dict[str, Any]], jobs: dict[str, Any]
) -> str:
    status = dump.status or 0
    parts = [f"Thermal status was {_status_name(status)} ({status}) at capture."]
    for sensor in hot:
        trip = f" (trip {sensor['trip']} °C)" if sensor["trip"] is not None else ""
        parts.append(
            f"{sensor['source'].capitalize()} {sensor['name']} reading "
            f"{sensor['value']} °C has status {_status_name(sensor['status'])}{trip}.",
        )
    if any(s["below_trip"] for s in hot):
        parts.append(
            "A reading below its trip point still carries the status: the "
            "status lags (hysteresis or a stale cached value).",
        )
    if jobs.get("jobs_restricted_thermal"):
        parts.append(
            f"JobScheduler held back {jobs['jobs_restricted_thermal']} jobs for "
            "thermal reasons.",
        )
    active = [c for c in dump.cooling if c["value"] > 0]
    parts.append(f"{len(active)} of {len(dump.cooling)} cooling devices were active.")
    return " ".join(parts)


def _status_finding(
    ctx: Context, dump: ThermalDump, jobs: dict[str, Any], log_evidence: list[Evidence]
) -> Finding:
    status = dump.status or 0
    hot = _hot_sensors(dump)
    severity: Severity
    if status >= THERMAL_CRITICAL_STATUS:
        severity = "high"
    elif (
        status >= THERMAL_SEVERE_STATUS
        and ctx.windows.on_battery_at_capture is not False
    ):
        severity = "medium"
    else:
        severity = "low"
    evidence = [dump.text.evidence(dump.status_index or 0)]
    evidence += [dump.text.evidence(s["index"]) for s in hot[:3]]
    evidence += [
        dump.text.evidence(dump.threshold_refs[s["name"]])
        for s in hot[:1]
        if s["name"] in dump.threshold_refs
    ]
    evidence += jobs.get("evidence", []) + log_evidence
    return Finding(
        id="thermal_status.elevated",
        title=f"Thermal status {_status_name(status)}",
        symptom="slowness",
        severity=severity,
        basis="measured",
        window="snapshot",
        summary=_thermal_summary(dump, hot, jobs) + _charging_caveat(ctx),
        metrics={
            "thermal_status": status,
            "hot_sensors": [s["name"] for s in hot],
            "jobs_restricted_thermal": jobs.get("jobs_restricted_thermal"),
        },
        evidence=evidence,
        recommendation=(
            "Avoid heavy use while fast-charging, remove thick cases while "
            "charging, and keep the phone out of the sun. Trip points are set "
            "by the vendor; no user setting changes them."
        ),
        followups=[
            (
                "During normal use on battery, run "
                + _adb_ro(
                    "thermalservice_battery",
                    "dumpsys thermalservice",
                    "grep -E 'Thermal Status|mStatus=[1-9]'",
                )
                + " to see whether the status also rises without charging"
            ),
            (
                "Right after the activity that feels slow, run "
                + _adb_ro(
                    "events_thermal", "logcat -b events -d", "grep thermal_changed"
                )
            ),
        ],
    )


def _log_thermal_finding(
    events: list[dict[str, Any]], evidence: list[Evidence]
) -> Finding:
    worst = max(events, key=itemgetter("status"))
    return Finding(
        id="thermal_status.log_events",
        title=(
            f"Thermal status reached {_status_name(worst['status'])} in the log window"
        ),
        symptom="slowness",
        severity="low",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{len(events)} thermal status changes were logged; the worst was "
            f"{_status_name(worst['status'])} at {worst['time']} "
            f"({worst['sensor']}, {worst['value']} °C)."
        ),
        metrics={"events": len(events), "max_status": worst["status"]},
        evidence=evidence,
        recommendation=(
            "Note what the phone was doing at that time (charging, camera, games)."
        ),
        followups=[
            "During the slow period, run "
            + _adb_ro(
                "thermalservice_slow",
                "dumpsys thermalservice",
                "grep -E 'Thermal Status|mStatus=[1-9]'",
            ),
        ],
    )


def _cap_finding(caps: list[dict[str, Any]], text: Text, ctx: Context) -> Finding:
    capped = [c for c in caps if c["capped"]]
    listed = ", ".join(
        f"cpu{c['cpu']} {c['max_khz']}/{c['hw_max_khz']} kHz" for c in capped
    )
    return Finding(
        id="thermal_status.cpu_frequency_capped",
        title=f"{len(capped)} CPUs capped below their maximum frequency",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=(
            f"scaling_max_freq is below cpuinfo_max_freq on {listed}. A thermal "
            "or power-saving limit was active at capture." + _charging_caveat(ctx)
        ),
        metrics={"capped_cpus": [c["cpu"] for c in capped]},
        evidence=[text.evidence(c["index"]) for c in capped[:3]],
        recommendation=(
            "Repeat the reading with the phone cool and Battery Saver off; a "
            "persistent cap points to a vendor thermal or power policy."
        ),
        followups=[
            "Unplugged, with Battery Saver on and then off (a key for each), run "
            + _adb_ro("cpufreq_unplugged", _CPUFREQ_MAX_COMMAND, "grep max_freq"),
        ],
    )


def _thermal_metrics(
    result: Result, dump: ThermalDump | None, zones: list[dict[str, Any]]
) -> None:
    if dump:
        temps = [
            s for s in dump.sensors if s["is_temperature"] and s["value"] is not None
        ]
        result.metrics.update(
            {
                "thermal_status": dump.status,
                "thermal_status_name": _status_name(dump.status)
                if dump.status is not None
                else None,
                "status_override": dump.override,
                "cooling_devices": len(dump.cooling),
                "cooling_devices_active": sum(
                    1 for c in dump.cooling if c["value"] > 0
                ),
                "max_sensor_c": max((s["value"] for s in temps), default=None),
            },
        )
        for kind in ("SKIN", "CPU", "BATTERY"):
            values = [
                s["value"]
                for s in temps
                if s["type"] == kind and s["source"] == "current"
            ]
            if values:
                result.metrics[f"current_{kind.lower()}_max_c"] = max(values)
        rows = [
            {k: v for k, v in s.items() if k != "index"}
            | {
                "trip_points": dump.thresholds.get(s["name"], {}),
                "ref": dump.text.ref(s["index"]),
            }
            for s in sorted(
                dump.sensors, key=lambda s: (-s["status"], -(s["value"] or 0))
            )
        ]
        result.add_table("sensors", rows)
    if zones:
        result.metrics["hottest_zone"] = zones[0]["zone"]
        result.metrics["hottest_zone_c"] = zones[0]["celsius"]
        result.add_table("thermal_zones", zones, cap=ZONES_SHOWN)


@analyzer("thermal_status")
def thermal_status(ctx: Context) -> Result:
    """Report thermal status, hot sensors, restrictions and CPU caps."""
    text = ctx.sources.get("thermalservice")
    zones = _thermal_zones(ctx)
    if text is None and not zones:
        msg = "no thermalservice dump and no thermal zones"
        raise SkipError(msg)
    dump = parse_thermalservice(text) if text else None
    result = Result("thermal_status", window="snapshot")
    _thermal_metrics(result, dump, zones)
    jobs = _jobs_thermal(ctx)
    result.metrics.update(
        {k: v for k, v in jobs.items() if k not in {"evidence", "reasons"}},
    )
    reasons = sorted(jobs.get("reasons", {}).items(), key=lambda kv: -kv[1])
    result.add_table("job_restrictions", [{"reason": k, "jobs": n} for k, n in reasons])
    events, log_evidence = _thermal_log_events(ctx)
    result.metrics["thermal_log_events"] = len(events)
    result.add_table("log_events", events)
    if dump and (dump.status or 0) >= THERMAL_FLAG_STATUS:
        result.findings.append(_status_finding(ctx, dump, jobs, log_evidence))
    elif any(e["status"] >= THERMAL_FLAG_STATUS for e in events):
        result.findings.append(_log_thermal_finding(events, log_evidence))
    caps, cpufreq = _cpufreq_caps(ctx)
    result.metrics["cpus_capped"] = sum(1 for c in caps if c["capped"])
    result.tables["cpufreq"] = [
        {k: v for k, v in c.items() if k != "index"} for c in caps
    ]
    if cpufreq and any(c["capped"] for c in caps):
        result.findings.append(_cap_finding(caps, cpufreq, ctx))
    if caveat := _charging_caveat(ctx):
        result.notes.append(caveat.strip())
    result.notes.append(
        "BCL entries (types 6-8) are battery voltage, current or percent, not "
        "temperatures; they are listed but not compared with temperatures.",
    )
    return result


# --------------------------------------------------------------------------
# storage_io_per_uid
# --------------------------------------------------------------------------

# Since-boot rates need hours: in the first hour boot loads every library
# from flash, so its reads and fsyncs say nothing about everyday use.
MIN_RATE_UPTIME_S = 3600
# An app reading three times more from flash than it read() itself, at over
# 2 GiB per day, is re-faulting its own mapped code and resources.
APP_CHURN_RATIO = 3.0
APP_CHURN_GIB_PER_DAY = 2.0
# Without an uptime, an app needs this much in total to be flagged.
APP_CHURN_MIN_GIB = 2.0
# More than 10k fsync calls per day keep the flash and CPU awake.
FSYNC_PER_DAY_FLAG = 10_000
# Under 10% free space slows flash writes and blocks app optimisation.
DATA_FREE_PCT_FLAG = 10
# Write latency over 50 ms for a 512-byte write means struggling flash.
WRITE_LATENCY_MS_FLAG = 50

_STORAGED_HEADER_RE = re.compile(r"^name/uid\s+fg_rchar")
_STORAGED_PERF_PREFIXES = (
    "I/O perf history",
    "last 24 hours",
    "last 7 days",
    "last 52 weeks",
)
_STORAGED_FIELDS = 11
_INTERVAL_RE = re.compile(r"^(\d{9,11}),(\d{9,11})$")
_DISK_LATENCY_RE = re.compile(r"^Latency: (\d+)ms")
_DISK_SPEED_RE = re.compile(r"^Recent Disk Write Speed \(kB/s\) = (\d+)")
_DISK_FREE_RE = re.compile(r"^Data-Free: (\d+)K / (\d+)K total = (\d+)% free")
_DISK_ARRAYS = {
    "Package Names": "package",
    "App Sizes": "app_bytes",
    "App Data Sizes": "data_bytes",
    "Cache Sizes": "cache_bytes",
}


def _storaged_name(ctx: Context, name: str) -> str:
    return ctx.packages.name(int(name)) if name.isdigit() else name


def parse_storaged(ctx: Context, text: Text) -> tuple[list[dict[str, Any]], int]:
    """Parse the per-UID table of ``storaged -u -p``; return rows and skips."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    in_table = False
    for i, line in enumerate(text.lines):
        fields = line.split()
        if _STORAGED_HEADER_RE.match(line):
            in_table = True
        elif not in_table or not fields or line.startswith(_STORAGED_PERF_PREFIXES):
            continue
        elif len(fields) == _STORAGED_FIELDS and all(f.isdigit() for f in fields[1:]):
            n = [int(f) for f in fields[1:]]
            rows.append(
                {
                    "name": _storaged_name(ctx, fields[0]),
                    "rchar": n[0] + n[4],
                    "wchar": n[1] + n[5],
                    "rbytes": n[2] + n[6],
                    "wbytes": n[3] + n[7],
                    "bg_rbytes": n[6],
                    "fsync": n[8] + n[9],
                    "ref": text.ref(i),
                    "evidence": text.evidence(i),
                },
            )
        else:
            skipped += 1
    return rows, skipped


def _io_row(row: dict[str, Any], days: float | None) -> dict[str, Any]:
    ratio = row["rbytes"] / row["rchar"] if row["rchar"] else None
    out = {
        "name": row["name"],
        "read_gib": round(row["rbytes"] / GIB, 2),
        "read_call_gib": round(row["rchar"] / GIB, 2),
        "write_gib": round(row["wbytes"] / GIB, 2),
        "read_ratio": _round(ratio, 2),
        "fsync": row["fsync"],
        "bg_read_share_pct": _round(PERCENT * row["bg_rbytes"] / row["rbytes"])
        if row["rbytes"]
        else None,
        "ref": row["ref"],
    }
    if days:
        out["read_gib_per_day"] = round(row["rbytes"] / GIB / days, 2)
        out["fsync_per_day"] = round(row["fsync"] / days)
    return out


def _is_app(name: str) -> bool:
    return "." in name and not name.startswith("shared:android.")


def _churning(rows: list[dict[str, Any]], days: float | None) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if not _is_app(row["name"]) or (row["read_ratio"] or 0) < APP_CHURN_RATIO:
            continue
        per_day = bool(days) and row["read_gib_per_day"] >= APP_CHURN_GIB_PER_DAY
        total = not days and row["read_gib"] >= APP_CHURN_MIN_GIB
        if per_day or total:
            out.append(row)
    return out


def _churn_finding(apps: list[dict[str, Any]], cited: dict[str, Evidence]) -> Finding:
    listed = "; ".join(
        f"{a['name']} {a['read_gib']} GiB read vs {a['read_call_gib']} GiB requested"
        for a in apps[:MAX_LISTED]
    )
    return Finding(
        id="storage_io_per_uid.app_page_cache_churn",
        title=f"{len(apps)} apps re-read their files from flash",
        symptom="both",
        severity="medium",
        basis="measured",
        window="since_boot",
        summary=(
            f"These apps read at least {APP_CHURN_RATIO:.0f}x more from flash "
            f"than they requested and over {APP_CHURN_GIB_PER_DAY:.0f} GiB per day: "
            f"{listed}. Their mapped code and resources are being evicted and "
            "faulted back in, often because they are killed and restarted or "
            "run in the background under memory pressure (mechanism inferred)."
        ),
        metrics={"apps": [a["name"] for a in apps]},
        evidence=[cited[a["ref"]] for a in apps[:3]],
        recommendation=(
            "Restrict background activity for the listed apps you do not need "
            "running (Settings > Apps > app > App battery usage > Restricted), "
            "update them, or report the I/O to their developers."
        ),
        followups=["Check exit-info for repeated low-memory kills of the same apps"],
    )


def _fsync_finding(apps: list[dict[str, Any]], cited: dict[str, Evidence]) -> Finding:
    listed = "; ".join(
        f"{a['name']} {a['fsync_per_day']:,}/day" for a in apps[:MAX_LISTED]
    )
    return Finding(
        id="storage_io_per_uid.fsync_heavy",
        title=f"{len(apps)} apps call fsync over {FSYNC_PER_DAY_FLAG:,} times a day",
        symptom="battery",
        severity="low",
        basis="measured",
        window="since_boot",
        summary=(
            f"Frequent fsync calls force flash writes and keep the storage "
            f"awake: {listed}. The battery cost is not measured here."
        ),
        metrics={"apps": [a["name"] for a in apps]},
        evidence=[cited[a["ref"]] for a in apps[:3]],
        recommendation="Update the listed apps or restrict their background activity.",
        followups=["Compare the fsync counts after a day with the app restricted"],
    )


def _io_totals(raw: list[dict[str, Any]], uptime: float | None) -> dict[str, Any]:
    rbytes = sum(r["rbytes"] for r in raw)
    rchar = sum(r["rchar"] for r in raw)
    totals = {
        "uids": len(raw),
        "read_gib": round(rbytes / GIB, 1),
        "read_call_gib": round(rchar / GIB, 1),
        # Flash reads per byte apps asked for; well above 1 means page-cache
        # churn (vmstat_reclaim_io owns that finding).
        "read_ratio": _round(rbytes / rchar if rchar else None, 2),
        "write_gib": round(sum(r["wbytes"] for r in raw) / GIB, 1),
        "fsync": sum(r["fsync"] for r in raw),
        "read_mib_s": None,
    }
    if uptime:
        totals["read_mib_s"] = round(rbytes / MIB / uptime, 2)
    return totals


def _storaged_analysis(ctx: Context, text: Text, result: Result) -> None:
    raw, skipped = parse_storaged(ctx, text)
    _note_skipped(result, text, skipped)
    if not raw:
        result.notes.append(f"{text.origin} has no per-UID I/O rows.")
        return
    uptime = _uptime_s(ctx)
    short = uptime is not None and uptime < MIN_RATE_UPTIME_S
    if short:
        result.notes.append(
            f"Captured {uptime / 60:.0f} min after boot: boot reads dominate "
            "the counters, so rates are left out and no app is flagged.",
        )
        uptime = None
    days = uptime / SECONDS_PER_DAY if uptime else None
    totals = _io_totals(raw, uptime)
    result.metrics.update({f"total_{k}": v for k, v in totals.items()})
    rows = sorted((_io_row(r, days) for r in raw), key=lambda r: -r["read_gib"])
    result.add_table("per_uid", rows)
    if short:
        return
    cited = {r["ref"]: r["evidence"] for r in raw}
    churn = _churning(rows, days)
    if churn:
        result.findings.append(_churn_finding(churn, cited))
    if days:
        heavy = [
            r
            for r in rows
            if _is_app(r["name"]) and r["fsync_per_day"] >= FSYNC_PER_DAY_FLAG
        ]
        if heavy:
            heavy.sort(key=lambda r: -r["fsync_per_day"])
            result.findings.append(_fsync_finding(heavy, cited))
    else:
        result.notes.append("Boot time unknown: per-day rates were not computed.")


def _interval_summary(ctx: Context, text: Text, result: Result) -> None:
    """Report which boots the ``dumpsys storaged`` charger split covers."""
    ends = [int(m[2]) for _, m in text.find(_INTERVAL_RE)]
    if not ends:
        return
    last = _from_epoch(max(ends))
    if last is None:
        return
    result.metrics["storaged_intervals"] = len(ends)
    result.metrics["storaged_last_interval_end_utc"] = last.isoformat(sep=" ")
    boot, last_local = ctx.windows.boot_time, ctx.windows.local_from_epoch(max(ends))
    if boot and last_local:
        result.metrics["storaged_intervals_cover_this_boot"] = last_local > boot
    result.notes.append(
        "dumpsys storaged keeps per-boot intervals split by charger state; the "
        "last interval often ends at the previous boot, so it rarely describes "
        "the current one.",
    )


def _disk_arrays(text: Text) -> list[dict[str, Any]]:
    arrays: dict[str, list[Any]] = {}
    for line in text.lines:
        label, _, payload = line.partition(": ")
        if label in _DISK_ARRAYS and payload.startswith("["):
            try:
                arrays[_DISK_ARRAYS[label]] = json.loads(payload)
            except json.JSONDecodeError:
                continue
    names = arrays.get("package", [])
    rows = []
    for i, name in enumerate(names):
        row = {"package": name}
        for key in ("app_bytes", "data_bytes", "cache_bytes"):
            values = arrays.get(key, [])
            row[key] = values[i] if i < len(values) else None
        row["total_gib"] = round(
            sum(row[k] or 0 for k in ("app_bytes", "data_bytes", "cache_bytes")) / GIB,
            2,
        )
        rows.append(row)
    return sorted(rows, key=lambda r: -r["total_gib"])


def _diskstats(ctx: Context, result: Result) -> None:
    text = ctx.sources.get("diskstats")
    if text is None:
        return
    refs: dict[str, int] = {}
    for i, line in enumerate(text.lines):
        if m := _DISK_LATENCY_RE.match(line):
            result.metrics["write_latency_ms"] = int(m[1])
            refs["latency"] = i
        elif m := _DISK_SPEED_RE.match(line):
            result.metrics["recent_write_kb_per_s"] = int(m[1])
        elif m := _DISK_FREE_RE.match(line):
            result.metrics["data_free_gib"] = round(int(m[1]) * 1024 / GIB, 1)
            result.metrics["data_total_gib"] = round(int(m[2]) * 1024 / GIB, 1)
            result.metrics["data_free_pct"] = int(m[3])
            refs["free"] = i
    result.add_table("app_storage", _disk_arrays(text))
    free = result.metrics.get("data_free_pct")
    if free is not None and free < DATA_FREE_PCT_FLAG:
        result.findings.append(
            _disk_finding(
                "low_free_space", f"Only {free}% of /data is free", text, refs["free"]
            )
        )
    latency = result.metrics.get("write_latency_ms")
    if latency is not None and latency > WRITE_LATENCY_MS_FLAG:
        result.findings.append(
            _disk_finding(
                "slow_writes",
                f"Flash write latency {latency} ms",
                text,
                refs["latency"],
            )
        )


def _disk_finding(slug: str, title: str, text: Text, index: int) -> Finding:
    advice = {
        "low_free_space": (
            (
                "Low free space slows flash writes and can stop apps from being "
                "optimised (dexopt) and updated."
            ),
            (
                "Settings > Storage: free space (clear caches, remove unused apps "
                "and large media) to get above 15% free."
            ),
        ),
        "slow_writes": (
            (
                "diskstats timed a 512-byte write far above the usual few "
                "milliseconds, so storage is slow or worn."
            ),
            (
                "Free up space and reboot; if the latency stays high, back up and "
                "consider a factory reset or a storage check by the vendor."
            ),
        ),
    }
    summary, recommendation = advice[slug]
    return Finding(
        id=f"storage_io_per_uid.{slug}",
        title=title,
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=summary,
        evidence=[text.evidence(index)],
        recommendation=recommendation,
        followups=[
            "After freeing space, run "
            + _adb_ro("diskstats_after", "dumpsys diskstats", "grep -E 'Latency|Free'"),
        ],
    )


@analyzer("storage_io_per_uid")
def storage_io_per_uid(ctx: Context) -> Result:
    """Rank UIDs by flash I/O since boot and check free space and latency."""
    storaged = ctx.sources.get("storaged")
    intervals = ctx.sources.get("storaged_service")
    if storaged is None and intervals is None and not ctx.sources.has("diskstats"):
        msg = "no storaged output and no diskstats"
        raise SkipError(msg)
    result = Result("storage_io_per_uid", window="since_boot")
    if storaged and any(_STORAGED_HEADER_RE.match(x) for x in storaged.lines[:5]):
        _storaged_analysis(ctx, storaged, result)
    elif storaged:
        intervals = intervals or storaged
    if intervals:
        _interval_summary(ctx, intervals, result)
    _diskstats(ctx, result)
    result.notes.append(
        "storaged counts since it started (about boot); fg/bg columns describe "
        "each UID's own state, not which app was on screen.",
    )
    return result


# --------------------------------------------------------------------------
# dexopt_status
# --------------------------------------------------------------------------

# Compiler filters that mean ahead-of-time compiled code.
COMPILED_FILTERS = frozenset(
    {
        "speed",
        "speed-profile",
        "everything",
        "everything-profile",
        "space",
        "space-profile",
    },
)
# The background dexopt job runs daily when idle and charging; three days
# without a successful run means apps stay uncompiled after updates.
BG_DEXOPT_STALE_DAYS = 3
# The apps that draw the most frames (graphicsstats) count as frequently used.
FREQUENT_APPS = 10

_DEXOPT_HEADER = "Dexopt state:"
TIMEOUT_TAIL_CHARS = 2000
_DEXOPT_PACKAGE_RE = re.compile(r"^  \[([\w.]+)\]\s*$")
_DEXOPT_PATH_RE = re.compile(r"^\s+path: (\S+)")
_DEXOPT_STATUS_RE = re.compile(
    r"^\s+(arm64|arm|x86_64|x86|riscv64): \[status=([^\]]+)\] \[reason=([^\]]+)\]"
)
_JOB_HEADER_RE = re.compile(r"^\s*JOB \S+: \S+ (\S+)")
_JOB_LAST_RE = re.compile(
    r"^\s*Last (successful|failed) run: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)"
)
_DEXOPT_JOB_SERVICES = ("BackgroundDexoptJobService", "BackgroundDexOptService")
_PS_DEX2OAT_RE = re.compile(r"\bdex2oat")


def parse_dexopt(text: Text) -> tuple[list[dict[str, Any]], bool]:
    """Return primary-dex compiler status per package and whether it timed out."""
    lines = text.lines
    start = next((i for i, x in enumerate(lines) if x.strip() == _DEXOPT_HEADER), None)
    if start is None and not any(_DEXOPT_PACKAGE_RE.match(x) for x in lines[:5]):
        return [], False
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for i in range(0 if start is None else start + 1, len(lines)):
        line = lines[i]
        if line.strip() and not line.startswith(" "):
            break
        if m := _DEXOPT_PACKAGE_RE.match(line):
            current = {"package": m[1], "path": None, "status": None}
            rows.append(current)
        elif current and current["path"] is None and (m := _DEXOPT_PATH_RE.match(line)):
            current["path"] = m[1]
        elif (
            current
            and current["status"] is None
            and (m := _DEXOPT_STATUS_RE.match(line))
        ):
            current.update(isa=m[1], status=m[2], reason=m[3], ref=text.ref(i))
    # dumpsys marks a service dump cut short by its time limit at the end.
    timed_out = "DUMP TIMEOUT" in text.text[-TIMEOUT_TAIL_CHARS:]
    return [r for r in rows if r["status"]], timed_out


def _location(path: str | None) -> str:
    return "data" if path and path.startswith("/data/") else "system"


def _bg_dexopt(ctx: Context) -> dict[str, Any]:
    text = ctx.sources.get("jobscheduler")
    if text is None:
        return {}
    in_job = False
    found: dict[str, Any] = {}
    for i, line in enumerate(text.lines):
        if m := _JOB_HEADER_RE.match(line):
            in_job = m[1].endswith(_DEXOPT_JOB_SERVICES)
        elif in_job and (m := _JOB_LAST_RE.match(line)):
            stamp = _strptime(m[2], "%Y-%m-%d %H:%M:%S")
            key = f"last_{m[1]}"
            if stamp and (key not in found or stamp > found[key]):
                found[key] = stamp
                found[f"{key}_evidence"] = text.evidence(i)
    return found


def _dex2oat_running(ctx: Context) -> int | None:
    text = ctx.sources.get("ps") or ctx.sources.get("top")
    if text is None:
        return None
    return sum(1 for line in text.lines if _PS_DEX2OAT_RE.search(line))


def _frequent_packages(ctx: Context) -> dict[str, str]:
    """Return ``{package: role}``: key apps, then the apps that draw the most."""
    packages = key_packages(ctx)
    frames: dict[str, int] = {}
    for block in load_graphicsstats(ctx)[1]:
        frames[block.package] = frames.get(block.package, 0) + block.frames
    ranked = sorted(frames, key=lambda p: -frames[p])
    for package in ranked:
        if role := _role(package, packages):
            packages.setdefault(package, role)
    for package in ranked[:FREQUENT_APPS]:
        packages.setdefault(package, "frequently drawn")
    return packages


def _uncompiled_finding(rows: list[dict[str, Any]]) -> Finding:
    listed = ", ".join(f"{r['package']} ({r['status']})" for r in rows[:MAX_LISTED])
    return Finding(
        id="dexopt_status.key_apps_uncompiled",
        title=f"{len(rows)} key apps run without compiled code",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=(
            f"These frequently used apps are not ahead-of-time compiled: "
            f"{listed}. They run interpreted or JIT-compiled, which slows "
            "their start and scrolling until background dexopt compiles them."
        ),
        metrics={"packages": [r["package"] for r in rows]},
        evidence=[
            Evidence(r["ref"], f"{r['package']}: status={r['status']}")
            for r in rows[:3]
        ],
        recommendation=(
            "Leave the phone idle on the charger overnight so background "
            "optimisation can run; it needs idle, charging and free storage."
        ),
        followups=["Check the dexopt state again after a night on the charger"],
    )


def _stale_job_finding(job: dict[str, Any], days: float) -> Finding:
    evidence = [
        job[k] for k in ("last_successful_evidence", "last_failed_evidence") if k in job
    ]
    last = job.get("last_successful")
    return Finding(
        id="dexopt_status.background_dexopt_stale",
        title=f"Background app optimisation last succeeded {days:.0f} days ago",
        symptom="slowness",
        severity="medium",
        basis="measured",
        window="snapshot",
        summary=(
            f"The ART background dexopt job last succeeded at {last}. Apps "
            "updated since then run without compiled code until it runs."
        ),
        metrics={"days_since_success": round(days, 1)},
        evidence=evidence,
        recommendation=(
            "Leave the phone idle on the charger overnight with enough free "
            "storage; the job needs idle, charging and battery not low."
        ),
        followups=[
            "Check 'Last successful run' of BackgroundDexoptJobService tomorrow"
        ],
    )


@analyzer("dexopt_status")
def dexopt_status(ctx: Context) -> Result:
    """Report compiler filters per app and the background dexopt job."""
    text = ctx.sources.get("package_dexopt")
    rows, timed_out = parse_dexopt(text) if text else ([], False)
    job = _bg_dexopt(ctx)
    if not rows and not job:
        msg = "no dexopt state in the package dump and no dexopt job"
        raise SkipError(msg)
    result = Result("dexopt_status", window="snapshot")
    if timed_out:
        result.notes.append(
            "The package dump timed out; the dexopt list may be incomplete."
        )
    histogram: dict[str, int] = {}
    for row in rows:
        row["location"] = _location(row["path"])
        key = f"{row['location']}/{row['status']}"
        histogram[key] = histogram.get(key, 0) + 1
    result.metrics["packages_with_dexopt_state"] = len(rows)
    result.add_table(
        "compiler_filters",
        [
            {"location": k.split("/")[0], "filter": k.split("/", 1)[1], "packages": n}
            for k, n in sorted(histogram.items(), key=lambda kv: -kv[1])
        ],
    )
    result.metrics["data_apps_uncompiled"] = sum(
        1
        for r in rows
        if r["location"] == "data" and r["status"] not in COMPILED_FILTERS
    )
    key = _frequent_packages(ctx)
    status_by_package = {r["package"]: r for r in rows}
    key_rows = [
        {
            "package": p,
            "role": role,
            "status": r["status"],
            "reason": r["reason"],
            "ref": r["ref"],
        }
        for p, role in key.items()
        if (r := status_by_package.get(p))
    ]
    result.add_table("key_apps", key_rows)
    uncompiled = [r for r in key_rows if r["status"] not in COMPILED_FILTERS]
    if uncompiled:
        result.findings.append(_uncompiled_finding(uncompiled))
    _dexopt_job_metrics(ctx, result, job)
    result.metrics["dex2oat_processes_at_capture"] = _dex2oat_running(ctx)
    result.notes.append(
        "'verify' is normal for rarely used apps; it matters for apps used daily."
    )
    return result


def _dexopt_job_metrics(ctx: Context, result: Result, job: dict[str, Any]) -> None:
    last = job.get("last_successful")
    result.metrics["bg_dexopt_last_success"] = last.isoformat(sep=" ") if last else None
    failed = job.get("last_failed")
    result.metrics["bg_dexopt_last_failure"] = (
        failed.isoformat(sep=" ") if failed else None
    )
    if last and ctx.windows.dump_time:
        days = (ctx.windows.dump_time - last).total_seconds() / SECONDS_PER_DAY
        result.metrics["bg_dexopt_days_since_success"] = round(days, 1)
        if days > BG_DEXOPT_STALE_DAYS:
            result.findings.append(_stale_job_finding(job, days))


# --------------------------------------------------------------------------
# build_identity
# --------------------------------------------------------------------------

# A vendor image this many API levels behind the OS may lack kernel and HAL
# support that newer framework features assume.
VENDOR_API_GAP_FLAG = 3
# Properties reported as metrics. Serial numbers and other identifiers are
# deliberately absent.
BUILD_PROPS = {
    "ro.build.version.release": "android_release",
    "ro.build.version.sdk": "sdk",
    "ro.build.display.id": "build_display_id",
    "ro.build.fingerprint": "build_fingerprint",
    "ro.build.version.security_patch": "security_patch",
    "ro.build.date": "build_date",
    "ro.build.type": "build_type",
    "ro.vendor.api_level": "vendor_api_level",
    "ro.board.first_api_level": "board_first_api_level",
    "ro.product.first_api_level": "product_first_api_level",
    "ro.vendor.build.version.release": "vendor_android_release",
    "ro.vendor.build.version.sdk": "vendor_sdk",
    "ro.vendor.build.fingerprint": "vendor_fingerprint",
    "ro.kernel.version": "kernel_series",
    "ro.soc.manufacturer": "soc_manufacturer",
    "ro.soc.model": "soc_model",
    "ro.hardware": "hardware",
    "ro.product.manufacturer": "manufacturer",
    "ro.product.model": "model",
    "ro.product.device": "device",
    "ro.boot.verifiedbootstate": "verified_boot_state",
    "ro.build.ab_update": "ab_update",
    "sys.boot.reason": "boot_reason",
}
# Kernel command-line flags worth knowing; the command line itself also holds
# serial numbers and MAC addresses and is never copied.
KERNEL_FLAGS_RE = re.compile(r"\b(cgroup_disable=\S+|psi=\S+|transparent_hugepage=\S+)")

_PROP_RE = re.compile(r"^\[([^\]]+)\]: \[(.*)$")
_KERNEL_RE = re.compile(r"Linux version (\S+)")
_ROLLBACK_ID_RE = re.compile(r"^\s*(\d+):\s*$")
_ROLLBACK_FIELD_RE = re.compile(r"^\s*-(state|stateDescription|timestamp): ?(.*)$")
_ROLLBACK_TS_RE = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)")
# Rollback stamps before Android 10 (2019) or after the capture come from a
# clock that was not set yet.
EARLIEST_STAMP = datetime(2019, 1, 1)
_OTA_RESULT_RE = re.compile(r"OTAResult::(\w+)")
_UE_STAMP_RE = re.compile(r"update_engine\.(\d{8}-\d{6})")
_DROPBOX_BOOT_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) SYSTEM_BOOT")
_DROPBOX_BUILD_RE = re.compile(r"^Build: (\S+)")


def parse_getprop(text: Text) -> dict[str, tuple[str, int]]:
    """Parse ``getprop`` output, including values that span several lines."""
    props: dict[str, tuple[str, int]] = {}
    key: str | None = None
    parts: list[str] = []
    start = 0
    for i, line in enumerate(text.lines):
        if key is None:
            m = _PROP_RE.match(line)
            if not m:
                continue
            key, parts, start = m[1], [m[2]], i
        else:
            parts.append(line)
        if parts[-1].endswith("]"):
            props[key] = ("\n".join(parts)[:-1], start)
            key = None
    return props


def _parse_rollbacks(text: Text) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for i, line in enumerate(text.lines):
        if m := _ROLLBACK_ID_RE.match(line):
            current = {"index": i}
            records.append(current)
        elif current is not None and (m := _ROLLBACK_FIELD_RE.match(line)):
            current[m[1]] = m[2].strip()
            if m[1] == "timestamp" and (stamp := _ROLLBACK_TS_RE.match(m[2])):
                current["time"] = _strptime(stamp[1], "%Y-%m-%dT%H:%M:%S")
    return [r for r in records if r.get("time")]


def _ota_window(text: Text, latest: datetime) -> dict[str, Any]:
    """Bracket the last OTA with mainline rollback records.

    An OTA changes the build fingerprint, and the rollback manager then
    deletes every pending rollback with "Fingerprint changed". So the last OTA
    came after the newest record deleted that way and before the oldest record
    still available (inferred from the rollback lifecycle). Records stamped
    after ``latest`` come from an unset clock and are ignored.
    """
    records = [
        r for r in _parse_rollbacks(text) if EARLIEST_STAMP <= r["time"] <= latest
    ]
    deleted = [r for r in records if r.get("stateDescription") == "Fingerprint changed"]
    if not deleted:
        return {}
    after = max(deleted, key=itemgetter("time"))
    alive = [
        r
        for r in records
        if r.get("state") == "available" and r["time"] > after["time"]
    ]
    before = min(alive, key=itemgetter("time")) if alive else None
    out = {
        "ota_after_utc": after["timestamp"],
        "evidence": [text.evidence(after["index"])],
    }
    if before:
        out["ota_before_utc"] = before["timestamp"]
        out["evidence"].append(text.evidence(before["index"]))
    return out


def _update_engine(ctx: Context) -> list[dict[str, Any]]:
    rows = []
    for text in ctx.sources.members("update_engine_logs"):
        stamp = _UE_STAMP_RE.search(text.origin)
        results = _OTA_RESULT_RE.findall(text.text)
        rows.append(
            {
                "log": text.origin.rsplit("/", 1)[-1],
                "started": stamp[1] if stamp else None,
                "ota_results": sorted(set(results)),
                "ref": text.ref(0),
            },
        )
    return sorted(rows, key=lambda r: r["started"] or "")


def _dropbox_builds(ctx: Context) -> list[dict[str, Any]]:
    text = ctx.sources.get("dropbox")
    if text is None:
        return []
    builds: list[dict[str, Any]] = []
    boot_time: str | None = None
    for i, line in enumerate(text.lines):
        if m := _DROPBOX_BOOT_RE.match(line):
            boot_time = m[1]
        elif boot_time and (m := _DROPBOX_BUILD_RE.match(line)):
            if not builds or builds[-1]["build"] != m[1]:
                builds.append(
                    {"first_boot": boot_time, "build": m[1], "ref": text.ref(i)}
                )
            builds[-1]["last_boot"] = boot_time
            boot_time = None
    return builds


def _header_fields(ctx: Context) -> dict[str, Any]:
    br = ctx.sources.workdir.bugreport
    if br is None:
        return {}
    header = br.header
    out: dict[str, Any] = {}
    if m := _KERNEL_RE.search(header.get("kernel", "")):
        out["kernel_release"] = m[1]
    flags = list(dict.fromkeys(KERNEL_FLAGS_RE.findall(header.get("command_line", ""))))
    if flags:
        out["kernel_cmdline_flags"] = " ".join(flags)
    return out


def _kernel_release(ctx: Context) -> str | None:
    text = ctx.sources.get("kernel_release")
    if text and text.lines:
        return text.lines[0].strip() or None
    return None


def _build_metrics(
    ctx: Context, result: Result
) -> tuple[dict[str, tuple[str, int]], Text | None]:
    text = ctx.sources.get("getprop")
    props = parse_getprop(text) if text else {}
    for prop, name in BUILD_PROPS.items():
        if prop in props:
            result.metrics[name] = props[prop][0]
    result.metrics.update(_header_fields(ctx))
    if release := _kernel_release(ctx):
        result.metrics["kernel_release"] = release
    return props, text


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _security_patch_age(ctx: Context, result: Result) -> None:
    patch = result.metrics.get("security_patch")
    if not patch or not ctx.windows.dump_time:
        return
    try:
        day = datetime.strptime(patch, "%Y-%m-%d")
    except ValueError:
        return
    result.metrics["security_patch_age_days"] = (ctx.windows.dump_time - day).days


def _ota_metrics(ctx: Context, result: Result) -> list[Evidence]:
    evidence: list[Evidence] = []
    rollback = ctx.sources.get("rollback")
    if rollback:
        latest = ctx.windows.log_reference() + timedelta(days=1)
        window = _ota_window(rollback, latest)
        evidence += window.pop("evidence", [])
        result.metrics.update(window)
    engine = _update_engine(ctx)
    result.add_table("update_engine_logs", engine)
    success = [r for r in engine if "OTA_SUCCESSFUL" in r["ota_results"]]
    if success:
        result.metrics["ota_success_log"] = success[-1]["started"]
        evidence.append(Evidence(success[-1]["ref"], "OTAResult::OTA_SUCCESSFUL"))
    builds = _dropbox_builds(ctx)
    result.add_table("builds_seen_at_boot", builds)
    if len(builds) > 1:
        result.metrics["build_changed_after"] = builds[-2]["last_boot"]
        result.metrics["build_changed_before"] = builds[-1]["first_boot"]
        evidence.append(Evidence(builds[-1]["ref"], f"Build: {builds[-1]['build']}"))
    return evidence


def _identity_summary(m: dict[str, Any]) -> str:
    parts = [
        (
            f"Android {m.get('android_release', '?')} (SDK {m.get('sdk', '?')}), "
            f"build {m.get('build_display_id', '?')}, security patch "
            f"{m.get('security_patch', '?')}."
        ),
    ]
    if m.get("vendor_api_level") or m.get("vendor_android_release"):
        parts.append(
            f"Vendor image API level {m.get('vendor_api_level', '?')} (Android "
            f"{m.get('vendor_android_release', '?')}).",
        )
    if m.get("kernel_release") or m.get("kernel_series"):
        parts.append(f"Kernel {m.get('kernel_release') or m.get('kernel_series')}.")
    if m.get("soc_model"):
        parts.append(
            f"SoC {m.get('soc_manufacturer', '')} {m['soc_model']}.".replace("  ", " ")
        )
    if m.get("ota_after_utc"):
        parts.append(
            f"The last OTA was installed after {m['ota_after_utc']}"
            + (f" and before {m['ota_before_utc']}" if m.get("ota_before_utc") else "")
            + " (inferred from rollback records).",
        )
    return " ".join(parts)


def _vendor_gap_finding(result: Result, evidence: list[Evidence], gap: int) -> Finding:
    m = result.metrics
    return Finding(
        id="build_identity.old_vendor_image",
        title=f"Vendor image is {gap} API levels older than the OS",
        symptom="both",
        severity="low",
        basis="inferred",
        window="snapshot",
        summary=(
            f"The OS is SDK {m.get('sdk')} but the vendor image (kernel and "
            f"HALs) is API level {m.get('vendor_api_level')}. Framework features "
            "that need newer kernel or HAL support (for example the cached-app "
            "freezer or newer memory-pressure handling) may be off or degraded. "
            "This is a known-issue lead, not a measured cause."
        ),
        metrics={"sdk": m.get("sdk"), "vendor_api_level": m.get("vendor_api_level")},
        evidence=evidence,
        recommendation=(
            "When searching for known issues, match both the OS build and the "
            "vendor base; check the memory analysis for the freezer state."
        ),
        followups=[
            (
                "Is the freezer enabled? grep -i freezer "
                "WORKDIR/live/activity_settings.txt; if that file is missing, "
                "first run adb_ro.py --save activity_settings --workdir WORKDIR "
                "-- dumpsys activity settings"
            ),
        ],
    )


def _prop_evidence(
    text: Text | None, props: dict[str, tuple[str, int]], keys: tuple[str, ...]
) -> list[Evidence]:
    if text is None:
        return []
    return [text.evidence(props[k][1]) for k in keys if k in props]


@analyzer("build_identity")
def build_identity(ctx: Context) -> Result:
    """Report OS, vendor and kernel versions and the last OTA."""
    has_header = ctx.sources.workdir.bugreport is not None
    if not ctx.sources.has("getprop") and not has_header:
        msg = "no getprop dump and no bugreport header"
        raise SkipError(msg)
    result = Result("build_identity", window="snapshot")
    props, text = _build_metrics(ctx, result)
    _security_patch_age(ctx, result)
    evidence = _prop_evidence(
        text,
        props,
        (
            "ro.build.fingerprint",
            "ro.build.version.security_patch",
            "ro.vendor.api_level",
        ),
    )
    evidence += _ota_metrics(ctx, result)
    m = result.metrics
    result.findings.append(
        Finding(
            id="build_identity.build",
            title=f"Build {m.get('build_display_id', 'unknown')}",
            symptom="info",
            severity="info",
            basis="measured",
            window="snapshot",
            summary=_identity_summary(m),
            metrics={
                k: m.get(k)
                for k in (
                    "android_release",
                    "sdk",
                    "build_display_id",
                    "security_patch",
                    "vendor_api_level",
                    "kernel_release",
                )
            },
            evidence=evidence,
            recommendation=(
                "Use the build ID, vendor base and kernel when searching for "
                "known issues; check that forum reports match this build and "
                "that their cause is visible in this data."
            ),
            followups=["Compare with the vendor's release notes for later builds"],
        ),
    )
    sdk, vendor = _int_or_none(m.get("sdk")), _int_or_none(m.get("vendor_api_level"))
    if sdk and vendor and sdk - vendor >= VENDOR_API_GAP_FLAG:
        gap_evidence = _prop_evidence(
            text, props, ("ro.vendor.api_level", "ro.build.version.sdk")
        )
        result.findings.append(_vendor_gap_finding(result, gap_evidence, sdk - vendor))
    return result
