"""Tests for the radio analyzers, on invented dumps only.

Addresses come from documentation ranges (192.0.2.x, 198.51.100.x) and
locally administered MACs (02:00:00:xx:xx:xx); packages are com.example.*.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from textwrap import dedent
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
from androiddiag.model import SkipError, Windows
from androiddiag.radio import (
    background_scanning_sensors_location,
    cellular_radio,
    ims_handover,
    network_traffic,
    vpn,
    wifi_roaming,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

START = datetime(2026, 1, 15, 7, 0, 0)
WINDOWS = Windows(
    dump_time=datetime(2026, 1, 15, 12, 30, 0),
    since_charge_start=START,
    on_battery_s=5 * 3600,
    on_battery_at_capture=False,
    plugged_at=START + timedelta(hours=5),
    utc_offset="+0200",
)
PACKAGES = dedent(
    """\
    package:com.example.chatty uid:10101
    package:com.example.wearable uid:10102
    package:com.example.motion uid:10103
    package:com.example.meshvpn uid:10104
    package:com.example.tracker uid:10105
    """,
)


def _offset(seconds: float) -> str:
    """Format a history offset like batterystats: +1h05m05s381ms."""
    ms = round(seconds * 1000)
    if not ms:
        return "0"
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    if h >= 24:
        return f"+{h // 24}d{h % 24:02d}h{m:02d}m{s:02d}s{ms:03d}ms"
    if h:
        return f"+{h}h{m:02d}m{s:02d}s{ms:03d}ms"
    if m:
        return f"+{m}m{s:02d}s{ms:03d}ms"
    return f"+{s}s{ms:03d}ms"


def history(events: Sequence[tuple[float, str]], end_s: float = 5 * 3600) -> str:
    """Build a battery history: reset at 07:00, unplugged, plugged at ``end_s``."""
    lines = [
        "Battery History (1% used, 10KB used of 4096KB, 10 strings using 1KB):",
        "                    0 (14) RESET:TIME: 2026-01-15-07-00-00",
        (
            "                    0 (2) 100 status=discharging +running +screen"
            " +plugged phone_signal_strength=good wifi_suppl=completed"
        ),
        "                    0 (2) 100 -plugged",
    ]
    for seconds, tokens in [*sorted(events), (end_s, "plug=ac +plugged")]:
        lines.append(f"{_offset(seconds):>21} (1) 095 {tokens}")
    return "\n".join([*lines, "", "Per-PID Stats:", ""])


CHARGED = dedent(
    """\
    Statistics since last charge:
      System starts: 2, currently on battery: false
      Time on battery: 5h 0m 0s 0ms (99,0%) realtime, 3h 0m 0s 0ms (60,0%) uptime
      Connectivity changes: 12

      CONNECTIVITY POWER SUMMARY START
      Logging duration for connectivity statistics: 5h 0m 0s 0ms
      Cellular Statistics:
         Cellular kernel active time: 30m 0s 0ms (10,0%)
         Cellular Sleep time:  4h 0m 0s 0ms (80,0%)
         Cellular Idle time:   30m 0s 0ms (10,0%)
         Cellular Rx time:     20m 0s 0ms (6,7%)
         Cellular Tx time:
           less than 0dBm:  1s 0ms (0,0%)
           0dBm to 8dBm:  10s 0ms (0,1%)
           8dBm to 15dBm:  20s 0ms (0,1%)
           15dBm to 20dBm:  30s 0ms (0,2%)
           above 20dBm:  2m 0s 0ms (0,7%)
         Cellular Battery drain: 80.5mAh
         Cellular data received: 50,00KB
         Cellular data sent: 30,00KB
         Cellular packets received: 100
         Cellular packets sent: 120
         Cellular Radio Access Technology:
           lte 5h 0m 0s 0ms (100,0%)
         Cellular Rx signal strength (RSRP):
           none (less than -128dBm):  15m 0s 0ms (5,0%)
           poor (-128dBm to -118dBm):  1h 0m 0s 0ms (20,0%)
           moderate (-118dBm to -108dBm):  1h 45m 0s 0ms (35,0%)
           good (-108dBm to -98dBm):  2h 0m 0s 0ms (40,0%)
      Wifi Statistics:
         Wifi kernel active time: 5h 0m 0s 0ms (100,0%)
         WiFi Scan time:  1m 0s 0ms (0,3%)
         Wifi data received: 10,00MB
         Wifi data sent: 2,00MB
         Wifi packets received: 50000
         Wifi packets sent: 20000
         Wifi states:
           sta 5h 0m 0s 0ms (100,0%)
         Wifi supplicant states:
           completed 5h 0m 0s 0ms (100,0%)
         Wifi Rx signal strength (RSSI):
             moderate (-77.5dBm to -66.25dBm): 30m 0s 0ms (10,0%)
             good (-66.25dBm to -55dBm): 2h 0m 0s 0ms (40,0%)
             great (greater than -55dBm): 2h 30m 0s 0ms (50,0%)
      CONNECTIVITY POWER SUMMARY END

      Bluetooth scan time: 5h 0m 0s 0ms

      Estimated power use (mAh):
        Capacity: 3000, Computed drain: 400, actual drain: 400-420
        Global
          screen: 100 apps: 100 duration: 40m 0s 0ms
          bluetooth: 3.50 apps: 0 duration: 10m 0s 0ms
          mobile_radio: 40.0 apps: 24.0 duration: 30m 0s 0ms
          sensors: 1.00 apps: 1.00
          gnss: 0.100 apps: 0.100
        UID 0: 30.0 ( cpu=10.0 mobile_radio=20.0 (20m 0s 0ms) )
        UID u0a101: 9.00 fgs: 9.00 ( cpu=4.00 mobile_radio=4.00 (4m 0s 0ms) wifi=1.00 (1m 0s 0ms) )

      Per-app mobile ms per packet:
        Uid 0: 30000 (40 packets over 20m 0s 0ms) 10x
        Uid u0a101: 200 (10 packets over 2s 0ms) 2x
        TOTAL TIME: 20m 2s 0ms (0,0%)

      All kernel wake locks:
      Kernel Wake lock wlan_roam_ho_wl: 30s 0ms (50 times) realtime

      All partial wake locks:
      Wake lock 1000 *alarm*: 1s 0ms (5 times) max=300 actual=1000 realtime

      0:
        Mobile network: 0B received, 2,50KB sent (packets 0 received, 40 sent)
        Mobile radio active: 20m 0s 0ms (66,7%) 10x @ 30000 mspp
      u0a101:
        Wi-Fi network: 3,20MB received, 3,00MB sent (packets 18000 received, 18500 sent)
        Mobile radio active: 2s 0ms (0,0%) 2x @ 200 mspp
      u0a102:
        Bluetooth Scan (total blamed realtime): 1h 0m 0s 0ms  (0 times) (currently running)
        Bluetooth Scan (total actual realtime): 5h 0m 0s 0ms  (0 times) (currently running)
        Bluetooth Scan Results: 0 (0 in background)
      u0a103:
        Wi-Fi network: 30,00KB received, 28,00KB sent (packets 400 received, 390 sent)
        Sensor 12: 4h 0m 0s 0ms blamed realtime, 4h 30m 0s 0ms realtime (3 times), 4h 0m 0s 0ms background (3 times)
      u0a104:
        Wi-Fi network: 2,00MB received, 2,10MB sent (packets 12000 received, 12500 sent)
    """,  # ruff: ignore[line-too-long]
)

# An older batterystats layout with decimal points, a small active share and
# the "Phone signal levels" block instead of the connectivity summary.
CHARGED_OLD = dedent(
    """\
    Statistics since last charge:
      Phone signal levels:
        none 0ms (0.0%) 0x
        poor 5m 0s 0ms (1.7%) 2x
        moderate 1h 0m 0s 0ms (20.0%) 4x
        good 3h 55m 0s 0ms (78.3%) 5x
      Signal scanning time: 0ms
      Radio types:
        lte 5h 0m 0s 0ms (100.0%) 1x
      Mobile radio active time: 3m 0s 0ms (1.0%) 12x
      Mobile radio active unknown time: 10s 0ms (0.1%) 1x

      Estimated power use (mAh):
        Global
          mobile_radio: 3.00 apps: 2.00 duration: 3m 0s 0ms
    """,
)


def _ctx(context_factory, live=None, **bugreport):
    return context_factory(live=live, packages=PACKAGES, windows=WINDOWS, **bugreport)


def _ids(result) -> set[str]:
    return {f.id for f in result.findings}


# ---------------------------------------------------------------------------
# cellular_radio

RADIO_EVENTS = [
    (600, "-screen"),
    (900, "device_idle=full"),
    (3600, "+mobile_radio"),
    (3630, "-mobile_radio"),
    (7200, "+mobile_radio"),
    (7220, "-mobile_radio"),
    (10800, "+mobile_radio +cellular_high_tx_power"),
    (10815, "-mobile_radio"),
    (14400, "+mobile_radio"),
    (14410, "-mobile_radio"),
]


def test_cellular_counters_history_and_findings(context_factory):
    ctx = _ctx(
        context_factory,
        live={
            "batterystats_charged": CHARGED,
            "batterystats": history(RADIO_EVENTS),
            "settings": "mobile_data_always_on=1\n",
        },
    )
    result = cellular_radio(ctx)
    m = result.metrics
    assert m["radio_active_s"] == 1800
    assert m["radio_active_pct"] == pytest.approx(10.0)
    assert m["signal_level_pct"] == {
        "none": 5.0,
        "poor": 20.0,
        "moderate": 35.0,
        "good": 40.0,
    }
    assert m["rat_pct"] == {"lte": 100.0}
    assert m["cellular_rx_bytes"] == 50 * 1024
    assert m["modem_tx_by_level_s"]["above 20dBm"] == pytest.approx(120.0)
    assert m["mobile_radio_apps_modelled_mah"] == pytest.approx(24.0)
    assert m["mobile_radio_unattributed_modelled_mah"] == pytest.approx(16.0)
    assert m["radio_activations_on_battery"] == 4
    assert m["radio_active_on_battery_min"] == pytest.approx(75 / 60, abs=0.01)
    assert m["radio_active_screen_off_min"] == pytest.approx(75 / 60, abs=0.01)
    assert m["mobile_data_always_on"] is True
    top = result.tables["uid_mobile_radio"][0]
    assert top["name"] == "kernel (UID 0)"
    assert top["ms_per_packet"] == 30000
    assert _ids(result) == {
        "cellular_radio.active_for_little_data",
        "cellular_radio.weak_coverage",
        "cellular_radio.high_tx_power",
    }
    active = next(f for f in result.findings if f.id.endswith("little_data"))
    assert active.severity == "medium"
    assert "kernel (UID 0)" in active.summary
    assert active.evidence[0].ref.startswith("live/batterystats_charged.txt:")


def test_modelled_radio_cost_splits_active_time_from_standby(context_factory):
    # Apps hold the radio 24 of its 30 active minutes and are billed 24 mAh,
    # so active time costs 1 mAh/min: 30 mAh, 6 of them billed to no app,
    # and only the remaining 10 mAh are idle or sleep (standby) cost.
    live = {"batterystats_charged": CHARGED, "batterystats": history(RADIO_EVENTS)}
    result = cellular_radio(_ctx(context_factory, live=live))
    m = result.metrics
    assert m["mobile_radio_app_active_s_modelled"] == pytest.approx(1440.0)
    assert m["mobile_radio_active_s_modelled"] == pytest.approx(1800.0)
    assert m["mobile_radio_active_modelled_mah"] == pytest.approx(30.0)
    assert m["mobile_radio_unattributed_active_modelled_mah"] == pytest.approx(6.0)
    assert m["mobile_radio_inactive_modelled_mah"] == pytest.approx(10.0)
    active = next(f for f in result.findings if f.id.endswith("little_data"))
    assert "30.0 mAh for radio-active time" in active.summary
    assert "10.0 mAh for the modem idling or asleep" in active.summary
    assert "standby camping" not in active.summary


def test_radio_split_is_skipped_when_apps_cost_more_than_the_model(context_factory):
    # With measured modem energy, app shares do not follow active time.
    charged = CHARGED.replace(
        "mobile_radio: 40.0 apps: 24.0", "mobile_radio: 26.0 apps: 24.0"
    )
    live = {"batterystats_charged": charged}
    result = cellular_radio(_ctx(context_factory, live=live))
    assert "mobile_radio_inactive_modelled_mah" not in result.metrics
    active = next(f for f in result.findings if f.id.endswith("little_data"))
    assert "24.0 mAh is billed to apps" in active.summary


def test_cellular_old_layout_with_decimal_points_stays_quiet(context_factory):
    ctx = _ctx(context_factory, live={"batterystats_charged": CHARGED_OLD})
    result = cellular_radio(ctx)
    m = result.metrics
    assert m["radio_active_s"] == 180
    assert m["radio_active_pct"] == pytest.approx(1.0)
    assert m["radio_active_count"] == 12
    assert m["radio_active_unknown_s"] == 10
    assert m["signal_level_pct"]["good"] == pytest.approx(78.3)
    assert m["rat_pct"] == {"lte": 100.0}
    assert result.findings == []


def test_cellular_reads_the_full_dump_when_charged_is_missing(context_factory):
    full = history(RADIO_EVENTS) + "\n" + CHARGED
    result = cellular_radio(_ctx(context_factory, live={"batterystats": full}))
    assert result.metrics["radio_active_pct"] == pytest.approx(10.0)
    assert result.metrics["radio_activations_on_battery"] == 4


def test_cellular_reads_history_offsets_with_days(context_factory):
    # Histories longer than a day print offsets such as +1d01h00m00s000ms.
    events = [(600, "-screen"), (90_000, "+mobile_radio"), (90_030, "-mobile_radio")]
    long_battery = Windows(
        since_charge_start=START, on_battery_s=100_000, utc_offset="+0200"
    )
    ctx = context_factory(
        live={"batterystats": history(events, end_s=100_000)},
        packages=PACKAGES,
        windows=long_battery,
    )
    result = cellular_radio(ctx)
    assert result.metrics["radio_activations_on_battery"] == 1
    assert result.tables["longest_radio_activations"][0]["start"] == (
        "2026-01-16 08:00:00"
    )
    assert not any("unreadable" in note for note in result.notes)


def test_cellular_reads_a_checkin_only_history(context_factory):
    epoch_ms = int(datetime(2026, 1, 15, 5, 0, tzinfo=UTC).timestamp() * 1000)
    checkin = "\n".join(
        [
            "9,0,i,vers,36,214,TEST.1,TEST.1",
            f"9,h,0:RESET:TIME:{epoch_ms}",
            "9,h,0,Bl=100,+S,+BP,Pss=3",
            "9,h,0,-BP",
            "9,h,600000,-S",
            "9,h,3000000,+Pr",
            "9,h,1800000,-Pr",
            "9,h,12600000,+BP",
        ],
    )
    ctx = _ctx(context_factory, live={"batterystats_checkin": checkin + "\n"})
    result = cellular_radio(ctx)
    m = result.metrics
    assert m["radio_activations_on_battery"] == 1
    assert m["radio_active_screen_off_min"] == pytest.approx(30.0)
    row = result.tables["longest_radio_activations"][0]
    assert row["start"] == "2026-01-15 08:00:00"
    assert row["ref"] == "live/batterystats_checkin.txt:6"
    # The cited checkin row reads like the text dump.
    finding = result.findings[0]
    assert finding.id == "cellular_radio.active_for_little_data"
    assert finding.evidence[-1].ref == row["ref"]
    assert finding.evidence[-1].excerpt == "08:00:00 +mobile_radio"


def test_mobile_data_always_on_from_the_bugreport_settings_dump(context_factory):
    settings = dedent(
        """\
        GLOBAL SETTINGS (user 0)
        version: 1 (OK)
        _id:7 name:mobile_data_always_on pkg:android value:1 default:1 defaultSystemSet:true
        """,  # ruff: ignore[line-too-long]
    )
    ctx = _ctx(
        context_factory,
        live={"batterystats_charged": CHARGED},
        services={"settings": settings},
    )
    assert cellular_radio(ctx).metrics["mobile_data_always_on"] is True


def test_cellular_skips_without_batterystats(context_factory):
    with pytest.raises(SkipError):
        cellular_radio(_ctx(context_factory, live={"settings": "x=1\n"}))


# ---------------------------------------------------------------------------
# wifi_roaming


def _assoc_events(count: int, start_s: float = 1800, step_s: float = 180):
    return [(start_s + i * step_s, "wifi_suppl=associated") for i in range(count)]


def _l2_log(count: int, start: datetime, step_s: float = 180) -> str:
    bssids = ["02:00:00:00:01:0a", "02:00:00:00:01:0b", "02:00:00:00:02:0a"]
    lines = ["Recently active IpClient logs:", "IpClient.wlan0"]
    for i in range(count):
        ts = (start + timedelta(seconds=i * step_s)).isoformat(timespec="microseconds")
        lines.append(
            f"    {ts} - CMD_UPDATE_L2INFORMATION wlan0/20 0 0 "
            "Layer2InformationParcelable{l2Key: Wexample, cluster: Gexample, "
            f"bssid: {bssids[i % 3]}}} [rcvd_in=RunningState, proc_in=StartedState]",
        )
    return "\n".join(lines) + "\n"


DMESG = dedent(
    """\
    <6>[90.000001] [schedu][0x0][05:25:00.000001] wlan: [1:I:HDD] connected
    <6>[100.000001] [schedu][0x1][05:30:00.000001] wlan: [1:I:WMA] [05:29:59.000000] [ROAM_TRIGGER]: VDEV[0] Reason: "LOW RSSI"  Cur_Rssi threshold:75 Current AP RSSI: 74
    <6>[100.000002] [schedu][0x2][05:30:00.000002] wlan: [1:I:WMA] [05:30:00.000000] [ROAM_RESULT]: VDEV[0] SUCCESS
    <6>[101.000001] [schedu][0x3][05:31:00.000001] wlan: [1:I:WMA] [05:30:59.000000] [ROAM_TRIGGER]: VDEV[0] Reason: "LOW RSSI" Sub-Reason: FULL SCAN Cur_Rssi threshold:82 Current AP RSSI: 80
    <6>[101.000002] [schedu][0x4][05:31:00.000002] wlan: [1:I:WMA] [05:31:00.000000] [ROAM_RESULT]: VDEV[0] FAILED Reason: SCAN NOT STARTED
    <6>[700.000001] [schedu][0x5][05:40:00.000001] wlan: [1:I:HDD] scan done
    """,  # ruff: ignore[line-too-long]
)


def test_wifi_roaming_fires_for_stationary_ping_pong(context_factory):
    events = [(600, "-screen"), (900, "device_idle=full"), *_assoc_events(60)]
    irm = '+wake_lock=1073:"IpReachabilityMonitor.wlan0"'
    events += [(e[0] + 0.03, irm) for e in events[2:12]]
    ctx = _ctx(
        context_factory,
        live={
            "batterystats": history(events),
            "batterystats_charged": CHARGED,
            "network_stack": _l2_log(60, START + timedelta(seconds=1800)),
        },
        sections={"KERNEL LOG (dmesg)": DMESG},
    )
    result = wifi_roaming(ctx)
    m = result.metrics
    assert m["associations_on_battery"] == 60
    assert m["associations_deep_idle"] == 60
    assert m["associations_per_h_deep_idle"] > 5
    assert m["bssid_changes_on_battery"] == 60
    assert m["distinct_bssids_on_battery"] == 3
    assert m["access_points_on_battery"] == 2
    assert m["irm_within_1s_of_association_pct"] == pytest.approx(100.0)
    assert m["roam_triggers_kernel_sample"] == 2
    assert m["roam_trigger_rssi_dbm_min"] == -80
    assert m["roam_trigger_rssi_dbm_max"] == -74
    results = m["roam_results_kernel_sample"]
    assert results == {"SUCCESS": 1, "FAILED: SCAN NOT STARTED": 1}
    assert m["roam_handoff_wakelock_count"] == 50
    # The sample spans the Wi-Fi driver lines, not just the roam lines.
    assert m["kernel_log_wifi_span_s"] == 15 * 60
    assert any("span 15m00s (driver clock 05:25:00-05:40:00" in n for n in result.notes)
    assert m["wifi_rssi_level_pct"]["great"] == pytest.approx(50.0)
    finding = next(f for f in result.findings if f.id.endswith("stationary_roaming"))
    assert finding.severity == "medium"
    assert "in deep idle" in finding.summary
    assert all("02:00:00" not in e.excerpt for e in finding.evidence)
    labels = {r["access_point"] for r in result.tables["access_points"]}
    assert labels == {"AP-1", "AP-2"}


def test_kernel_log_span_crosses_midnight_and_tolerates_jitter(context_factory):
    trigger = '[ROAM_TRIGGER]: VDEV[0] Reason: "LOW RSSI" Current AP RSSI: 70'
    stamps = ["23:59:00", "23:59:59", "23:59:58", "00:00:30", "00:01:00"]
    dmesg = "".join(
        f"<6>[{i}.000001] [schedu][0x{i}][{t}.000001] wlan: [1:I:WMA] {trigger}\n"
        for i, t in enumerate(stamps)
    )
    ctx = _ctx(
        context_factory,
        live={"batterystats": history([])},
        sections={"KERNEL LOG (dmesg)": dmesg},
    )
    result = wifi_roaming(ctx)
    assert result.metrics["kernel_log_wifi_span_s"] == 120


def test_wifi_roaming_quiet_for_a_few_roams(context_factory):
    events = [(600, "-screen"), (900, "device_idle=full"), *_assoc_events(3)]
    result = wifi_roaming(_ctx(context_factory, live={"batterystats": history(events)}))
    assert result.metrics["associations_deep_idle"] == 3
    assert result.findings == []


def test_connectivity_changes_explained_as_capability_updates(context_factory):
    events = []
    for i in range(60):
        t = 60 + i * 30
        events += [(t, "wifi_signal_strength=3"), (t + 0.05, 'conn=17:"CONNECTED"')]
    charged = CHARGED.replace("Connectivity changes: 12", "Connectivity changes: 60")
    ctx = _ctx(
        context_factory,
        live={"batterystats": history(events), "batterystats_charged": charged},
    )
    result = wifi_roaming(ctx)
    assert result.metrics["conn_events_after_wifi_change_pct"] == pytest.approx(100.0)
    assert result.metrics["rssi_updates_screen_on_pct"] == pytest.approx(100.0)
    finding = next(f for f in result.findings if "connectivity_changes" in f.id)
    assert finding.severity == "info"
    assert finding.basis == "inferred"


def test_wifi_without_network_fires(context_factory):
    charged = CHARGED.replace(
        "sta 5h 0m 0s 0ms (100,0%)",
        "no_net 2h 0m 0s 0ms (40,0%)\n       sta 3h 0m 0s 0ms (60,0%)",
    )
    ctx = _ctx(
        context_factory,
        live={"batterystats_charged": charged, "batterystats": history([])},
    )
    result = wifi_roaming(ctx)
    assert result.metrics["wifi_on_no_network_pct"] == pytest.approx(40.0)
    assert "wifi_roaming.wifi_without_network" in _ids(result)


def test_wifi_roaming_skips_without_inputs(context_factory):
    with pytest.raises(SkipError):
        wifi_roaming(_ctx(context_factory, live={"settings": "x=1\n"}))


# ---------------------------------------------------------------------------
# ims_handover

IMS_STARTS = [START + timedelta(hours=h) for h in (1, 2, 3)]


def _registry_log() -> str:
    apn = (
        "APN Setting: [ApnSetting] Example IMS, 1, 00101, ims, , null, , null, null, "
        "0, ims, IPV4V6, IPV4V6, true, 0, false, link properties: {InterfaceName: x}"
    )
    lines = ["Local logs:"]
    for start in IMS_STARTS:
        for delta, state, transport, rat in (
            (0, "HANDOVERINPROGRESS", "WWAN", "LTE"),
            (2, "CONNECTED", "WLAN", "IWLAN"),
            (120, "HANDOVERINPROGRESS", "WLAN", "IWLAN"),
            (121, "CONNECTED", "WWAN", "LTE"),
        ):
            ts = (start + timedelta(seconds=delta)).isoformat(timespec="microseconds")
            lines.append(
                f"  {ts} - notifyDataConnectionForSubscriber: phoneId=0 subId=1  "
                f"state: {state}, transport: {transport}, id: 1, netId: 102, "
                f"network type: {rat}, {apn}",
            )
    return "\n".join(lines) + "\n"


ISUB = (
    "  [SubscriptionInfoInternal: id=1 iccId=[****] simSlotIndex=0 portIndex=0 "
    "isEnhanced4GModeEnabled=1 isWifiCallingEnabled=1 "
    "isWifiCallingEnabledForRoaming=1 wifiCallingMode=CELLULAR_PREFERRED]\n"
)


def _ims_live():
    radio = []
    for start in IMS_STARTS:
        offset = (start - START).total_seconds()
        radio += [(offset + 10, "+mobile_radio"), (offset + 40, "-mobile_radio")]
    radio += [(4.5 * 3600, "+mobile_radio"), (4.5 * 3600 + 10, "-mobile_radio")]
    l2 = _l2_log(3, IMS_STARTS[0] - timedelta(seconds=5), step_s=3600)
    return {
        "telephony_registry": _registry_log(),
        "isub": ISUB,
        "batterystats": history([(600, "-screen"), *radio]),
        "network_stack": l2,
    }


def test_ims_handover_correlates_roams_and_radio(context_factory):
    result = ims_handover(_ctx(context_factory, live=_ims_live()))
    m = result.metrics
    assert m["wifi_calling_enabled"] is True
    assert m["wifi_calling_mode"] == "CELLULAR_PREFERRED"
    assert m["iwlan_cycles_on_battery"] == 3
    assert [r["last_roam_before_s"] for r in result.tables["iwlan_windows"]] == [
        5.0,
        5.0,
        5.0,
    ]
    assert m["radio_activations_in_windows_margin_0s"] == 3
    assert m["radio_share_in_windows_pct_range"] == [90.0, 90.0]
    finding = result.findings[0]
    assert finding.id == "ims_handover.iwlan_pingpong"
    assert finding.severity == "medium"
    assert "Example" not in " ".join(e.excerpt for e in finding.evidence)


def test_ims_handover_prices_window_radio_time_at_the_active_rate(context_factory):
    # 90 s of radio time fall inside the windows. The model's active-time
    # rate is 30 mAh per 1800 s, so they cost 1.5 mAh. Pricing the 90 %
    # share against the 24 mAh billed to apps would give 22 mAh.
    live = {**_ims_live(), "batterystats_charged": CHARGED}
    result = ims_handover(_ctx(context_factory, live=live))
    finding = result.findings[0]
    assert "(30.0 mAh for 30m00s)" in finding.summary
    assert "about 2-2 mAh (modelled)" in finding.summary
    assert "traffic-driven" not in finding.summary


def test_ims_handover_prefers_access_networks_log(context_factory):
    lines = [
        "      AccessNetworksManager-0:",
        "        IWLAN operation mode=AP-assisted",
    ]
    for start in IMS_STARTS:
        for delta, transport in ((0, "WLAN"), (122, "WWAN")):
            ts = (start + timedelta(seconds=delta)).isoformat(timespec="microseconds")
            lines.append(
                f"          {ts} - setPreferredTransports: apnType=ims, "
                f"transport={transport}",
            )
    ctx = _ctx(
        context_factory,
        live=_ims_live(),
        sections={"APP SERVICES PLATFORM (dumpsys activity service)": "\n".join(lines)},
    )
    result = ims_handover(ctx)
    assert result.metrics["iwlan_operation_mode"] == "AP-assisted"
    assert result.notes[0] == "IWLAN windows from the AccessNetworksManager log."
    assert result.findings[0].metrics["median_dwell_s"] == pytest.approx(122.0)


def test_ims_handover_without_cycles_has_no_finding(context_factory):
    result = ims_handover(_ctx(context_factory, live={"isub": ISUB}))
    assert result.metrics["iwlan_cycles_on_battery"] == 0
    assert result.findings == []


def test_ims_handover_skips_without_inputs(context_factory):
    with pytest.raises(SkipError):
        ims_handover(_ctx(context_factory, live={"settings": "x=1\n"}))


# ---------------------------------------------------------------------------
# network_traffic and vpn

BUCKETS = [int(datetime(2026, 1, 15, h, tzinfo=UTC).timestamp()) for h in (5, 7, 9)]


def _netstats() -> str:
    wifi = '{type=1, ratType=COMBINED, wifiNetworkKey="ExampleNet"wpa2-psk, metered=false, defaultNetwork=true, oemManaged=OEM_NONE, subId=-1, transports={1}}'  # ruff: ignore[line-too-long]
    tun = "{type=17, ratType=COMBINED, metered=false, defaultNetwork=true, oemManaged=OEM_NONE, subId=-1, transports={1, 4}}"  # ruff: ignore[line-too-long]
    rows = {
        (wifi, 10101): (1_100_000, 6000, 1_000_000, 6100),
        (wifi, 10103): (10_000, 130, 9_000, 130),
        (wifi, 10104): (700_000, 4000, 720_000, 4100),
        (wifi, 10105): (120 * 1024**2, 80_000, 1_000_000, 9000),
        (tun, 10101): (20_000, 200, 20_000, 200),
        (tun, 0): (0, 0, 4000, 100),
    }
    lines = [
        "Active interfaces:",
        f"  iface=wlan0 ident=[{wifi}]",
        f"  iface=tun0 ident=[{tun}]",
        "UID stats:",
        "  Pending bytes: 0",
        "  History since boot:",
    ]
    for (ident, uid), (rb, rp, tb, tp) in rows.items():
        lines += [
            f"  ident=[{ident}] uid={uid} set=DEFAULT tag=0x0",
            "    NetworkStatsHistory: bucketDuration=7200",
        ]
        for i, st in enumerate(BUCKETS):
            big = rb if uid != 10105 or i == 1 else 1000
            lines.append(f"      st={st} rb={big} rp={rp} tb={tb} tp={tp} op=0")
    lines += ["UID tag stats:", "  Pending bytes: 0"]
    return "\n".join(lines) + "\n"


def test_network_traffic_steady_packets_and_download(context_factory):
    ctx = _ctx(
        context_factory,
        live={"batterystats_charged": CHARGED, "netstats": _netstats()},
    )
    result = network_traffic(ctx)
    m = result.metrics
    assert m["wifi_rx_packets"] == 50000
    assert m["netstats_span"] == ["2026-01-15 07:00:00", "2026-01-15 13:00:00"]
    assert m["kernel_vpn_bare_tx_segments"] == 300
    buckets = result.tables["netstats_buckets"]
    assert [b["vpn_rx_pkts"] for b in buckets] == [200, 200, 200]
    steady = next(f for f in result.findings if "steady" in f.id)
    assert steady.severity == "medium"
    assert steady.metrics["uids"][0] == "com.example.chatty"
    assert "com.example.motion" in steady.metrics["uids"]
    download = next(f for f in result.findings if "download" in f.id)
    assert download.metrics["largest_mib"] == pytest.approx(120.0)
    assert "ExampleNet" not in str(result.to_dict())


def test_network_traffic_quiet_traffic(context_factory):
    charged = dedent(
        """\
        Statistics since last charge:
          u0a101:
            Wi-Fi network: 30,00KB received, 28,00KB sent (packets 20 received, 20 sent)
        """,
    )
    ctx = _ctx(context_factory, live={"batterystats_charged": charged})
    result = network_traffic(ctx)
    assert result.tables["batterystats_traffic"][0]["rx_pkts"] == 20
    assert result.findings == []


def test_network_traffic_skips_without_inputs(context_factory):
    with pytest.raises(SkipError):
        network_traffic(_ctx(context_factory, live={"settings": "x=1\n"}))


def _connectivity(vpn_line: str) -> str:
    wifi = (
        "  NetworkAgentInfo{network{100}  handle{1}  ni{WIFI CONNECTED extra: } "
        "created=2026-01-15T03:00:00.000Z Score(Policies : IS_VALIDATED)  "
        "lp{{InterfaceName: wlan0 LinkAddresses: [ 192.0.2.10/24 ] }}  "
        "nc{[ Transports: WIFI ]}}"
    )
    return f"NetworkAgentInfos:\n{wifi}\n{vpn_line}\n"


MESH_VPN = (
    "  NetworkAgentInfo{network{101}  handle{2}  ni{VPN CONNECTED extra: "
    "VPN:com.example.meshvpn} created=2026-01-15T04:30:00.000Z Score(Policies : "
    "IS_VPN)  underlying{[100]}  lp{{InterfaceName: tun0 LinkAddresses: [ "
    "198.51.100.5/32 ] Routes: [ 198.51.100.7/32 -> 0.0.0.0 tun0 mtu 0,"
    "198.51.100.8/32 -> 0.0.0.0 tun0 mtu 0,198.51.100.9/32 -> 0.0.0.0 tun0 mtu 0,"
    "198.51.100.5/32 -> 0.0.0.0 tun0 mtu 0 ]}}  nc{[ Transports: WIFI|VPN ]}}"
)


def test_vpn_mesh_finding(context_factory):
    ctx = _ctx(
        context_factory,
        live={
            "connectivity": _connectivity(MESH_VPN),
            "netstats": _netstats(),
            "batterystats_charged": CHARGED,
            "vpn_management": "[LockdownAlwaysOn] Mode changed: lockdown=false "
            "alwaysOn=true calling from 1000\n",
        },
    )
    result = vpn(ctx)
    m = result.metrics
    assert m["vpn_active"] is True
    assert m["vpn_interfaces"] == ["tun0"]
    assert m["vpn_always_on"] is True
    assert m["vpn_mesh"] is True
    assert m["vpn_created"] == "2026-01-15 06:30:00"
    assert m["vpn_app_rx_pkts"] == 12000
    assert m["kernel_vpn_bare_tx_segments"] == 300
    finding = result.findings[0]
    assert finding.id == "vpn.mesh_vpn_keepalives"
    assert finding.severity == "medium"
    assert "resets" in finding.followups[0]
    text = finding.summary + " ".join(e.excerpt for e in finding.evidence)
    assert "198.51.100" not in text


def test_network_traffic_leaves_out_the_vpn_app(context_factory):
    """vpn owns the VPN app's own packets; network_traffic does not repeat them."""
    live = {
        "connectivity": _connectivity(MESH_VPN),
        "netstats": _netstats(),
        "batterystats_charged": CHARGED,
    }
    ctx = _ctx(context_factory, live=live)
    before = next(f for f in network_traffic(ctx).findings if "steady" in f.id)
    ctx.results["vpn"] = vpn(ctx)
    after = next(f for f in network_traffic(ctx).findings if "steady" in f.id)
    assert set(before.metrics["uids"]) - set(after.metrics["uids"]) == {
        "com.example.meshvpn",
    }
    assert "vpn.mesh_vpn_keepalives reports its packets" in after.summary


def test_vpn_peer_routes_leave_out_the_dns_resolver(context_factory):
    # A mesh VPN routes its built-in resolver by a host route too.
    with_dns = MESH_VPN.replace(
        "198.51.100.5/32 -> 0.0.0.0 tun0 mtu 0 ]",
        "198.51.100.5/32 -> 0.0.0.0 tun0 mtu 0,198.51.100.53/32 -> 0.0.0.0 tun0 "
        "mtu 0 ] DnsAddresses: [ /198.51.100.53,/2001:db8::53 ]",
    )
    result = vpn(_ctx(context_factory, live={"connectivity": _connectivity(with_dns)}))
    assert result.tables["vpns"][0]["peer_routes"] == 3
    assert "3 peer routes" in result.findings[0].summary


def test_vpn_always_on_app_null_means_off(context_factory):
    settings = "===SECURE\nalways_on_vpn_app=null\nalways_on_vpn_lockdown=0\n"
    live = {"connectivity": _connectivity(MESH_VPN), "settings": settings}
    result = vpn(_ctx(context_factory, live=live))
    assert result.metrics["vpn_always_on"] is False
    assert result.metrics["vpn_lockdown"] is False


def test_vpn_plain_vpn_is_info(context_factory):
    plain = MESH_VPN.replace("meshvpn", "corpvpn").replace(
        "Routes: [ 198.51.100.7/32",
        "Routes: [ 0.0.0.0/0",
    )
    plain = plain.split(",198.51.100.8")[0] + " ]}}  nc{[ Transports: WIFI|VPN ]}}"
    result = vpn(_ctx(context_factory, live={"connectivity": _connectivity(plain)}))
    assert result.findings[0].id == "vpn.active_vpn"
    assert result.findings[0].severity == "info"


def test_no_vpn_no_finding(context_factory):
    result = vpn(_ctx(context_factory, live={"connectivity": _connectivity("")}))
    assert result.metrics["vpn_active"] is False
    assert result.findings == []


def test_vpn_skips_without_connectivity(context_factory):
    with pytest.raises(SkipError):
        vpn(_ctx(context_factory, live={"settings": "x=1\n"}))


# ---------------------------------------------------------------------------
# background_scanning_sensors_location

BLUETOOTH = dedent(
    """\
    Profile: GattService
    GATT Scanner Map
      Entries: 2

      com.example.wearable (Registered)
      LE scans (started/stopped)                                  : 3 / 2
      Scan time in ms (active/suspend/total)                      : 7200000 / 0 / 7200000
      Scan time with mode in ms (Opp/LowPower/Balanced/LowLatency/AmbientDiscovery):0 / 0 / 0 / 7200000 / 0
      Total number of results                                     : 0
      Ongoing scans                                               :
        01-15 09:00:00 - 7200000ms Filter 0 results (1) CB Regular Scan
          └ Scan Config: [ ScanMode=LOW_LATENCY, callbackType=ALL_MATCHES ]
          └ BluetoothLeScanFilter [ DeviceAddress=02:00:00:00:00:01 ]
      Application ID                     : 4

      com.example.beacons
      LE scans (started/stopped)                                  : 10 / 10
      Scan time in ms (active/suspend/total)                      : 10000 / 0 / 10000
      Scan time with mode in ms (Opp/LowPower/Balanced/LowLatency/AmbientDiscovery):0 / 10000 / 0 / 0 / 0
      Total number of results                                     : 5
      Last 1 scans                                                :
        01-15 10:00:00 - 1000ms Filter 1 results (2) CB Regular Scan
          └ Scan Config: [ ScanMode=LOW_POWER, callbackType=ALL_MATCHES ]

    GATT Advertiser Map
    """,  # ruff: ignore[line-too-long]
)
LOCATION = dedent(
    """\
    Location Manager State:
      Location Providers:
        gps provider:
          service: ProviderRequest[OFF]
          listeners:
            10105/com.example.tracker/AB12CD34 Request[@+5s0ms HIGH_ACCURACY, WorkSource{10105 com.example.tracker}]
      Historical Aggregate Location Provider Data:
        gps:
          10105/com.example.tracker: min/max interval = 5s/5s, total/active/foreground duration = +2h0m0s0ms/+1h0m0s0ms/+10m0s0ms, locations = 700
        network:
          10106/com.example.weather: min/max interval = 3600s/3600s, total/active/foreground duration = +5h0m0s0ms/+5h0m0s0ms/+5h0m0s0ms, locations = 5
      Historical Aggregate Gnss Measurement Provider Data:
    """,  # ruff: ignore[line-too-long]
)
SENSORS = dedent(
    """\
    Sensor List:
    0x0000000c) Example Accelerometer Wakeup | ExampleVendor | ver: 1 | type: android.sensor.accelerometer(1) | perm: n/a | flags: 0x00000981
    \tcontinuous | minRate=1.00Hz | maxRate=400.00Hz | wakeUp |
    0x000000bf) Example Step Counter Non-wakeup | ExampleVendor | ver: 1 | type: android.sensor.step_counter(19) | perm: n/a | flags: 0x00000002
    Active sensors:
    Example Accelerometer Wakeup (handle=0x0000000c, connections=1)
    1 active connections
    Connection Number: 0
    \tOperating Mode: NORMAL
    \t com.example.motion.Listener | WakeLockRefCount 0 | uid 10103 | cache size 0 | max cache size 0
    \t Example Accelerometer Wakeup 0x0000000c | status: active | pending flush events 0
    """,  # ruff: ignore[line-too-long]
)


def test_background_scanning_finds_ble_location_and_sensors(context_factory):
    ctx = _ctx(
        context_factory,
        live={
            "batterystats_charged": CHARGED,
            "bluetooth_manager": BLUETOOTH,
            "location": LOCATION,
            "sensorservice": SENSORS,
        },
    )
    result = background_scanning_sensors_location(ctx)
    assert result.metrics["bluetooth_modelled_mah"] == pytest.approx(3.5)
    assert _ids(result) == {
        "background_scanning_sensors_location.ble",
        "background_scanning_sensors_location.location",
        "background_scanning_sensors_location.sensors",
    }
    ble = next(f for f in result.findings if f.id.endswith(".ble"))
    assert "com.example.wearable" in ble.summary
    assert "LOW_LATENCY" in ble.summary
    location = next(f for f in result.findings if f.id.endswith(".location"))
    assert location.window == "since_boot"
    assert "com.example.tracker used GPS for 50 min" in location.summary
    sensors = next(f for f in result.findings if f.id.endswith(".sensors"))
    assert "Example Accelerometer Wakeup" in sensors.summary
    listeners = result.tables["sensor_listeners_now"]
    assert listeners[0]["name"] == "com.example.motion"
    assert listeners[0]["wakeup"] is True


def test_modelled_bluetooth_counts_only_the_on_battery_states(context_factory):
    # Android 15+ repeats the components per power state; the Global line
    # also counts time on the charger.
    states = "".join(
        f"      {line}\n"
        for line in (
            "gnss: 0.100 apps: 0.100",
            "  (on battery, screen on)",
            "  bluetooth: 0.500 apps: 0",
            "  (on battery, screen off/doze)",
            "  bluetooth: 2.00 apps: 0",
            "  (not on battery, screen off/doze)",
            "  bluetooth: 1.00 apps: 0",
        )
    )
    charged = CHARGED.replace("      gnss: 0.100 apps: 0.100\n", states)
    ctx = _ctx(context_factory, live={"batterystats_charged": charged})
    result = background_scanning_sensors_location(ctx)
    assert result.metrics["bluetooth_modelled_mah"] == pytest.approx(2.5)
    assert result.metrics["gnss_modelled_mah"] == pytest.approx(0.1)


def test_background_scanning_quiet(context_factory):
    quiet_location = LOCATION.replace("+1h0m0s0ms/+10m0s0ms", "+10m0s0ms/+10m0s0ms")
    ctx = _ctx(
        context_factory,
        live={
            "location": quiet_location,
            "bluetooth_manager": BLUETOOTH.replace("7200000", "720000"),
        },
    )
    result = background_scanning_sensors_location(ctx)
    assert result.findings == []
    assert result.tables["location_use_since_boot"][0]["background_s"] == 0


def test_background_scanning_skips_without_inputs(context_factory):
    with pytest.raises(SkipError):
        background_scanning_sensors_location(
            _ctx(context_factory, live={"settings": "x=1\n"}),
        )


# ---------------------------------------------------------------------------
# robustness


def test_odd_lines_are_skipped_and_counted(context_factory):
    hist = history([(600, "-screen")]).replace(
        "    0 (2) 100 -plugged",
        "    0 (2) 100 -plugged\n                 Details: cpu=1u+2s\n"
        "             +5s000ms (2) garbled",
    )
    charged = CHARGED.replace(
        "Cellular data received: 50,00KB",
        "Cellular data received: 1,2,3KB",
    )
    ctx = _ctx(
        context_factory,
        live={"batterystats": hist, "batterystats_charged": charged},
    )
    result = cellular_radio(ctx)
    assert "Battery history: 1 unreadable lines skipped." in result.notes
    assert "batterystats: 1 lines with unreadable values skipped." in result.notes
    assert "cellular_rx_bytes" not in result.metrics


def test_netstats_buckets_use_the_phone_time_zone(context_factory):
    # Helsinki is UTC+2 in January: the 05:00 UTC bucket starts at 07:00.
    zoned = Windows(
        since_charge_start=START,
        on_battery_s=5 * 3600,
        dump_time=datetime(2026, 1, 15, 12, 30, 0),
        zone=ZoneInfo("Europe/Helsinki"),
    )
    ctx = context_factory(
        live={"netstats": _netstats()},
        packages=PACKAGES,
        windows=zoned,
    )
    result = network_traffic(ctx)
    assert result.metrics["netstats_span"][0] == "2026-01-15 07:00:00"
    assert not any("UTC offset unknown" in note for note in result.notes)


def test_netstats_buckets_without_a_time_zone_are_read_as_utc(context_factory):
    unzoned = Windows(
        since_charge_start=datetime(2026, 1, 15, 5, 0, 0),
        on_battery_s=5 * 3600,
        dump_time=datetime(2026, 1, 15, 10, 30, 0),
    )
    ctx = context_factory(
        live={"netstats": _netstats()},
        packages=PACKAGES,
        windows=unzoned,
    )
    result = network_traffic(ctx)
    assert result.metrics["netstats_span"][0] == "2026-01-15 05:00:00"
    assert "UTC offset unknown: netstats buckets were read as UTC." in result.notes


def test_ims_windows_from_radio_log_are_lower_bounds(context_factory):
    lines = []
    for start in IMS_STARTS:
        for delta, transport in ((0, "WLAN"), (120, "WWAN")):
            ts = (start + timedelta(seconds=delta)).strftime("%Y-%m-%d %H:%M:%S.000")
            lines.append(
                f"{ts} radio  2832  3797 D ANM-0   : setPreferredTransports: "
                f"apnType=ims, transport={transport}",
            )
    live = {"logcat_radio": "\n".join(lines) + "\n", "isub": ISUB}
    result = ims_handover(_ctx(context_factory, live=live))
    assert result.metrics["iwlan_cycles_on_battery"] == 3
    assert any("lower bounds" in note for note in result.notes)
