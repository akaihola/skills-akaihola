"""Tests for the Qualcomm wake-packet, charging and WLAN-logging analyzers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from textwrap import dedent

import pytest
from androiddiag.model import Finding, Result, SkipError
from androiddiag.qcom import (
    dst_class,
    grid_fit,
    qcom_charging,
    qcom_wlan_logging,
    qcom_wow,
)
from androiddiag.windows import windows as fill_windows

KERNEL_LOG = "KERNEL LOG (dmesg)"
LOGCAT_KERNEL_LOG = "KERNEL LOG (logcat -b kernel -v threadtime -d *:v)"
OWN = "02:00:00:00:00:aa"
PEER = "02:00:00:00:00:10"
GATEWAY = "02:00:00:00:00:01"
MDNS_SENDER = "02:00:00:00:00:20"
MDNS = "01:00:5e:00:00:fb"
NEIGHBOURS = dedent(
    """\
    192.0.2.10 dev wlan0 lladdr 02:00:00:00:00:10 REACHABLE
    192.0.2.1 dev wlan0 lladdr 02:00:00:00:00:01 DELAY
    """,
)
CONNECTIVITY = dedent(
    """\
    NetworkAgentInfo{network{100} handle{1} ni{WIFI CONNECTED extra: }
      LinkProperties: {InterfaceName: wlan0 LinkAddresses: [ 192.0.2.50/24 ]
      Routes: [ 192.0.2.0/24 -> 0.0.0.0 wlan0 mtu 0,0.0.0.0/0 -> 192.0.2.1 wlan0 ]}
    """,
)
WIFI = dedent(
    """\
    Wlan Wake Reasons: totalCmdEventWake 0 totalDriverFwLocalWake 0 \
    totalRxDataWake 200 rxUnicast 150 rxMulticast 40 rxBroadcast 10 icmp 0 \
    icmp6 0 icmp6Ra 0 icmp6Na 0 icmp6Ns 0 ipv4RxMulticast 30 ipv6Multicast 10 \
    otherRxMulticast 0
    """,
)


def tod(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{seconds % 60:09.6f}"


Event = tuple[float, str, str, str, tuple[int, int] | None]


def wake_lines(t: float, event: Event) -> list[str]:
    """Return the lines the qcacld driver logs for one wake packet."""
    utc_s, src, dst, kind, ports = event
    prefix = f"<6>[{t:12.6f}] [soft_i][0x1a2b][{tod(utc_s)}] wlan: "
    lines = [
        prefix + "[0:F:WMA] WLAN triggered wakeup: BPF_ALLOW (39), vdev: 0 (STA)",
        prefix + f"[0:I:WMA] wma_wow_parse_data_pkt: 2172: Src_mac: {src}, "
        f"Dst_mac: {dst}",
    ]
    if kind:
        lines.append(prefix + f"[0:I:WMA] WOW Wakeup: {kind} rcvd")
    if ports:
        lines.append(
            prefix + f"[0:I:WMA] Pkt_len: 52, src_port: {ports[0]}, "
            f"dst_port: {ports[1]}",
        )
    return lines


def counters(t: float, uc: int, v4_mc: int) -> str:
    return (
        f"<1>[{t:12.6f}] [soft_i][0x1a2b][10:00:00.000000] wlan: [0:F:WMA] "
        f"uc:{uc} bc:1 v4_mc:{v4_mc} v6_mc:2 ra:0 ns:0 na:0 icmp:0 icmpv6:0"
    )


def wow_log(events: list[Event]) -> str:
    """Render (UTC seconds of day, src, dst, kind, ports) events as a kernel log."""
    lines = [counters(99.0, 100, 5)]
    for i, event in enumerate(sorted(events)):
        lines += wake_lines(100.0 + i * 0.5, event)
    lines.append(counters(200.0, 120, 10))
    return "\n".join(lines)


def busy_events() -> list[Event]:
    """A peer on a 3 s grid, a few gateway TCP packets and mDNS multicast."""
    events = []
    t = 36_000.0
    for gap in (3, 3, 6, 3, 3, 9, 3, 3, 3, 6, 3, 3, 3, 3, 6, 0):
        events.append((t, PEER, OWN, "", None))
        t += gap + 0.01
    events += [
        (36_001.5 + 10 * i, GATEWAY, OWN, "IPV4 TCP Packet", (443, 40000 + i))
        for i in range(4)
    ]
    events += [(36_002.2 + 11 * i, MDNS_SENDER, MDNS, "", None) for i in range(5)]
    return events


def as_logcat(log: str) -> str:
    """Rewrite printk lines the way logd prints them for 'logcat -b kernel'."""
    out = []
    for line in log.splitlines():
        m = re.match(r"(?:<\d>)?\[\s*([\d.]+)\] (.*)", line)
        assert m, line
        stamp = datetime(2026, 1, 15, 10) + timedelta(seconds=round(float(m[1]), 3))
        out.append(
            f"{stamp:%m-%d %H:%M:%S}.{stamp.microsecond // 1000:03d}  root     0"
            f"     0 I         : {m[2]}",
        )
    return "\n".join(out)


def wow_ctx(context_factory, events, log=None, title=KERNEL_LOG):
    return context_factory(
        sections={
            title: log or wow_log(events),
            "ARP CACHE (ip -4 neigh show)": NEIGHBOURS,
        },
        live={"connectivity": CONNECTIVITY, "wifi": WIFI},
    )


def test_wow_attribution_and_findings(context_factory):
    result = qcom_wow(wow_ctx(context_factory, busy_events()))
    m = result.metrics
    assert m["wake_packets"] == 25
    assert m["wake_triggers"] == 25
    assert m["first_wake_utc"] == "10:00:00.000"
    assert m["fw_uc_delta"] == 20
    assert m["fw_v4_mc_delta"] == 5
    assert m["fw_rx_multicast_broadcast_pct_since_driver_start"] == pytest.approx(25.0)
    assert m["multicast_broadcast_pct"] == pytest.approx(20.0)
    assert m["undecoded_wakes"] == 21
    senders = result.tables["wake_senders"]
    assert [(s["src_mac"], s["role"], s["wakes"]) for s in senders] == [
        (PEER, "lan_peer", 16),
        (MDNS_SENDER, "unknown", 5),
        (GATEWAY, "gateway", 4),
    ]
    assert senders[0]["period_s"] == pytest.approx(3.0, abs=0.05)
    assert m["top_sender_period_s"] == pytest.approx(3.0, abs=0.05)
    tables = result.tables
    destinations = {r["destination"]: r["wakes"] for r in tables["wake_destinations"]}
    assert destinations == {"unicast_own": 20, "mdns_multicast": 5}
    protocols = {r["protocol"]: r["wakes"] for r in result.tables["wake_protocols"]}
    assert protocols["IPV4 TCP Packet 443->40000"] == 1
    ids = {f.id: f for f in result.findings}
    dominant = ids["qcom_wow.dominant-sender"]
    assert dominant.severity == "high"
    assert "3.00 s grid" in dominant.summary
    assert PEER not in dominant.summary  # addresses stay in the table
    assert "qcom_wow.multicast-wakes" in ids
    assert any("personal data" in n for n in result.notes)


def _other_view(fid: str, **metrics) -> Result:
    finding = Finding(fid, "t", "battery", "medium", "measured", "on_battery", "s.")
    finding.metrics = metrics
    return Result(fid.split(".", maxsplit=1)[0], findings=[finding])


@pytest.mark.parametrize(("period", "linked"), [(2.99, True), (10.0, False)])
def test_wow_links_other_views_of_the_same_wakes(context_factory, period, linked):
    """The sender confirms periodic resumes; the multicast lock owns its wakes."""
    ctx = wow_ctx(context_factory, busy_events())
    periodic = _other_view("wake_periodicity.periodic_sender", period_s=period)
    lock = _other_view("wifi_multicast.lock_held", multicast_pct_of_battery=93.7)
    ctx.results.update(wake_periodicity=periodic, wifi_multicast=lock)
    ids = {f.id: f for f in qcom_wow(ctx).findings}
    sender = ids["qcom_wow.dominant-sender"]
    assert ("This confirms wake_periodicity" in sender.summary) is linked
    assert (sender.related, periodic.findings[0].related) == (
        (["wake_periodicity.periodic_sender"], ["qcom_wow.dominant-sender"])
        if linked
        else ([], [])
    )
    multicast = ids["qcom_wow.multicast-wakes"]
    assert "held 94% of the time on battery (wifi_multicast)" in multicast.summary
    assert "inferred" not in multicast.summary
    assert multicast.related == ["wifi_multicast.lock_held"]
    assert lock.findings[0].related == ["qcom_wow.multicast-wakes"]


def test_wow_quiet_when_wakes_are_spread_and_unicast(context_factory):
    events = [
        (36_000.0 + 7.3 * i + j, f"02:00:00:00:00:{j:02x}", OWN, "", None)
        for i in range(4)
        for j in range(1, 6)
    ]
    result = qcom_wow(wow_ctx(context_factory, events))
    assert result.metrics["top_sender_share_pct"] == pytest.approx(20.0)
    assert result.metrics["multicast_broadcast_pct"] == pytest.approx(0.0)
    assert not result.findings


def test_wow_skips_on_other_vendors(context_factory):
    log = "<6>[  10.000000] PM: suspend entry (deep)\n<6>[  10.100000] PM: suspend exit"
    ctx = context_factory(sections={KERNEL_LOG: log})
    with pytest.raises(SkipError, match="WOW"):
        qcom_wow(ctx)
    with pytest.raises(SkipError, match="charger"):
        qcom_charging(ctx)


def test_wow_skips_without_kernel_log(context_factory):
    with pytest.raises(SkipError, match="no kernel log"):
        qcom_wow(context_factory(live={"battery": "level: 50"}))


def test_grid_fit_finds_the_period_and_rejects_noise():
    on_grid = grid_fit([3.0, 3.02, 6.01, 2.98, 9.0, 3.0, 6.0, 3.01, 12.0, 3.0, 3.0])
    assert on_grid is not None
    assert on_grid[0] == pytest.approx(3.0, abs=0.05)
    assert on_grid[1] == pytest.approx(100.0)
    noise = grid_fit([1.7, 4.4, 7.3, 2.2, 5.9, 11.3, 3.7, 8.6, 1.3, 13.9, 6.6])
    assert noise is not None
    assert noise[1] - noise[2] < 40
    assert grid_fit([3.0, 3.0]) is None


@pytest.mark.parametrize(
    ("dst", "expected"),
    [
        (OWN, "unicast_own"),
        ("02:00:00:00:00:bb", "unicast_other"),
        ("ff:ff:ff:ff:ff:ff", "broadcast"),
        (MDNS, "mdns_multicast"),
        ("33:33:00:00:00:fb", "mdns_multicast"),
        ("01:00:5e:7f:ff:fa", "ipv4_multicast"),
        ("33:33:00:00:00:01", "ipv6_multicast"),
    ],
)
def test_dst_class(dst, expected):
    assert dst_class(dst, OWN) == expected


# Lines are shortened; the parsers need only the fields shown.
CHARGE_LOG = dedent(
    """\
    [499.000000] healthd: battery l=60 v=3900 t=28.0 h=2 st=3 c=-200000 chg=
    [500.000000] [SMBLIB5]: smblib_usb_plugin_locked: IRQ: usbin-plugin attached
    [500.100000] [PE]:usbpd_process_typec_mode: Type-C Source (medium - 1.5A) connected
    [500.200000] [SMB5]: smb5_usb_main_set_prop: set final main_fcc = 1500000
    [500.300000] [PE]:start_usb_peripheral: start usb peripheral with cc=1
    [500.400000] healthd: battery l=60 v=4100 t=28.5 h=2 st=2 c=1200000 chg=u
    [520.000000] QCOM-STEPCHG: handle_vbatt_limit: f=1500000, v=4410000
    [520.001000] [SMB5]: smb5_usb_main_set_prop: set final main_fcc = 1100000
    [521.000000] QG-K: process_udata_work: userspace write rbat=120, esr=80
    [530.000000] healthd: battery l=61 v=4400 t=29.0 h=2 st=2 c=1100000 chg=u
    """,
)
CHARGE_FAULTS = dedent(
    """\
    [540.000000] QCOM-STEPCHG: handle_jeita: handle_jeita ,temp:465, fcc_ua:0
    [540.000100] QCOM-STEPCHG: handle_jeita: FCC vote chg_disable_votable:true
    [541.000000] healthd: battery l=61 v=4200 t=46.5 h=3 st=4 c=0 chg=u
    [700.000000] healthd: battery l=61 v=4200 t=40.0 h=2 st=4 c=0 chg=u
    """,
)


def test_charging_session(context_factory):
    result = qcom_charging(context_factory(sections={KERNEL_LOG: CHARGE_LOG}))
    m = result.metrics
    assert (m["fcc_first_ua"], m["fcc_last_ua"], m["fcc_max_ua"]) == (
        1_500_000,
        1_100_000,
        1_500_000,
    )
    assert m["vbatt_limit_checks"] == 1
    assert m["typec_sources"] == "medium - 1.5A"
    assert m["settled_charge_current_ua"] == 1_150_000
    assert (m["qg_rbat_mohm_min"], m["qg_esr_mohm_max"]) == (120, 80)
    assert m["healthd_status_counts"] == "st=2:2, st=3:1"
    events = [(r["event"], r["level"]) for r in result.tables["charge_timeline"]]
    assert events[0] == ("usbin-plugin attached", 60)
    assert [f.id for f in result.findings] == ["qcom_charging.charged-from-usb-host"]
    assert result.findings[0].severity == "info"


def test_charging_faults_fire(context_factory):
    log = CHARGE_LOG.replace("start_usb_peripheral", "example_event") + CHARGE_FAULTS
    result = qcom_charging(context_factory(sections={KERNEL_LOG: log}))
    ids = [f.id for f in result.findings]
    assert ids == [
        "qcom_charging.jeita-disabled",
        "qcom_charging.battery-health-flag",
        "qcom_charging.not-charging-while-plugged",
    ]
    assert result.metrics["jeita_temp_c"] == pytest.approx(46.5)
    assert result.metrics["usb_data_to_host"] is False


def test_wow_and_charging_read_a_logcat_kernel_log(context_factory):
    """Phones with ro.logd.kernel=true dump the kernel log through logcat."""
    log = as_logcat(wow_log(busy_events()) + "\n" + CHARGE_LOG)
    ctx = wow_ctx(context_factory, [], log=log, title=LOGCAT_KERNEL_LOG)
    wow = qcom_wow(ctx)
    assert wow.metrics["wake_packets"] == 25
    assert wow.metrics["first_wake_utc"] == "10:00:00.000"
    assert {f.id for f in wow.findings} == {
        "qcom_wow.dominant-sender",
        "qcom_wow.multicast-wakes",
    }
    charging = qcom_charging(ctx)
    assert charging.metrics["fcc_first_ua"] == 1_500_000
    assert charging.metrics["healthd_status_counts"] == "st=2:2, st=3:1"
    assert [f.id for f in charging.findings] == ["qcom_charging.charged-from-usb-host"]


PS_LIVE = dedent(
    """\
      PID  PPID USER            RSS     VSZ     TIME S NAME
        2     0 root
      410     1 root           2100  9000000 00:02:30 S ueventd
     1200     1 system         3000  9100000 00:20:00 S cnss_diag
    """,
)
# Column spacing is narrowed; the parser splits on whitespace.
PS_THREADS = dedent(
    """\
    LABEL USER PID TID PPID VSZ RSS WCHAN ADDR S PRI NI RTPRIO SCH PCY TIME CMD
    u:r:x:s0 system 1200 1200 1 9100 3000 0 0 S 19 0 - 0 fg 00:15:00 cnss_diag
    u:r:x:s0 system 1200 1201 1 9100 3000 0 0 S 19 0 - 0 fg 00:05:00 diag_reader
    u:r:x:s0 system 1300 1300 1 9100 3000 0 0 S 19 0 - 0 fg 00:01:00 other
    """,
)
CLOCK = dedent(
    """\
    1768478400
    2026-01-15 12:00:00 +0200
    36000.00 140000.00
    """,
)


def logging_ctx(context_factory, ps_key="ps", ps=PS_LIVE):
    if ps_key == "ps":
        ctx = context_factory(live={"clock": CLOCK, "ps": ps})
    else:
        ctx = context_factory(
            live={"clock": CLOCK},
            sections={"PROCESSES AND THREADS (ps -A -T -Z)": ps},
        )
    fill_windows(ctx)
    return ctx


def test_cnss_diag_since_boot_cpu_without_a_finding(context_factory):
    result = qcom_wlan_logging(logging_ctx(context_factory))
    m = result.metrics
    assert m["cnss_diag_running"] is True
    assert m["cnss_diag_cpu_s_since_start"] == 1200
    assert m["cnss_diag_cpu_pct_since_boot"] == pytest.approx(3.3)
    # system_process_cpu_churn owns the finding about its CPU on battery.
    assert not result.findings
    assert any("system_process_cpu_churn" in n for n in result.notes)


def test_cnss_diag_reads_the_thread_listing(context_factory):
    threads = logging_ctx(context_factory, ps_key="ps_threads", ps=PS_THREADS)
    assert qcom_wlan_logging(threads).metrics["cnss_diag_cpu_s_since_start"] == 1200


def test_cnss_diag_skips(context_factory):
    with pytest.raises(SkipError, match="no process list"):
        qcom_wlan_logging(context_factory(live={"battery": "level: 50"}))
    other = PS_LIVE.replace("cnss_diag", "example_d")
    with pytest.raises(SkipError, match="not running"):
        qcom_wlan_logging(context_factory(live={"ps": other}))
