"""Qualcomm-specific parsers: Wi-Fi wake packets, charging logs, WLAN logging.

These analyzers read vendor driver lines from the kernel log and the process
list. On phones without Qualcomm drivers they skip.

Wake-on-WLAN: while the SoC sleeps, the Wi-Fi firmware filters incoming frames
and wakes the host for those that pass. The qcacld driver logs each such wake:
the trigger (``WLAN triggered wakeup: BPF_ALLOW (39)``), the frame's source and
destination MAC (``wma_wow_parse_data_pkt: ... Src_mac: ..., Dst_mac: ...``)
and, for some protocols only, the decoded type and ports. Driver lines carry a
UTC time of day that keeps running while the printk clock stops in suspend.

Charging: the SMB5 charger, QG fuel gauge and step-charging drivers log the
negotiated USB source, the charge-current (FCC) votes and the gauge's battery
resistance.

cnss_diag is Qualcomm's WLAN firmware log daemon. A production phone does not
need it; ``qcom_wlan_logging`` notes that it runs, and
``system_process_cpu_churn`` reports its CPU on battery.
"""

from __future__ import annotations

import re
import statistics
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING

from .common import load_ps, pct, ps_cpu_by_name
from .kernel_suspend import KernelLine, driver_tod_s, load_kernel_log, parse_healthd
from .model import Context, Finding, Result, SkipError, analyzer, link

if TYPE_CHECKING:
    from .kernel_suspend import HealthdSample
    from .source import Text

# One sender causing this share of the wake packets is the primary target
# (battery catalogue: a single LAN source above ~30 % of wakes).
DOMINANT_SENDER_PCT = 30.0
# Below this many wakes a share says little.
MIN_SENDER_WAKES = 10
# A sender waking the phone more than twice a minute keeps it from staying
# asleep for long: severity high.
HIGH_SENDER_WAKES_PER_MIN = 2.0
# Multicast and broadcast frames above 10 % of wakes mean multicast filtering
# is off, usually because an app holds a Wi-Fi multicast lock.
MULTICAST_FLAG_PCT = 10.0
MIN_MULTICAST_WAKES = 5
# Periodicity: candidate periods from 1 s to 60 s in 0.05 s steps, and a gap
# fits the grid when it is within 0.1 s of a whole multiple. A sender is
# periodic when 60 % of its gaps fit and that beats the chance level of
# 2 * tolerance / period by 40 points.
MIN_PERIOD_S = 1.0
MAX_PERIOD_S = 60.0
PERIOD_STEP_S = 0.05
GRID_TOLERANCE_S = 0.1
MIN_GAPS_FOR_PERIOD = 10
PERIODIC_MIN_FIT_PCT = 60.0
PERIODIC_MIN_EXCESS_PCT = 40.0
# Periodicity is computed for the top senders only.
MAX_SENDERS_FOR_PERIOD = 10
# Two periods within this fraction of each other are taken as one timer.
PERIOD_MATCH = 0.05
# Lines of one wake event follow its Src_mac line within microseconds.
EVENT_SPAN_S = 0.05
# A charger "not charging" for this long below this level is worth a look.
NOT_CHARGING_MIN_S = 120.0
NOT_CHARGING_MAX_LEVEL = 90
SECONDS_PER_DAY = 86_400
SECONDS_PER_MINUTE = 60.0
# BatteryManager constants used in healthd lines.
STATUS_CHARGING = 2
STATUS_NOT_CHARGING = 4
BAD_HEALTH = {3: "overheat", 4: "dead", 5: "over voltage", 6: "failure", 7: "cold"}

_WOW_PKT_RE = re.compile(
    r"wma_wow_parse_data_pkt: \d+: Src_mac: (?P<src>[0-9a-f]{2}(?::[0-9a-f]{2}){5}), "
    r"Dst_mac: (?P<dst>[0-9a-f]{2}(?::[0-9a-f]{2}){5})",
    re.IGNORECASE,
)
_WOW_KIND_RE = re.compile(r"WOW Wakeup: (?P<kind>.+?) rcvd")
_WOW_PORTS_RE = re.compile(
    r"\bPkt_len: (?P<len>\d+)(?:, src_port: (?P<sport>\d+), dst_port: (?P<dport>\d+))?",
)
_TRIGGER_RE = re.compile(
    r"(?P<who>Non-WLAN|WLAN) triggered wakeup: (?P<reason>.+?) \((?P<code>-?\d+)\)",
)
_FW_COUNTERS_RE = re.compile(
    r"\buc:(?P<uc>\d+) bc:(?P<bc>\d+) v4_mc:(?P<v4_mc>\d+) v6_mc:(?P<v6_mc>\d+)",
)
_FW_WAKE_REASONS_RE = re.compile(
    r"Wlan Wake Reasons:.*?totalRxDataWake (?P<total>\d+) rxUnicast (?P<uc>\d+) "
    r"rxMulticast (?P<mc>\d+) rxBroadcast (?P<bc>\d+)",
)
_NEIGH_RE = re.compile(
    r"^(?P<ip>\S+) dev (?P<dev>\S+) lladdr (?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})",
    re.IGNORECASE,
)
_GATEWAY_RE = re.compile(r"(?:0\.0\.0\.0/0|::/0) -> (?P<gw>[0-9a-f.:]+) wlan\d")

_CHARGER_LINE_RE = re.compile(r"\[SMB(?:LIB)?\d*\]|QG-K:|QCOM-STEPCHG|\[PE\]:")
_PLUGIN_RE = re.compile(r"usbin-plugin (?P<state>attached|detached)")
_TYPEC_RE = re.compile(r"Type-C Source \((?P<desc>[^)]+)\) connected")
_FCC_RE = re.compile(r"set final main_fcc = (?P<ua>\d+)")
_VBATT_LIMIT_RE = re.compile(r"handle_vbatt_limit: f=(?P<ua>\d+), v=(?P<uv>\d+)")
_JEITA_RE = re.compile(r"handle_jeita ,temp:(?P<temp>-?\d+), fcc_ua:(?P<ua>\d+)")
_JEITA_DISABLE_RE = re.compile(r"chg_disable_votable:(?P<on>true|false)")
_CP_ILIM_RE = re.compile(r"ilim (?P<ua>\d+)uA is too low to config CP charging")
_QG_RE = re.compile(r"QG-K: .*\brbat=(?P<rbat>\d+), esr=(?P<esr>\d+)")
_USB_PERIPHERAL_RE = re.compile(r"start_usb_peripheral")


def _local_offset(ctx: Context) -> timedelta | None:
    """Return the UTC offset from the clock dump or from the kernel_suspend result."""
    if (offset := ctx.windows.offset()) is not None:
        return offset
    kernel = ctx.results.get("kernel_suspend")
    if kernel is None:
        return None
    utc = kernel.metrics.get("log_first_utc")
    local = kernel.metrics.get("log_first_local")
    if not utc or not local:
        return None
    return datetime.fromisoformat(local) - datetime.fromisoformat(utc)


def _tod_text(seconds: float, offset: timedelta | None = None) -> str:
    value = (seconds + (offset.total_seconds() if offset else 0.0)) % SECONDS_PER_DAY
    whole = int(value)
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{value % 60:06.3f}"


# ------------------------------------------------------------- wake packets


@dataclass
class WakePacket:
    """One Wi-Fi wake caused by a data packet."""

    line: KernelLine
    time_s: float  # UTC seconds of day from the driver stamp, else kernel seconds
    src: str
    dst: str
    kind: str = ""  # "IPV4 TCP Packet"; empty when the driver did not decode it
    sport: int | None = None
    dport: int | None = None


@dataclass
class WowLog:
    """Everything the WLAN driver logged about wakes in the kernel log."""

    packets: list[WakePacket] = field(default_factory=list)
    triggers: Counter[str] = field(default_factory=Counter)
    counters: list[tuple[KernelLine, dict[str, int]]] = field(default_factory=list)
    wall_clock: bool = True


def parse_wow(lines: list[KernelLine]) -> WowLog:
    """Collect wake packets, wake triggers and firmware counters."""
    log = WowLog()
    current: WakePacket | None = None
    for kl in lines:
        msg = kl.msg
        if "wlan:" not in msg and "WMA" not in msg:
            continue
        if m := _WOW_PKT_RE.search(msg):
            time_s = driver_tod_s(msg)
            if time_s is None:
                time_s, log.wall_clock = kl.t, False
            current = WakePacket(kl, time_s, m["src"].lower(), m["dst"].lower())
            log.packets.append(current)
        elif m := _TRIGGER_RE.search(msg):
            log.triggers[f"{m['who']}: {m['reason']} ({m['code']})"] += 1
        elif m := _FW_COUNTERS_RE.search(msg):
            log.counters.append((kl, {k: int(v) for k, v in m.groupdict().items()}))
        elif current is not None and kl.t - current.line.t <= EVENT_SPAN_S:
            if (m := _WOW_KIND_RE.search(msg)) and not current.kind:
                current.kind = m["kind"].strip()
            elif (m := _WOW_PORTS_RE.search(msg)) and m["sport"]:
                current.sport, current.dport = int(m["sport"]), int(m["dport"])
    return log


def dst_class(dst: str, own: str) -> str:
    """Classify a destination MAC: own unicast, mDNS, multicast or broadcast."""
    if dst == "ff:ff:ff:ff:ff:ff":
        return "broadcast"
    if dst in {"01:00:5e:00:00:fb", "33:33:00:00:00:fb"}:
        return "mdns_multicast"
    if dst.startswith("01:00:5e:"):
        return "ipv4_multicast"
    if dst.startswith("33:33:"):
        return "ipv6_multicast"
    if int(dst[:2], 16) & 1:
        return "other_multicast"
    return "unicast_own" if dst == own else "unicast_other"


def grid_fit(gaps: list[float]) -> tuple[float, float, float] | None:
    """Return (period_s, fit_pct, chance_pct) of the grid the gaps fit best.

    For each candidate period P, a gap fits when it lies within
    ``GRID_TOLERANCE_S`` of a whole multiple of P (at least one). Short periods
    fit anything by chance, so candidates are ranked by how far the fit beats
    the chance level ``2 * tolerance / P``; ties go to the longer period.
    """
    if len(gaps) < MIN_GAPS_FOR_PERIOD:
        return None
    best: tuple[float, float, float] | None = None
    best_excess = -1.0
    steps = round((MAX_PERIOD_S - MIN_PERIOD_S) / PERIOD_STEP_S)
    for step in range(steps + 1):
        period = MIN_PERIOD_S + step * PERIOD_STEP_S
        fits = sum(
            1
            for g in gaps
            if g >= period - GRID_TOLERANCE_S
            and abs(g - round(g / period) * period) <= GRID_TOLERANCE_S
        )
        fit = fits / len(gaps)
        chance = min(1.0, 2 * GRID_TOLERANCE_S / period)
        if fit - chance >= best_excess - 1e-9:
            best_excess = fit - chance
            best = (round(period, 2), round(100 * fit, 1), round(100 * chance, 1))
    return best


def _neighbours(ctx: Context) -> tuple[dict[str, list[str]], set[str]]:
    """Map MAC addresses to IP addresses, and collect the Wi-Fi gateways."""
    by_mac: dict[str, list[str]] = {}
    for key in ("arp", "ipv6_neigh"):
        if (text := ctx.sources.get(key)) is None:
            continue
        for line in text.lines:
            if m := _NEIGH_RE.match(line.strip()):
                by_mac.setdefault(m["mac"].lower(), []).append(m["ip"])
    gateways: set[str] = set()
    for key in ("connectivity", "wifi"):
        if (text := ctx.sources.get(key)) is not None:
            gateways.update(m["gw"] for _, m in text.find(_GATEWAY_RE))
    return by_mac, gateways


def _gaps(times: list[float]) -> list[float]:
    """Return inter-arrival gaps, unwrapping a midnight rollover."""
    gaps = []
    for a, b in pairwise(times):
        gap = b - a
        if gap < -SECONDS_PER_DAY / 2:
            gap += SECONDS_PER_DAY
        gaps.append(gap)
    return gaps


def _sender_rows(
    packets: list[WakePacket],
    own: str,
    by_mac: dict[str, list[str]],
    gateways: set[str],
) -> list[dict]:
    by_src: dict[str, list[WakePacket]] = {}
    for p in packets:
        by_src.setdefault(p.src, []).append(p)
    ranked = sorted(by_src.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    rows = []
    for rank, (src, pkts) in enumerate(ranked, start=1):
        ips = by_mac.get(src, [])
        role = "gateway" if gateways & set(ips) else "lan_peer" if ips else "unknown"
        protocols = Counter(_protocol(p) for p in pkts)
        gaps = _gaps([p.time_s for p in pkts])
        row = {
            "sender": f"sender-{rank}",
            "src_mac": src,
            "ips": ", ".join(ips),
            "role": role,
            "wakes": len(pkts),
            "share_pct": pct(len(pkts), len(packets)),
            "to_own_unicast": sum(1 for p in pkts if p.dst == own),
            "to_multicast_or_broadcast": sum(
                1 for p in pkts if not dst_class(p.dst, own).startswith("unicast")
            ),
            "top_protocol": protocols.most_common(1)[0][0],
            "median_gap_s": round(statistics.median(gaps), 2) if gaps else None,
        }
        if rank <= MAX_SENDERS_FOR_PERIOD and (fit := grid_fit(gaps)):
            row.update(period_s=fit[0], on_grid_pct=fit[1], chance_pct=fit[2])
            row["gaps_on_grid"] = round(fit[1] * len(gaps) / 100)
            row["gaps"] = len(gaps)
        rows.append(row)
    return rows


def _protocol(p: WakePacket) -> str:
    kind = p.kind or "undecoded"
    return f"{kind} {p.sport}->{p.dport}" if p.sport is not None else kind


def _periodic(row: dict) -> bool:
    return (
        row.get("on_grid_pct", 0.0) >= PERIODIC_MIN_FIT_PCT
        and row["on_grid_pct"] - row["chance_pct"] >= PERIODIC_MIN_EXCESS_PCT
    )


def _firmware_counters(ctx: Context, log: WowLog, result: Result) -> None:
    if len(log.counters) >= 2:  # ruff: ignore[magic-value-comparison] - a delta needs two reads
        first, last = log.counters[0][1], log.counters[-1][1]
        if all(last[k] >= first[k] for k in first):
            for key, value in last.items():
                result.metrics[f"fw_{key}_delta"] = value - first[key]
        else:
            result.notes.append(
                "The firmware wake counters went down within the log (driver "
                "restart), so no deltas are given.",
            )
    wifi = ctx.sources.get("wifi")
    found = wifi.find(_FW_WAKE_REASONS_RE) if wifi else []
    if found:
        m = found[0][1]
        total = int(m["total"])
        result.metrics.update(
            fw_rx_data_wakes_since_driver_start=total,
            fw_rx_multicast_broadcast_pct_since_driver_start=pct(
                int(m["mc"]) + int(m["bc"]),
                total,
            ),
        )


def _own_mac(packets: list[WakePacket]) -> str:
    """Return the phone's own MAC: the most common unicast destination."""
    unicast = Counter(p.dst for p in packets if not int(p.dst[:2], 16) & 1)
    return unicast.most_common(1)[0][0] if unicast else ""


def _sample_metrics(
    ctx: Context,
    log: WowLog,
    classes: Counter[str],
    result: Result,
) -> None:
    packets = log.packets
    first, last = packets[0].time_s, packets[-1].time_s
    span_s = _gaps([first, last])[0] if len(packets) > 1 else 0.0
    clock = "utc" if log.wall_clock else "kernel"
    total = len(packets)
    result.metrics.update(
        {
            f"first_wake_{clock}": _tod_text(first),
            f"last_wake_{clock}": _tod_text(last),
            "sample_span_s": round(span_s, 1),
            "wakes_per_min": (
                round(total / (span_s / SECONDS_PER_MINUTE), 1) if span_s else None
            ),
            "unicast_own_pct": pct(classes["unicast_own"], total),
            "multicast_broadcast_pct": pct(_group_count(classes), total),
            "mdns_pct": pct(classes["mdns_multicast"], total),
            "undecoded_wakes": sum(1 for p in packets if not p.kind),
        },
    )
    offset = _local_offset(ctx) if log.wall_clock else None
    if offset is not None:
        result.metrics["first_wake_local"] = _tod_text(first, offset)
        result.metrics["last_wake_local"] = _tod_text(last, offset)
    if not log.wall_clock:
        result.notes.append(
            "The WLAN lines have no UTC stamps; gaps use kernel seconds, which "
            "stop while suspended.",
        )


def _group_count(classes: Counter[str]) -> int:
    """Return the number of multicast and broadcast wakes."""
    unicast = classes["unicast_own"] + classes["unicast_other"]
    return sum(classes.values()) - unicast


def _wake_tables(
    packets: list[WakePacket],
    classes: Counter[str],
    senders: list[dict],
    result: Result,
) -> None:
    result.add_table("wake_senders", senders)
    result.add_table(
        "wake_destinations",
        [
            {"destination": k, "wakes": v, "share_pct": pct(v, len(packets))}
            for k, v in classes.most_common()
        ],
    )
    protocols = Counter(_protocol(p) for p in packets)
    result.add_table(
        "wake_protocols",
        [
            {"protocol": k, "wakes": v, "share_pct": pct(v, len(packets))}
            for k, v in protocols.most_common()
        ],
    )
    result.notes.append(
        "wake_senders holds MAC and IP addresses of devices on the local network. "
        "They are personal data: keep them local and use the sender labels when "
        "sharing a report.",
    )


@analyzer(
    "qcom_wow",
    requires=("dmesg",),
    after=("windows", "kernel_suspend", "wake_periodicity", "wifi_multicast"),
)
def qcom_wow(ctx: Context) -> Result:
    """Attribute Wi-Fi wake packets to senders, protocols and destinations."""
    klog = load_kernel_log(ctx)
    log = parse_wow(klog.lines)
    if not log.packets and not log.triggers:
        msg = "no Qualcomm WLAN wake (WOW) lines in the kernel log"
        raise SkipError(msg)
    result = Result("qcom_wow", window="log_coverage")
    result.metrics.update(
        wake_triggers=sum(log.triggers.values()),
        wake_packets=len(log.packets),
    )
    result.add_table(
        "wake_triggers",
        [{"trigger": k, "count": v} for k, v in log.triggers.most_common()],
    )
    _firmware_counters(ctx, log, result)
    result.notes.append(
        "Per-packet data covers only the kernel-log sample (minutes). Shares are "
        "a sample, not the whole battery period; firmware counters give the "
        "long-run split.",
    )
    if klog.skipped:
        result.notes.append(f"{klog.skipped} kernel-log lines without a time stamp.")
    if not log.packets:
        return result
    own = _own_mac(log.packets)
    classes = Counter(dst_class(p.dst, own) for p in log.packets)
    _sample_metrics(ctx, log, classes, result)
    senders = _sender_rows(log.packets, own, *_neighbours(ctx))
    _wake_tables(log.packets, classes, senders, result)
    top = senders[0]
    result.metrics.update(
        top_sender_share_pct=top["share_pct"],
        top_sender_role=top["role"],
        top_sender_period_s=top.get("period_s") if _periodic(top) else None,
    )
    if finding := _dominant_sender(top, result.metrics, klog.text, log.packets):
        _confirm_periodicity(ctx, finding, result.metrics)
        result.findings.append(finding)
    multicast = _multicast_finding(classes, result.metrics, klog.text, log.packets, own)
    if multicast:
        _blame_multicast_lock(ctx, multicast)
        result.findings.append(multicast)
    return result


def _confirm_periodicity(ctx: Context, sender: Finding, m: dict) -> None:
    """Link the sender to the battery history's periodic resumes on one period.

    They come from two sources, so both findings stay, linked.
    """
    periodic = ctx.finding("wake_periodicity.periodic_sender")
    period = m.get("top_sender_period_s")
    if not periodic or not period:
        return
    history_period = periodic.metrics["period_s"]
    if abs(period - history_period) <= PERIOD_MATCH * history_period:
        sender.summary += (
            " This confirms wake_periodicity: screen-off resumes in the battery "
            f"history repeat every {history_period:.2f} s."
        )
        link(sender, periodic)


def _blame_multicast_lock(ctx: Context, multicast: Finding) -> None:
    """Name the multicast lock behind the wakes; wifi_multicast owns the fact."""
    lock = ctx.finding("wifi_multicast.lock_held")
    held = lock.metrics.get("multicast_pct_of_battery") if lock else None
    if lock is None or held is None:
        return
    multicast.summary = multicast.summary.replace(
        _LOCK_INFERRED,
        f"a Wi-Fi multicast lock, held {held:.0f}% of the time on battery "
        "(wifi_multicast), turns it off.",
    )
    link(lock, multicast)


def _dominant_sender(
    top: dict,
    m: dict,
    text: Text,
    packets: list[WakePacket],
) -> Finding | None:
    if top["share_pct"] < DOMINANT_SENDER_PCT or top["wakes"] < MIN_SENDER_WAKES:
        return None
    span_min = m["sample_span_s"] / SECONDS_PER_MINUTE
    rate = top["wakes"] / span_min if span_min else 0.0
    periodic = (
        f" Its packets arrive on a {top['period_s']:.2f} s grid: "
        f"{top['gaps_on_grid']} of {top['gaps']} gaps fall within "
        f"{GRID_TOLERANCE_S:g} s of a multiple (chance level {top['chance_pct']} %)."
        if _periodic(top)
        else ""
    )
    example = next(p for p in packets if p.src == top["src_mac"])
    role = {"gateway": "the Wi-Fi router", "lan_peer": "a device on the local network"}
    return Finding(
        id="qcom_wow.dominant-sender",
        title="One network device causes most Wi-Fi wakes",
        symptom="battery",
        severity="high" if rate >= HIGH_SENDER_WAKES_PER_MIN else "medium",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{top['wakes']} of {m['wake_packets']} Wi-Fi wake packets "
            f"({top['share_pct']} %) in the {m['sample_span_s']:.0f} s kernel-log "
            f"sample came from {role.get(top['role'], 'one sender')} "
            f"({top['sender']} in wake_senders), {rate:.1f} per minute.{periodic}"
            " The sample is minutes long; the share need not hold for hours."
        ),
        metrics={
            k: top.get(k)
            for k in ("sender", "role", "wakes", "share_pct", "period_s", "on_grid_pct")
        },
        # The excerpt leaves out the line: it holds MAC addresses.
        evidence=[text.evidence(example.line.index, "Src_mac line of a wake")],
        recommendation=(
            "Identify the device from its address in wake_senders (the router's "
            "client list names it) and stop or slow what it sends to the phone: "
            "sync and remote-control apps, VPN mesh peers, casting or smart-home "
            "hubs. Traffic from the router itself is internet traffic, such as "
            "push or keepalive connections of apps on the phone."
        ),
        followups=[
            (
                "Repeat the capture with that device's app or service stopped "
                "and compare the wake rate."
            ),
            (
                "Check per-UID network traffic to find the app on the phone that "
                "receives these packets."
            ),
        ],
    )


_LOCK_INFERRED = "that an app's multicast lock turned it off is inferred."


def _multicast_finding(
    classes: Counter[str],
    m: dict,
    text: Text,
    packets: list[WakePacket],
    own: str,
) -> Finding | None:
    count = _group_count(classes)
    share = m["multicast_broadcast_pct"] or 0.0
    if share < MULTICAST_FLAG_PCT or count < MIN_MULTICAST_WAKES:
        return None
    example = next(
        p for p in packets if not dst_class(p.dst, own).startswith("unicast")
    )
    return Finding(
        id="qcom_wow.multicast-wakes",
        title="Multicast and broadcast frames wake the phone over Wi-Fi",
        symptom="battery",
        severity="medium",
        basis="measured",
        window="log_coverage",
        summary=(
            f"{count} of {len(packets)} Wi-Fi wake packets ({share} %) in the "
            "kernel-log sample were multicast or broadcast, "
            f"{classes['mdns_multicast']} of them mDNS. The firmware passes such "
            "frames to a sleeping phone only when multicast filtering is off; "
            f"{_LOCK_INFERRED}"
        ),
        metrics={
            "multicast_broadcast_wakes": count,
            "multicast_broadcast_pct": share,
            "mdns_wakes": classes["mdns_multicast"],
        },
        evidence=[text.evidence(example.line.index, "Dst_mac is multicast")],
        recommendation=(
            "Find the apps holding a Wi-Fi multicast lock ('Multicast Locks held' "
            "in dumpsys wifi, 'WiFi Multicast Wakelock' in batterystats). Local "
            "discovery apps (device sync, casting, smart home) hold it; restrict "
            "their background use in Settings > Apps > (app) > App battery usage."
        ),
        followups=[
            (
                "Compare with the firmware's since-driver-start multicast share "
                "(fw_rx_multicast_broadcast_pct_since_driver_start)."
            ),
            "Check whether the lock is held while the screen is off.",
        ],
    )


# ----------------------------------------------------------------- charging


def _not_charging_run(
    samples: list[HealthdSample],
) -> tuple[float, HealthdSample] | None:
    """Return the longest plugged-in 'not charging' run below the level limit."""
    best: tuple[float, HealthdSample] | None = None
    start: HealthdSample | None = None
    for s in samples:
        stuck = s.plugged and s.status == STATUS_NOT_CHARGING
        stuck = stuck and s.level < NOT_CHARGING_MAX_LEVEL
        if stuck and start is None:
            start = s
        elif not stuck:
            start = None
        if start is not None:
            length = s.line.t - start.line.t
            if best is None or length > best[0]:
                best = (length, start)
    return best


@dataclass
class ChargeLog:
    """What the charger, fuel-gauge and step-charging drivers logged."""

    events: list[tuple[KernelLine, dict]] = field(default_factory=list)
    sources: Counter[str] = field(default_factory=Counter)
    qg: list[tuple[int, int]] = field(default_factory=list)
    metrics: dict[str, float | int] = field(default_factory=dict)
    usb_host: KernelLine | None = None
    jeita_off: KernelLine | None = None
    lines: int = 0


def _on_plugin(log: ChargeLog, kl: KernelLine, m: re.Match[str]) -> None:
    log.events.append((kl, {"event": f"usbin-plugin {m['state']}"}))


def _on_typec(log: ChargeLog, _kl: KernelLine, m: re.Match[str]) -> None:
    log.sources[m["desc"]] += 1


def _on_fcc(log: ChargeLog, kl: KernelLine, m: re.Match[str]) -> None:
    log.events.append((kl, {"event": "fcc vote", "fcc_ua": int(m["ua"])}))


def _on_vbatt(log: ChargeLog, kl: KernelLine, m: re.Match[str]) -> None:
    row = {
        "event": "vbatt limit check",
        "current_fcc_ua": int(m["ua"]),
        "vbatt_mv": round(int(m["uv"]) / 1000),
    }
    log.events.append((kl, row))


def _on_jeita(log: ChargeLog, _kl: KernelLine, m: re.Match[str]) -> None:
    log.metrics["jeita_temp_c"] = int(m["temp"]) / 10
    log.metrics["jeita_fcc_ua"] = int(m["ua"])


def _on_jeita_vote(log: ChargeLog, kl: KernelLine, m: re.Match[str]) -> None:
    if m["on"] == "true" and log.jeita_off is None:
        log.jeita_off = kl


def _on_cp(log: ChargeLog, _kl: KernelLine, m: re.Match[str]) -> None:
    log.metrics["charge_pump_skipped_ilim_ua"] = int(m["ua"])


def _on_qg(log: ChargeLog, _kl: KernelLine, m: re.Match[str]) -> None:
    log.qg.append((int(m["rbat"]), int(m["esr"])))


def _on_usb_peripheral(log: ChargeLog, kl: KernelLine, _m: re.Match[str]) -> None:
    if log.usb_host is None:
        log.usb_host = kl


_CHARGE_HANDLERS = (
    (_PLUGIN_RE, _on_plugin),
    (_TYPEC_RE, _on_typec),
    (_FCC_RE, _on_fcc),
    (_VBATT_LIMIT_RE, _on_vbatt),
    (_JEITA_RE, _on_jeita),
    (_JEITA_DISABLE_RE, _on_jeita_vote),
    (_CP_ILIM_RE, _on_cp),
    (_QG_RE, _on_qg),
    (_USB_PERIPHERAL_RE, _on_usb_peripheral),
)


def parse_charging(lines: list[KernelLine]) -> ChargeLog:
    """Collect the Qualcomm charger and fuel-gauge events of the kernel log."""
    log = ChargeLog()
    for kl in lines:
        if not _CHARGER_LINE_RE.search(kl.msg):
            continue
        log.lines += 1
        for regex, handler in _CHARGE_HANDLERS:
            if m := regex.search(kl.msg):
                handler(log, kl, m)
                break
    return log


def _charge_metrics(log: ChargeLog, samples: list[HealthdSample], m: dict) -> None:
    fcc = [row["fcc_ua"] for _, row in log.events if "fcc_ua" in row]
    charging = [s for s in samples if s.status == STATUS_CHARGING and s.current_ua]
    statuses = Counter(s.status for s in samples)
    m.update(
        charger_lines=log.lines,
        typec_source_reports=sum(log.sources.values()),
        typec_sources=", ".join(sorted(log.sources)),
        fcc_first_ua=fcc[0] if fcc else None,
        fcc_last_ua=fcc[-1] if fcc else None,
        fcc_max_ua=max(fcc) if fcc else None,
        vbatt_limit_checks=sum(1 for _, r in log.events if "vbatt_mv" in r),
        usb_data_to_host=log.usb_host is not None,
        healthd_samples=len(samples),
        healthd_status_counts=", ".join(
            f"st={k}:{v}" for k, v in sorted(statuses.items())
        ),
        **log.metrics,
    )
    if charging:
        last = [abs(s.current_ua or 0) for s in charging[-5:]]
        m["settled_charge_current_ua"] = round(statistics.median(last))
        m["level_first_charging"] = charging[0].level
        m["level_last_charging"] = charging[-1].level
    if log.qg:
        m.update(
            qg_rbat_mohm_min=min(r for r, _ in log.qg),
            qg_rbat_mohm_max=max(r for r, _ in log.qg),
            qg_esr_mohm_min=min(e for _, e in log.qg),
            qg_esr_mohm_max=max(e for _, e in log.qg),
        )


@analyzer("qcom_charging", requires=("dmesg",), after=("windows",))
def qcom_charging(ctx: Context) -> Result:
    """Summarise the charger, fuel-gauge and healthd lines of the kernel log."""
    klog = load_kernel_log(ctx)
    log = parse_charging(klog.lines)
    if not log.lines:
        msg = "no Qualcomm charger or fuel-gauge lines in the kernel log"
        raise SkipError(msg)
    samples = parse_healthd(klog.lines)
    result = Result("qcom_charging", window="log_coverage")
    _charge_metrics(log, samples, result.metrics)
    positions = [s.line.pos for s in samples]
    result.add_table(
        "charge_timeline",
        [
            {
                "kernel_s": round(kl.t, 3),
                **row,
                "level": samples[i - 1].level
                if (i := bisect_right(positions, kl.pos))
                else None,
            }
            for kl, row in log.events
        ],
    )
    result.notes.append(
        "healthd current sign conventions differ between devices; "
        "settled_charge_current_ua is the absolute value.",
    )
    result.findings.extend(
        _charging_findings(samples, log.usb_host, log.jeita_off, klog.text),
    )
    return result


def _charging_findings(
    samples: list[HealthdSample],
    usb_host: KernelLine | None,
    jeita_off: KernelLine | None,
    text: Text,
) -> list[Finding]:
    findings = []
    if usb_host is not None:
        findings.append(
            Finding(
                id="qcom_charging.charged-from-usb-host",
                title="The charge in the log came from a computer's USB port",
                symptom="info",
                severity="info",
                basis="measured",
                window="log_coverage",
                summary=(
                    "The phone started USB peripheral (device) mode when the "
                    "charger was attached, so the charging seen in the kernel log "
                    "is from a USB host such as the diagnosis computer. It says "
                    "nothing about the user's own charger."
                ),
                evidence=[text.evidence(usb_host.index)],
                recommendation=(
                    "To judge the user's charger, capture a bugreport after "
                    "charging on it without a USB data connection."
                ),
            ),
        )
    if jeita_off is not None:
        findings.append(
            Finding(
                id="qcom_charging.jeita-disabled",
                title="Charging was disabled for battery temperature",
                symptom="battery",
                severity="medium",
                basis="measured",
                window="log_coverage",
                summary=(
                    "The step-charging driver voted to disable charging (JEITA), "
                    "which happens when the battery is too hot or too cold."
                ),
                evidence=[text.evidence(jeita_off.index)],
                recommendation=(
                    "Charge at room temperature, out of direct sun and without a "
                    "thick case; check the thermal status during charging."
                ),
            ),
        )
    bad = next((s for s in samples if s.health in BAD_HEALTH), None)
    if bad is not None:
        findings.append(
            Finding(
                id="qcom_charging.battery-health-flag",
                title=f"healthd reported battery health '{BAD_HEALTH[bad.health]}'",
                symptom="battery",
                severity="medium",
                basis="measured",
                window="log_coverage",
                summary=(
                    f"A healthd sample reported health {bad.health} "
                    f"({BAD_HEALTH[bad.health]}) at level {bad.level} % and "
                    f"{bad.temp_c} degrees C."
                ),
                evidence=[text.evidence(bad.line.index)],
                recommendation=(
                    "Check the battery temperature and, if the flag persists, have "
                    "the battery inspected."
                ),
            ),
        )
    run = _not_charging_run(samples)
    if run is not None and run[0] >= NOT_CHARGING_MIN_S:
        length, start = run
        findings.append(
            Finding(
                id="qcom_charging.not-charging-while-plugged",
                title="The phone was plugged in but not charging",
                symptom="battery",
                severity="low",
                basis="measured",
                window="log_coverage",
                summary=(
                    f"healthd reported 'not charging' with a charger connected for "
                    f"{length:.0f} kernel seconds from level {start.level} %."
                ),
                evidence=[text.evidence(start.line.index)],
                recommendation=(
                    "Try another cable and charger; check for a charging limit "
                    "in Settings > Battery and for temperature throttling."
                ),
            ),
        )
    return findings


# ------------------------------------------------------- WLAN logging daemon


@analyzer("qcom_wlan_logging", after=("windows",))
def qcom_wlan_logging(ctx: Context) -> Result:
    """Report whether the Qualcomm WLAN log daemon cnss_diag runs.

    Its CPU on battery is reported by ``system_process_cpu_churn``; this
    analyzer adds the since-boot view, also when the daemon is below that
    analyzer's threshold.
    """
    rows = load_ps(ctx)
    if not rows:
        msg = "no process list"
        raise SkipError(msg)
    cpu_s = ps_cpu_by_name(rows, ["cnss_diag"]).get("cnss_diag")
    if cpu_s is None:
        msg = "cnss_diag is not running (no Qualcomm WLAN logging daemon)"
        raise SkipError(msg)
    result = Result("qcom_wlan_logging", window="since_boot")
    m = result.metrics
    m.update(cnss_diag_running=True, cnss_diag_cpu_s_since_start=round(cpu_s, 1))
    w = ctx.windows
    if w.dump_time and w.boot_time:
        uptime_s = (w.dump_time - w.boot_time).total_seconds()
        m["cnss_diag_cpu_pct_since_boot"] = pct(cpu_s, uptime_s)
    result.notes.append(
        "cnss_diag is Qualcomm's WLAN firmware log daemon, which a production "
        "phone does not need; system_process_cpu_churn reports its CPU on "
        "battery.",
    )
    return result
