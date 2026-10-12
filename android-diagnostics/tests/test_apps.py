"""Tests for the per-app analyzers: UID mapping, background activity, inventory.

All dump text is invented. Package names use com.example.*, times are in
January 2026 and the capture time is 2026-01-15 12:00.
"""

from __future__ import annotations

from datetime import datetime
from textwrap import dedent, indent

import pytest
from androiddiag import apps
from androiddiag.batterystats import parse_since_charge
from androiddiag.common import PackageMap, parse_settings
from androiddiag.model import Finding, Result, SkipError, Windows
from androiddiag.source import Text

CAPTURE = datetime(2026, 1, 15, 12, 0, 0)
WINDOWS = Windows(
    dump_time=CAPTURE,
    on_battery_s=4 * 3600,
    screen_off_on_battery_s=3 * 3600,
)

PACKAGES_3P = dedent(
    """\
    package:/data/app/~~AbC==/com.example.dormant-XyZ==/base.apk=com.example.dormant uid:10101
    package:/data/app/~~DeF==/com.example.active-UvW==/base.apk=com.example.active uid:10102
    package:com.example.push uid:10103,1010103
    package:com.example.launcher uid:10104
    package:com.example.keyboard uid:10105
    package:com.example.idle uid:10106
    package:com.example.scanner uid:10107
    package:com.example.heavy uid:10150
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

# The full package list, as "cmd package list packages -U" prints it.
PACKAGES_ALL = PACKAGES_3P + dedent(
    """\
    package:android uid:1000
    package:com.example.system.settings uid:1000
    package:com.android.launcher3 uid:10177
    package:com.example.shared.a uid:10140
    package:com.example.shared.b uid:10140
    """,
)

USAGESTATS = dedent(
    """\
    user=0
      Last 24 hour events (timeRange="14.1.2026 klo 12.00–15.1.2026 klo 12.00" )
        time="2026-01-15 09:00:00" type=ACTIVITY_RESUMED package=com.example.active flags=0x0
      In-memory daily stats
      timeRange="15.1.2026 klo 0.00–15.1.2026 klo 12.00"
        packages
          package=com.example.active totalTimeUsed="10:00" lastTimeUsed="2026-01-15 09:00:00" appLaunchCount=2
      In-memory yearly stats
      timeRange="1.6.2025 klo 10.00–15.1.2026 klo 12.00"
        packages
          package=com.example.dormant totalTimeUsed="00:00" lastTimeUsed="1970-01-01 02:00:00" totalTimeVisible="00:00" lastTimeVisible="1970-01-01 02:00:00" lastTimeComponentUsed="2026-01-15 11:00:00" totalTimeFS="00:00" lastTimeFS="1970-01-01 02:00:00" appLaunchCount=0
          package=com.example.active totalTimeUsed="1:02:03" lastTimeUsed="2026-01-15 09:00:00" totalTimeVisible="1:05:00" lastTimeVisible="2026-01-15 09:00:10" totalTimeFS="10:00:00" lastTimeFS="2026-01-15 11:00:00" appLaunchCount=40
          package=com.example.push totalTimeUsed="00:00" lastTimeUsed="1970-01-01 02:00:00" totalTimeVisible="00:00" lastTimeVisible="1970-01-01 02:00:00" totalTimeFS="2000:30:00" lastTimeFS="2026-01-15 11:59:00" appLaunchCount=0
          package=com.example.idle totalTimeUsed="05:05" lastTimeUsed="2025-10-01 12:00:00" totalTimeVisible="05:10" lastTimeVisible="2025-10-01 12:00:00" totalTimeFS="00:00" lastTimeFS="1970-01-01 02:00:00" appLaunchCount=1
          package=com.example.keyboard totalTimeUsed="00:00" lastTimeUsed="1970-01-01 02:00:00" totalTimeVisible="00:00" lastTimeVisible="1970-01-01 02:00:00" appLaunchCount=0
          package=com.example.launcher totalTimeUsed="20:00:00" lastTimeUsed="2026-01-15 11:00:00" appLaunchCount=0
          package=com.example.scanner totalTimeUsed="12:00" lastTimeUsed="2026-01-14 12:00:00" appLaunchCount=3
          package=com.example.heavy totalTimeUsed="30:00" lastTimeUsed="2026-01-13 12:00:00" appLaunchCount=5
        ChooserCounts
          package=com.example.active
    User 0 App Standby States:
      package=com.example.dormant u=0 bucket=10 reason=u used=+1h0m0s0ms usedByUser=+400d1h0m0s0ms usedScr=<uninitialized> idle=n
      package=com.example.push u=0 bucket=5 reason=d used=+1h0m0s usedByUser=<uninitialized> usedScr=<uninitialized> idle=n
      package=com.example.active u=0 bucket=10 reason=u used=+3h0m0s usedByUser=+3h0m0s usedScr=+3h idle=n
      package=com.example.active u=10 bucket=40 reason=p used=+30d usedByUser=+30d usedScr=+30d idle=y
    """,  # ruff: ignore[line-too-long, ambiguous-unicode-character-string] - dump lines are long, timeRange uses an en dash
)

USAGESTATS_CHECKIN = dedent(
    """\
    user=0
      In-memory yearly stats
      beginTime=1748772000000 endTime=1768471200000
        packages
          package=com.example.dormant totalTimeUsed=0 lastTimeUsed=0 totalTimeVisible=0 lastTimeVisible=0 appLaunchCount=0
          package=com.example.active totalTimeUsed=3723000 lastTimeUsed=1768460400000 totalTimeVisible=3900000 lastTimeVisible=1768460410000 appLaunchCount=40
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

DEVICEIDLE = dedent(
    """\
    DEVICE IDLE CONTROLLER (dumpsys deviceidle)
      Whitelist (except idle) system apps:
        com.android.providers.downloads
      Whitelist system apps:
        com.android.shell
      Whitelist user apps:
        com.example.dormant
        com.example.push
        com.example.idle
        com.example.active
      Whitelist (except idle) all app ids:
        10101
    """,
)

SETTINGS = dedent(
    """\
    adb_enabled=1
    ===SECURE
    accessibility_enabled=1
    default_input_method=com.example.keyboard/.Ime
    enabled_accessibility_services=com.example.dormant/com.example.dormant.A11y
    enabled_input_methods=com.example.keyboard/.Ime;123:com.example.voice/.VoiceIme:com.example.other.ime/.OtherIme;1;2
    enabled_notification_listeners=com.example.dormant/.Listener:com.example.idle/.Listener
    tts_default_synth=com.example.tts
    ===SYSTEM
    screen_brightness=100
    """,
)

ACTIVITY_SERVICES = dedent(
    """\
    ACTIVITY MANAGER SERVICES (dumpsys activity services)
      User 0 active services:
      * ServiceRecord{1a2b3c4 u0 com.example.push/.service.SubscriberService c:com.example.push}
        intent={cmp=com.example.push/.service.SubscriberService}
        isForeground=true foregroundId=1001 types=0x40000000 foregroundNoti=Notification(channel=subscriber)
      * ServiceRecord{aaa u0 com.example.active/.LinkService c:com.example.active}
        isForeground=true foregroundId=1 types=0x00000410 foregroundNoti=Notification(channel=link)
      * ServiceRecord{bbb u10 com.example.other/.Svc c:com.example.other}
        isForeground=true foregroundId=1 types=0x00000001 foregroundNoti=Notification(channel=x)
      * ServiceRecord{ccc u0 com.example.idle/.Svc c:com.example.idle}
        createTime=-1h
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

PROCSTATS = dedent(
    """\
    AGGREGATED OVER LAST 24 HOURS:
      * com.example.dormant:Daemon / u0a101 / v1:
             TOTAL: 100% (0,00-0,00-0,00/0,00-0,00-0,00/60MB-80MB-120MB over 20)
           Service: 100% (0,00-0,00-0,00/0,00-0,00-0,00/60MB-80MB-120MB over 20)
      * com.example.push / u0a103 / v7:
             TOTAL: 99,5% (10MB-12MB-15MB/5MB-6MB-7MB/50MB-56,5MB-60MB over 20)
               Fgs: 99,5% (10MB-12MB-15MB/5MB-6MB-7MB/50MB-56,5MB-60MB over 20)
      * com.example.keyboard / u0a105 / v1:
             TOTAL: 82% (0,00-0,00-0,00/0,00-0,00-0,00/80MB-90MB-100MB over 20)
           Bnd Fgs: 0,50%
            Imp Bg: 80% (0,00-0,00-0,00/0,00-0,00-0,00/80MB-90MB-100MB over 20)
      * com.example.launcher / u0a104 / v1:
             TOTAL: 73% (0,00-0,00-0,00/0,00-0,00-0,00/100MB-200MB-300MB over 20)
               Top: 73% (0,00-0,00-0,00/0,00-0,00-0,00/100MB-200MB-300MB over 20)
      * com.android.launcher3 / u0a177 / v3:
             TOTAL: 100% (0,00-0,00-0,00/0,00-0,00-0,00/100MB-110MB-120MB over 20)
           Bnd Fgs: 75% (0,00-0,00-0,00/0,00-0,00-0,00/100MB-110MB-120MB over 20)
      * broken / uXa1 / v1:
             TOTAL: 5%

    Run time Stats:
      SOff/Norm: +18h0m0s0ms
          TOTAL: +21h4m0s0ms

    Memory usage:
      Kernel : 500MB (60 samples)
    """,
)

BATTERYSTATS_CHARGED = dedent(
    """\
    Statistics since last charge:
      System starts: 0, currently on battery: true
      Discharge: 200 mAh
      Estimated power use (mAh):
        Capacity: 4000, Computed drain: 200, actual drain: 180-220
        Global
          screen: 50.0 apps: 50.0 duration: 30m 0s 0ms
          cpu: 60.0 apps: 60.0
        UID u0a102: 52.0 fg: 1.50 bg: 0.300 ( screen=50.0 (30m 0s 0ms) cpu=2.00 cpu:fg=1.50 cpu:bg=0.300 )
        UID 0: 40.0 ( cpu=40.0 )
        UID 1000: 30.0 ( cpu=30.0 )
        UID u0a101: 1,20 bg: 0,20 fgs: 0,90 ( cpu=1,10 cpu:bg=0,20 cpu:fgs=0,90 sensors=0,100 (1h 0m 0s 0ms) )
        UID u0a150: 6.00 bg: 6.00 ( cpu=6.00 cpu:bg=6.00 )
        UID u0a140: 2.00 ( cpu=2.00 )
        UID u0a199: 7.00 ( cpu=7.00 )

      u0a101:
        Wi-Fi network: 100,00KB received, 50,00KB sent (packets 250 received, 300 sent)
        Bluetooth Scan (total blamed realtime): 2h 0m 0s 0ms  (0 times) (currently running)
        Bluetooth Scan (total actual realtime): 4h 0m 0s 0ms  (0 times) (currently running)
        Bluetooth Scan Results: 2 (1 in background)
        Wake lock *alarm*: 20ms partial (4 times) max=10 realtime
        Wake lock Sync: 1s 0ms partial (2 times) max=600 realtime
        Fg Service for: 4h 0m 0s 0ms
        Total cpu time: u=13s 500ms s=12s 0ms
        Total screen-off cpu time per freq: 0 7000 500 500 4000
        Proc com.example.dormant:Daemon:
          CPU: 13s 0ms usr + 12s 0ms krn ; 0ms fg
        Apk com.example.dormant:
          Wakeup alarm *walarm*:com.example.dormant.SYNC: 6 times
      u0a102:
        Top for: 30m 0s 0ms
        Top Sleeping for: 45m 0s 0ms
        Foreground services: 4h 0m 0s 0ms realtime (1 times) (running)
        TOTAL wake: 2m 0s 0ms blamed partial, 3m 0s 0ms actual partial realtime
        Wake lock A: 1m 0s 0ms partial (3 times) max=100 realtime
        Wake lock B: 1m 0s 0ms partial (3 times) max=100 realtime
        Total screen-off cpu time per freq: 0 10000 30000
        WiFi Multicast Wakelock count = 2 time = 1h 0m 0s 0ms
      u0a150:
        Top Sleeping for: 10m 0s 0ms
        Total screen-off cpu time per freq: 0 600000
        Apk com.example.heavy:
          Wakeup alarm *walarm*:poll: 30 times
          Job com.example.heavy/.SyncJob: 1m 0s 0ms realtime (5 times)
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

ALARM = dedent(
    """\
    Current Alarm Manager state:
      Current AppStateTracker State:
        Restricted packages:
          u0a106 com.example.idle
        Stats:
          UID_FG_STATE_CHANGED: count=0
      nowRTC=1768471200000=2026-01-15 12:00:00.000 nowELAPSED=3600000
      Alarm Stats:
      u0a101:com.example.dormant +600ms running, 23 wakeups:
        +300ms 19 wakes 19 alarms, last -6m0s0ms:
          *walarm*:com.example.dormant.SYNC
      1000:android +30s0ms running, 295 wakeups:
        +20s0ms 118 wakes 118 alarms, last -10m0s0ms:
          *walarm*:android.appwidget.action.APPWIDGET_UPDATE
    """,
)

HOME_ACTIVITY = dedent(
    """\
    priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true
    com.example.launcher/com.example.launcher.Home
    """,
)

PACKAGE_DUMP = dedent(
    """\
    Known Packages:
      System:
        android
      Recents:
        com.android.launcher3

    Preferred Activities User 0:
      Non-Data Actions:
          android.intent.action.MAIN:
            abc0002 com.example.launcher/com.example.launcher.Home
             mMatch=0x100000 mAlways=true
              Selected from:
                com.android.launcher3/com.android.searchlauncher.SearchLauncher
                com.example.launcher/com.example.launcher.Home
                com.android.settings/.FallbackHome
              Action: "android.intent.action.MAIN"
              Category: "android.intent.category.HOME"
              Category: "android.intent.category.DEFAULT"

    Packages:
      Package [com.example.dormant] (abc0001):
        appId=10101
        flags=[ HAS_CODE ALLOW_CLEAR_USER_DATA ]
        User 0: ceDataInode=1 installed=true hidden=false suspended=false stopped=false notLaunched=false enabled=0
          firstInstallTime=2024-01-01 10:00:00
        User 10: ceDataInode=0 installed=false hidden=false suspended=false stopped=false notLaunched=true enabled=0
          firstInstallTime=1970-01-01 02:00:00
      Package [com.example.newapp] (abc1234):
        appId=10120
        flags=[ HAS_CODE ]
        User 0: ceDataInode=1 installed=true hidden=false suspended=false stopped=true notLaunched=true enabled=0
          firstInstallTime=2026-01-10 10:00:00
      Package [com.android.launcher3] (def5678):
        appId=10177
        flags=[ SYSTEM HAS_CODE ]
        User 0: ceDataInode=1 installed=true hidden=false suspended=false stopped=false notLaunched=false enabled=0

    Hidden system packages:
      Package [com.example.updated] (0a0b0c0):
        appId=10130
        flags=[ SYSTEM HAS_CODE ]
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

CHECKIN = dedent(
    """\
    9,0,i,vers,36,215,TEST.1,TEST.2
    9,0,i,uid,1000,android
    9,0,i,uid,10199,com.example.removed
    9,0,i,uid,10140,com.example.shared.a
    9,10199,l,cpu,1,2,0
    9,10101,l,cpu,1,2,0
    9,99003,l,cpu,1,2,0
    9,h,0:RESET:TIME:1768464000000
    """,
)

NETSTATS = dedent(
    """\
    UID stats:
      ident=[{type=1, ratType=COMBINED, metered=false, defaultNetwork=true}] uid=-1 set=ALL tag=0x0
      ident=[{type=1, ratType=COMBINED, metered=false, defaultNetwork=true}] uid=10101 set=DEFAULT tag=0x0
    """,  # ruff: ignore[line-too-long] - dump lines are long
)

LIVE = {
    "packages_3p": PACKAGES_3P,
    "usagestats": USAGESTATS,
    "deviceidle": DEVICEIDLE,
    "settings": SETTINGS,
    "activity_services": ACTIVITY_SERVICES,
    "procstats": PROCSTATS,
    "batterystats_charged": BATTERYSTATS_CHARGED,
    "alarm": ALARM,
    "home_activity": HOME_ACTIVITY,
}

# A per-UID block cut mid-token, as a dump that timed out ends.
CUT_UID_BLOCK = indent(
    dedent(
        """\
        u0a169:
          Total cpu time: u=1s 0ms s=500ms
          Cached for: 1""",
    ),
    "  ",
)

# The Android 15+ power model: state sub-blocks and UID continuation lines.
POWER_STATES = dedent(
    """\
    Statistics since last charge:
      Discharge: 100 mAh
      Estimated power use (mAh):
        Capacity: 4000, Computed drain: 100, actual drain: 100
        Global
        screen: 20.0 apps: 20.0
        cpu: 60.0 apps: 60.0
          (on battery, screen on)
          screen: 10.0 apps: 10.0
          cpu: 10.0 apps: 10.0
          (on battery, screen off/doze)
          cpu: 30.0 apps: 30.0
          (not on battery, screen on)
          screen: 10.0 apps: 10.0
          cpu: 20.0 apps: 20.0
      UID u0a150: 60.0 fg: 20.0 bg: 40.0
          screen=20.0 cpu=40.0 cpu:fg=10.0 cpu:bg=30.0
          (on battery, screen on) screen=10.0 cpu=5.00
          (on battery, screen off/doze) cpu=25.0
          (not on battery, screen on) screen=10.0 cpu=10.0
      UID u0a151: 2.00 bg: 2.00
          cpu=2.00
          (on battery, screen on) cpu=2.00
          (on battery, screen off/doze) cpu=2.00
          (not on battery, screen on) cpu=2.00
      UID 1000: 20.0 bg: 20.0
          cpu=20.0
    """,
)


def _text(body: str, origin: str = "live/test.txt") -> Text:
    return Text(origin, body)


def _ids(result) -> list[str]:
    return [f.id for f in result.findings]


def _finding(result, finding_id: str):
    return next(f for f in result.findings if f.id == finding_id)


def _battery_use(body: str) -> apps.BatteryUse:
    since_charge = parse_since_charge(_text(body, "live/batterystats_charged.txt"))
    assert since_charge is not None
    use = apps.parse_battery_use(since_charge)
    assert use is not None
    return use


@pytest.fixture
def ctx_factory(context_factory):
    """Build a context whose package map knows the third-party apps.

    analyze.build_packages fills ``PackageMap.third_party`` from packages_3p;
    the plain context factory does not.
    """

    def factory(live=None, **kwargs):
        ctx = context_factory(
            live=LIVE if live is None else live,
            packages=PACKAGES_ALL,
            windows=WINDOWS,
            **kwargs,
        )
        ctx.packages.third_party = frozenset(
            PackageMap.from_pm_list(PACKAGES_3P).by_app_id,
        )
        return ctx

    return factory


# --- Parsers --------------------------------------------------------------------


def test_parse_pm_list_handles_paths_and_multi_user_uids():
    parsed = apps.parse_pm_list(_text(PACKAGES_3P))
    assert parsed.app_ids["com.example.dormant"] == 10101
    assert parsed.app_ids["com.example.push"] == 10103
    assert parsed.multi_user == 1
    assert len(parsed.app_ids) == 8
    assert "base.apk" not in parsed.evidence["com.example.dormant"].excerpt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('timeRange="1.6.2025 klo 10.00-15.1.2026 klo 12.00"', datetime(2025, 6, 1)),
        ("2025-06-01 10:00 - 2026-01-15 12:00", datetime(2025, 6, 1)),
        ("Jun 1, 2025, 10:00 AM - Jan 15, 2026, 12:00 PM", datetime(2025, 6, 1)),
        ("6/1/25, 10:00 AM - 1/15/26, 12:00 PM", None),
    ],
)
def test_parse_localized_date(text, expected):
    assert apps.parse_localized_date(text) == expected


def test_parse_usage_live_format():
    usage = apps.parse_usage(_text(USAGESTATS), CAPTURE)
    assert usage.window_days == pytest.approx(228.5)
    assert usage.apps["com.example.dormant"].age_days is None
    # lastTimeVisible (09:00:10) is newer than lastTimeUsed and wins.
    assert usage.apps["com.example.active"].age_days == pytest.approx(0.125, abs=1e-3)
    assert usage.apps["com.example.active"].launches == 40
    assert usage.apps["com.example.active"].used_s == pytest.approx(3723.0)
    assert usage.apps["com.example.push"].fgs_s == pytest.approx(7_201_800.0)
    assert usage.apps["com.example.idle"].age_days == pytest.approx(106.0)
    # The daily interval and the ChooserCounts line do not override yearly data.
    assert usage.apps["com.example.active"].index > 10
    assert usage.standby["com.example.dormant"].by_user_days == pytest.approx(
        400 + 1 / 24,
    )
    assert usage.standby["com.example.push"].by_user_days is None
    assert usage.standby["com.example.push"].bucket == 5
    # Only user 0 standby rows are kept.
    assert usage.standby["com.example.active"].bucket == 10
    assert usage.skipped == 0


def test_parse_usage_never_used_sentinel_is_unknown():
    # AppIdleHistory prints usedByUser=totalElapsedTime for an app the user
    # never used; that is not a last use 500 days ago.
    tail = dedent(
        """\
        package=com.example.keyboard u=0 bucket=10 reason=d used=<uninitialized> usedByUser=+500d0h0m0s0ms usedScr=<uninitialized> idle=n

        totalElapsedTime=+500d0h0m0s0ms
        totalScreenOnTime=+50d0h0m0s0ms
        """,  # ruff: ignore[line-too-long] - dump lines are long
    )
    text = USAGESTATS + indent(tail, "  ")
    usage = apps.parse_usage(_text(text), CAPTURE)
    assert usage.standby["com.example.keyboard"].by_user_days is None
    assert usage.standby["com.example.dormant"].by_user_days == pytest.approx(
        400 + 1 / 24,
    )


def test_parse_usage_truncated_standby_line_is_skipped():
    # collect.py keeps partial output on a timeout: the last token may be cut.
    text = USAGESTATS + (
        "  package=com.example.app u=0 bucket=10 reason=u-ma used=+1h usedByUser=+1"
    )
    usage = apps.parse_usage(_text(text), CAPTURE)
    assert usage.standby["com.example.app"].by_user_days is None
    assert usage.skipped == 1


def test_parse_usage_checkin_epoch_format():
    usage = apps.parse_usage(_text(USAGESTATS_CHECKIN), None)
    assert usage.window_days == pytest.approx(228.0)
    assert usage.apps["com.example.dormant"].age_days is None
    assert usage.apps["com.example.active"].age_days == pytest.approx(0.125, abs=1e-3)
    assert usage.apps["com.example.active"].used_s == pytest.approx(3723.0)


def test_parse_usage_without_reference_uses_latest_use():
    usage = apps.parse_usage(_text(USAGESTATS), None)
    # The newest lastTimeUsed (11:00) stands in for the capture time.
    assert usage.apps["com.example.active"].age_days == pytest.approx(2 / 24, abs=1e-3)


def test_parse_procstats_decimal_comma_and_memory():
    parsed = apps.parse_procstats(_text(PROCSTATS))
    assert parsed.hours == pytest.approx(21.07, abs=0.01)
    push = parsed.apps[10103]
    assert push.alive_pct == pytest.approx(99.5)
    assert push.fgs_pct == pytest.approx(99.5)
    assert push.rss_avg_mb == pytest.approx(56.5)
    assert push.pss_avg_mb == pytest.approx(12.0)
    assert push.state == "Fgs"
    dormant = parsed.apps[10101]
    assert dormant.pss_avg_mb is None  # zeros mean PSS was not sampled
    assert dormant.rss_avg_mb == pytest.approx(80.0)
    assert dormant.state == "Service"
    assert parsed.apps[10105].fgs_pct == pytest.approx(0.0)
    assert parsed.apps[10105].state == "Imp Bg"
    assert parsed.apps[10177].state == "Bnd Fgs"
    assert parsed.skipped == 1


def test_parse_procstats_truncated_run_time_keeps_header_hours():
    text = PROCSTATS.replace("TOTAL: +21h4m0s0ms", "TOTAL: +2")
    parsed = apps.parse_procstats(_text(text))
    assert parsed.hours == pytest.approx(24.0)
    assert parsed.skipped == 2  # the unreadable UID and the cut run time


def test_parse_procstats_ignores_the_default_dump():
    text = "COMMITTED STATS FROM 2026-01-15-03-00-00:\n  * x / u0a1 / v1:\n"
    text += "         TOTAL: 5%\n"
    assert apps.parse_procstats(_text(text)).apps == {}


def test_parse_battery_use_power_and_uid_sections():
    use = _battery_use(BATTERYSTATS_CHARGED)
    model = use.since_charge.power
    assert model.computed_drain == pytest.approx(200.0)
    assert model.actual_drain_min == pytest.approx(180.0)
    assert model.capacity == pytest.approx(4000.0)
    assert use.measured_drain() == (200.0, 2)
    assert use.drain_range() == (180.0, 220.0)
    assert sorted(use.power) == [0, 1000, 10101, 10102, 10140, 10150, 10199]
    t3 = use.power[10102]
    assert t3.screen == pytest.approx(50.0)
    assert t3.states == {"fg": 1.5, "bg": 0.3}
    assert t3.background == pytest.approx(0.5)
    comma = use.power[10101]
    assert comma.total == pytest.approx(1.2)
    assert comma.states == {"bg": 0.2, "fgs": 0.9}
    dormant = use.uids[10101]
    assert dormant.bt_scan_s == 4 * 3600
    assert dormant.bt_results == 2
    assert dormant.wakelock_s == pytest.approx(1.02)
    assert dormant.fg_service_s == 4 * 3600
    assert dormant.screen_off_cpu_s == pytest.approx(12.0)
    assert dormant.cpu_s == pytest.approx(25.5)
    assert dormant.wakeup_alarms == 6
    assert dormant.wifi_rx_packets == 250
    active = use.uids[10102]
    assert active.top_sleeping_s == 45 * 60
    assert active.fgs_s == 4 * 3600
    # TOTAL wake wins over the per-tag sum.
    assert active.wakelock_s == pytest.approx(120.0)
    assert active.multicast_s == 3600
    assert use.uids[10150].jobs == 5
    assert use.skipped == 0


def test_parse_battery_use_full_dump_skips_history():
    text = "Battery History:\n  u0a101:\n    Top Sleeping for: 9h 0m 0s 0ms\n"
    use = _battery_use(text + BATTERYSTATS_CHARGED)
    assert use.uids[10101].top_sleeping_s == pytest.approx(0.0)
    assert use.since_charge.power.computed_drain == pytest.approx(200.0)


def test_parse_battery_use_truncated_duration_is_skipped():
    # A dump cut by a timeout ends mid-token ("Cached for: 1").
    text = BATTERYSTATS_CHARGED + CUT_UID_BLOCK
    use = _battery_use(text)
    assert use.uids[10169].cpu_s == pytest.approx(1.5)
    assert use.uids[10169].cached_s == pytest.approx(0.0)
    assert use.skipped == 1


def test_parse_battery_use_on_battery_power_states():
    use = _battery_use(POWER_STATES)
    row = use.power[10150]
    # On battery: screen 10 + cpu 30 of the UID's 60 mAh (two thirds), so
    # the all-states fg share of 20 mAh is scaled to 13.33 mAh.
    assert row.total == pytest.approx(40.0)
    assert row.screen == pytest.approx(10.0)
    assert row.states["fg"] == pytest.approx(13.333, abs=1e-3)
    assert row.background == pytest.approx(16.667, abs=1e-3)
    # Without power states the UID's own total stays.
    assert use.power[1000].total == pytest.approx(20.0)
    # A build that repeats one value in every state adds up to more than the
    # total; the all-states numbers are kept.
    assert use.power[10151].total == pytest.approx(2.0)


def test_measured_drain_falls_back_to_actual_drain():
    text = BATTERYSTATS_CHARGED.replace("  Discharge: 200 mAh\n", "").replace(
        "Computed drain: 200, actual drain: 180-220",
        "Computed drain: 300, actual drain: 180,5-220",
    )
    use = _battery_use(text)
    drain, index = use.measured_drain()
    assert drain == pytest.approx(180.5)
    assert use.text.lines[index].strip().startswith("Capacity:")


def test_parse_foreground_services_decodes_types_and_skips_other_users():
    found = apps.parse_foreground_services(_text(ACTIVITY_SERVICES))
    assert [(s.package, s.types) for s in found] == [
        ("com.example.push", ["specialUse"]),
        ("com.example.active", ["connectedDevice", "systemExempted"]),
    ]


def test_parse_foreground_services_in_full_activity_dump():
    text = (
        "ACTIVITY MANAGER SETTINGS (dumpsys activity settings)\n"
        "  * ServiceRecord{1 u0 com.example.wrong/.Svc c:x}\n"
        "    isForeground=true foregroundId=1 types=0x00000001\n"
        "-------\n" + ACTIVITY_SERVICES + "ACTIVITY MANAGER RECENT TASKS (x)\n"
    )
    found = apps.parse_foreground_services(_text(text))
    assert [s.package for s in found] == ["com.example.push", "com.example.active"]


def test_decode_fgs_types_reports_unknown_bits():
    assert apps.decode_fgs_types(0x10 | 0x100000) == ["connectedDevice", "0x100000"]


def test_setting_components_drop_ime_subtypes():
    settings = parse_settings(_text(SETTINGS))
    assert apps.setting_components(settings, "enabled_input_methods") == [
        "com.example.keyboard/.Ime",
        "com.example.voice/.VoiceIme",
        "com.example.other.ime/.OtherIme",
    ]
    assert apps.setting_components(settings, "missing_key") == []
    assert apps.setting_components(None, "enabled_input_methods") == []


def test_parse_exemptions_dumpsys_and_cmd_forms():
    assert sorted(apps.parse_exemptions(_text(DEVICEIDLE))) == [
        "com.example.active",
        "com.example.dormant",
        "com.example.idle",
        "com.example.push",
    ]
    cmd = "system-excidle,com.android.foo,10045\nsystem,com.android.bar,1000\n"
    cmd += "user,com.example.push,10103\n"
    assert list(apps.parse_exemptions(_text(cmd))) == ["com.example.push"]


def test_parse_alarms_wakeups_and_restricted():
    parsed = apps.parse_alarms(_text(ALARM))
    assert parsed.wakeups["com.example.dormant"][0] == 23
    assert parsed.wakeups["android"][0] == 295
    assert parsed.uids == {10101, 1000}
    assert list(parsed.restricted) == ["com.example.idle"]
    assert parsed.restricted_listed


def test_parse_package_dump():
    dump = apps.parse_package_dump(_text(PACKAGE_DUMP))
    assert dump.home == "com.example.launcher/com.example.launcher.Home"
    assert len(dump.home_candidates) == 3
    assert dump.recents == "com.android.launcher3"
    dormant = dump.packages["com.example.dormant"]
    assert dormant.app_id == 10101
    assert dormant.first_install == datetime(2024, 1, 1, 10, 0, 0)
    assert dormant.not_launched is False
    assert dump.packages["com.example.newapp"].not_launched is True
    assert dump.packages["com.example.updated"].app_id == 10130


def test_parse_package_dump_unindented_overlay_paths_line():
    # Some builds print "<package> overlay paths:" without indentation inside
    # "Packages:"; it must not end the section.
    text = PACKAGE_DUMP.replace(
        "  Package [com.example.newapp]",
        "com.example.overlay overlay paths:\n  Package [com.example.newapp]",
    )
    dump = apps.parse_package_dump(_text(text))
    assert dump.packages["com.example.newapp"].app_id == 10120
    assert dump.packages["com.android.launcher3"].app_id == 10177


def test_parse_package_checkin():
    text = dedent(
        """\
        vers,1
        pkg,com.example.dormant,10101,7,1700000000000,com.android.vending10134?,0
        pkg-splt,base,0
        pkg-usr,0,IbsusLiavpiqha,0,?,1704103200000,
        pkg-usr,10,ibsusliavpiqha,0,?,0,
        pkg,com.example.newapp,10120,1,1768000000000,?-1?,0
        pkg-usr,0,IbsuSliavpiqha,0,?,1768039200000,
        pkg,com.example.broken,10121,1,1768000000000,?-1?,0
        pkg-usr,0,IbsuSliavpiqha,0,?,99999999999999999999,
        """,
    )
    parsed = apps.parse_package_checkin(_text(text))
    assert parsed["com.example.dormant"].not_launched is False
    assert parsed["com.example.dormant"].first_install == datetime(2024, 1, 1, 10, 0)
    assert parsed["com.example.newapp"].not_launched is True
    assert parsed["com.example.broken"].first_install is None


def test_checkin_uids():
    assert apps.checkin_uids(_text(CHECKIN)) == {10199, 10101, 99003}


# --- third_party_apps -------------------------------------------------------------


def test_third_party_apps_one_finding_for_dormant_apps_that_still_run(context_factory):
    ctx = context_factory(live=LIVE, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    assert [i for i in _ids(result) if "dormant-active" in i] == [
        "third_party_apps.dormant-active",
    ]
    finding = _finding(result, "third_party_apps.dormant-active")
    # The BLE scan is background energy, so the finding is medium.
    assert finding.severity == "medium"
    assert finding.basis == "measured"
    assert finding.window == "on_battery"
    assert finding.metrics["packages"] == "com.example.dormant, com.example.push"
    assert finding.metrics["energy_packages"] == "com.example.dormant"
    assert "Bluetooth LE scan 4.0 h" in finding.summary
    assert "accessibility service" in finding.summary
    assert "specialUse" in finding.summary
    assert "not opened for at least 400 days" in finding.summary
    assert "user's call" in finding.recommendation
    rows = {r["package"]: r for r in result.tables["apps"]}
    assert rows["com.example.dormant"]["days_since_use"] == pytest.approx(
        400.0, abs=0.1
    )
    assert rows["com.example.dormant"]["days_since_use_is_lower_bound"] is True
    assert rows["com.example.push"]["fgs_h_in_usage_window"] == pytest.approx(2000.5)
    assert rows["com.example.push"]["days_since_use"] == pytest.approx(228.5)
    refs = {e.ref.split(":")[0] for e in finding.evidence}
    assert {
        "live/usagestats.txt",
        "live/batterystats_charged.txt",
        "live/procstats.txt",
        "live/activity_services.txt",
    } <= refs


def test_third_party_apps_dormant_scanner_relates_to_the_ble_finding(context_factory):
    """background_scanning_sensors_location.ble owns the scan it names."""
    ctx = context_factory(live=LIVE, packages=PACKAGES_ALL, windows=WINDOWS)
    ble = Finding(
        "background_scanning_sensors_location.ble",
        "t",
        "battery",
        "low",
        "measured",
        "on_battery",
        "com.example.dormant scanned 4.0 h on battery with 0 results.",
    )
    ctx.results["background_scanning_sensors_location"] = Result(
        "background_scanning_sensors_location",
        findings=[ble],
    )
    result = apps.third_party_apps(ctx)
    dormant = _finding(result, "third_party_apps.dormant-active")
    assert dormant.related == [ble.id]
    assert ble.related == [dormant.id]
    # Another app's scan is not this finding's fact.
    ble.summary, ble.related = "com.example.other scanned 4.0 h.", []
    dormant = _finding(apps.third_party_apps(ctx), "third_party_apps.dormant-active")
    assert dormant.related == []


def test_third_party_apps_dormant_without_energy_is_low(context_factory):
    live = {k: v for k, v in LIVE.items() if k != "batterystats_charged"}
    ctx = context_factory(live=live, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    finding = _finding(result, "third_party_apps.dormant-active")
    # A live process and a foreground service alone are not measured energy.
    assert finding.severity == "low"
    assert finding.window == "last_24h"
    assert finding.metrics["apps_with_background_energy"] == 0


@pytest.mark.parametrize(
    ("state", "active"),
    [("Bnd Fgs", False), ("Service", True)],
)
def test_third_party_apps_system_bound_listener_is_not_active(
    context_factory,
    state,
    active,
):
    # com.example.idle is a dormant notification listener. Kept bound by the
    # system it holds a privilege; running its own service it is active.
    live = dict(LIVE)
    live["procstats"] = PROCSTATS.replace(
        "  * broken / uXa1 / v1:",
        f"  * com.example.idle / u0a106 / v1:\n"
        f"         TOTAL: 100% (0,00-0,00-0,00/0,00-0,00-0,00/20MB-30MB-40MB over 20)\n"
        f"       {state}: 100% (0,00-0,00-0,00/0,00-0,00-0,00/20MB-30MB-40MB over 20)\n"
        "  * broken / uXa1 / v1:",
    )
    ctx = context_factory(live=live, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    active_apps = _finding(result, "third_party_apps.dormant-active").metrics
    assert ("com.example.idle" in active_apps["packages"]) is active
    if not active:
        privileged = _finding(result, "third_party_apps.dormant-privileged")
        assert privileged.metrics["packages"] == "com.example.idle"
        assert "kept bound by the system" in privileged.summary


def test_third_party_apps_idle_dormant_apps_with_privileges(context_factory):
    ctx = context_factory(live=LIVE, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    finding = _finding(result, "third_party_apps.dormant-privileged")
    assert finding.severity == "low"
    assert finding.metrics["packages"] == "com.example.idle"
    row = next(r for r in result.tables["apps"] if r["package"] == "com.example.idle")
    assert row["background_restricted"] is True
    assert row["days_since_use"] == pytest.approx(106.0)


def test_third_party_apps_roles_are_never_dormant(context_factory):
    ctx = context_factory(live=LIVE, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    rows = {r["package"]: r for r in result.tables["apps"]}
    assert rows["com.example.keyboard"]["role"] == "default keyboard"
    assert rows["com.example.keyboard"]["dormant"] is False
    assert rows["com.example.launcher"]["role"] == "Home app"
    assert "com.example.keyboard" not in str(
        [f.metrics for f in result.findings if "dormant" in f.id],
    )


def test_third_party_apps_recent_use_is_not_dormant(context_factory):
    live = dict(LIVE)
    live["usagestats"] = USAGESTATS.replace(
        'lastTimeUsed="2025-10-01 12:00:00"',
        'lastTimeUsed="2026-01-05 12:00:00"',
    ).replace("usedByUser=+400d1h0m0s0ms", "usedByUser=+2d")
    ctx = context_factory(live=live, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    assert "third_party_apps.dormant-privileged" not in _ids(result)
    # The window length still bounds com.example.dormant from below.
    active = _finding(result, "third_party_apps.dormant-active")
    assert "com.example.dormant" in active.metrics["packages"]


def test_third_party_apps_short_usage_window_is_unknown(context_factory):
    live = dict(LIVE)
    live["usagestats"] = USAGESTATS.replace(
        'timeRange="1.6.2025 klo',
        'timeRange="5.1.2026 klo',
    ).replace("usedByUser=+400d1h0m0s0ms", "usedByUser=<uninitialized>")
    ctx = context_factory(live=live, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    rows = {r["package"]: r for r in result.tables["apps"]}
    # Ten days without use is not enough to call an app dormant.
    assert rows["com.example.dormant"]["dormant"] is False
    assert rows["com.example.dormant"]["days_since_use"] == pytest.approx(10.5)


def test_third_party_apps_last_use_is_capped_at_install(context_factory):
    # com.example.newapp has no usage record in a 228-day window but was
    # installed 60 days ago: it was never opened since then.
    package_dump = PACKAGE_DUMP.replace(
        "firstInstallTime=2026-01-10 10:00:00",
        "firstInstallTime=2025-11-16 12:00:00",
    )
    deviceidle = DEVICEIDLE.replace(
        "    com.example.dormant\n",
        "    com.example.dormant\n    com.example.newapp\n",
    )
    ctx = context_factory(
        live={"usagestats": USAGESTATS, "deviceidle": deviceidle},
        windows=WINDOWS,
        services={"package": package_dump},
    )
    ctx.packages = PackageMap.from_package_dump(package_dump)
    result = apps.third_party_apps(ctx)
    rows = {r["package"]: r for r in result.tables["apps"]}
    assert rows["com.example.newapp"]["days_since_use"] == pytest.approx(60.0)
    assert rows["com.example.newapp"]["installed_days"] == pytest.approx(60.0)
    assert rows["com.example.newapp"]["dormant"] is True
    finding = _finding(result, "third_party_apps.dormant-privileged")
    assert "not opened since it was installed 60 days ago" in finding.summary


def test_third_party_apps_persistent_foreground_services(context_factory):
    ctx = context_factory(live=LIVE, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    finding = _finding(result, "third_party_apps.persistent-foreground-services")
    assert finding.metrics["packages"] == "com.example.active"
    assert "systemExempted" in finding.summary
    assert finding.window == "last_24h"
    assert result.metrics["third_party_fgs_apps_now"] == 2
    assert result.metrics["foreground_services_now"] == 2
    assert [r["package"] for r in result.tables["foreground_services"]] == [
        "com.example.push",
        "com.example.active",
    ]


def test_third_party_apps_exempt_app_using_background_energy(context_factory):
    ctx = context_factory(live=LIVE, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    finding = _finding(result, "third_party_apps.exempt-background-energy")
    # 40 s of screen-off CPU over 3 h is above 10 s/h.
    assert finding.metrics["packages"] == "com.example.active"
    assert "13 s/h screen-off CPU" in finding.summary
    # Its foreground service is also in the persistent list: linked both ways.
    assert finding.related == ["third_party_apps.persistent-foreground-services"]


def test_third_party_apps_exempt_app_below_threshold(context_factory):
    live = dict(LIVE)
    live["batterystats_charged"] = BATTERYSTATS_CHARGED.replace(
        "per freq: 0 10000 30000",
        "per freq: 0 10000 15000",
    )
    ctx = context_factory(live=live, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    assert "third_party_apps.exempt-background-energy" not in _ids(result)


def test_third_party_apps_two_launchers_and_keyboards(context_factory):
    ctx = context_factory(
        live=LIVE,
        packages=PACKAGES_ALL,
        windows=WINDOWS,
        services={"package": PACKAGE_DUMP},
    )
    result = apps.third_party_apps(ctx)
    launchers = _finding(result, "third_party_apps.two-launchers")
    assert launchers.metrics == {
        "home": "com.example.launcher",
        "recents": "com.android.launcher3",
        "home_candidates": "com.android.launcher3, com.example.launcher",
    }
    assert "com.android.launcher3 alive 100%" in launchers.summary
    keyboards = _finding(result, "third_party_apps.several-keyboards")
    assert keyboards.severity == "info"
    assert keyboards.metrics["enabled_input_methods"] == 3
    assert [e.ref for e in keyboards.evidence] == [
        "live/settings.txt:6",
        "live/settings.txt:4",
    ]
    rows = {r["package"]: r for r in result.tables["apps"]}
    row = rows["com.example.dormant"]
    assert row["installed_days"] == pytest.approx(745.1)
    assert row["never_launched"] is False


def test_third_party_apps_home_is_system_launcher(context_factory):
    live = dict(LIVE)
    live["home_activity"] = "com.android.launcher3/com.android.searchlauncher.X\n"
    ctx = context_factory(
        live=live,
        packages=PACKAGES_ALL,
        windows=WINDOWS,
        services={"package": PACKAGE_DUMP},
    )
    result = apps.third_party_apps(ctx)
    assert "third_party_apps.two-launchers" not in _ids(result)


def test_third_party_apps_from_package_dump_only(context_factory):
    # Without packages_3p, analyze.build_packages takes the third-party app
    # ids from dumpsys package; the context factory does not.
    ctx = context_factory(windows=WINDOWS, services={"package": PACKAGE_DUMP})
    ctx.packages = PackageMap.from_package_dump(PACKAGE_DUMP)
    result = apps.third_party_apps(ctx)
    assert result.metrics["third_party_apps"] == 2
    assert {r["package"] for r in result.tables["apps"]} == {
        "com.example.dormant",
        "com.example.newapp",
    }
    assert "No usage statistics: dormancy is unknown." in result.notes


def test_third_party_apps_metrics(context_factory):
    ctx = context_factory(live=LIVE, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    metrics = result.metrics
    assert metrics["third_party_apps"] == 8
    assert metrics["third_party_list_source"] == "live/packages_3p.txt"
    assert metrics["multi_user_installs"] == 1
    assert metrics["apps_without_usage_record"] == 0
    assert metrics["apps_never_launched_in_usage_window"] == 3
    assert metrics["exempt_third_party_apps"] == 4
    assert metrics["notification_listeners"] == 2
    assert metrics["accessibility_services"] == 1
    assert metrics["background_restricted_apps"] == 1
    assert metrics["procstats_window_h"] == pytest.approx(21.1)
    assert result.tables["apps"][0]["package"] == "com.example.dormant"


def test_third_party_apps_truncated_usage_does_not_crash(context_factory):
    live = dict(LIVE)
    live["usagestats"] = USAGESTATS + (
        "  package=com.example.app u=0 bucket=10 reason=u-ma used=+1h usedByUser=+1"
    )
    ctx = context_factory(live=live, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.third_party_apps(ctx)
    assert "1 usage lines could not be parsed." in result.notes


def test_third_party_apps_skips_without_package_list(context_factory):
    ctx = context_factory(live={"usagestats": USAGESTATS}, windows=WINDOWS)
    with pytest.raises(SkipError, match="third-party package list"):
        apps.third_party_apps(ctx)


def test_third_party_apps_bugreport_fallbacks(context_factory):
    settings_dump = dedent(
        """\
        SECURE SETTINGS (user 0)
        _id:2 name:enabled_notification_listeners pkg:android value:com.example.dormant/.L
        """,  # ruff: ignore[line-too-long] - dump lines are long
    )
    activity_dump = dedent(
        """\
        ACTIVITY MANAGER PENDING INTENTS (dumpsys activity intents)
          * ServiceRecord{9 u0 com.example.newapp/.Svc c:com.example.newapp}
            isForeground=true foregroundId=1 types=0x00000001
        """,
    ) + ACTIVITY_SERVICES.replace("com.example.push", "com.example.dormant")
    ctx = context_factory(
        windows=WINDOWS,
        services={
            "package": PACKAGE_DUMP,
            "settings": settings_dump,
            "activity": activity_dump,
        },
    )
    ctx.packages = PackageMap.from_package_dump(PACKAGE_DUMP)
    result = apps.third_party_apps(ctx)
    rows = {r["package"]: r for r in result.tables["apps"]}
    assert rows["com.example.dormant"]["notification_listener"] is True
    assert rows["com.example.dormant"]["fgs_types_now"] == "specialUse"
    assert rows["com.example.newapp"]["fgs_types_now"] is None
    assert rows["com.example.newapp"]["never_launched"] is True


# --- app_background_activity ------------------------------------------------------


def test_background_activity_drain_split(ctx_factory):
    result = apps.app_background_activity(ctx_factory())
    m = result.metrics
    assert m["model_uid_sum_mah"] == pytest.approx(138.2)
    assert m["core_mah"] == pytest.approx(70.0)
    assert m["third_party_mah"] == pytest.approx(59.2)
    assert m["third_party_screen_mah"] == pytest.approx(50.0)
    assert m["third_party_nonscreen_mah"] == pytest.approx(9.2)
    assert m["third_party_background_mah"] == pytest.approx(7.7)
    assert m["preinstalled_app_mah"] == pytest.approx(9.0)
    assert m["share_basis"] == "measured_drain"
    assert m["unbilled_mah"] == pytest.approx(61.8)
    assert m["third_party_nonscreen_share_pct"] == pytest.approx(4.6)
    share = _finding(result, "app_background_activity.third-party-share")
    assert share.severity == "info"
    assert share.basis == "modelled"
    assert share.evidence[0].ref == "live/batterystats_charged.txt:3"


def test_background_activity_major_share(ctx_factory):
    live = dict(LIVE)
    live["batterystats_charged"] = BATTERYSTATS_CHARGED.replace(
        "UID u0a150: 6.00 bg: 6.00 ( cpu=6.00 cpu:bg=6.00 )",
        "UID u0a150: 60.0 bg: 60.0 ( cpu=60.0 cpu:bg=60.0 )",
    )
    result = apps.app_background_activity(ctx_factory(live))
    share = _finding(result, "app_background_activity.third-party-share")
    assert share.severity == "medium"


def test_background_activity_middle_share_has_no_finding(ctx_factory):
    live = dict(LIVE)
    live["batterystats_charged"] = BATTERYSTATS_CHARGED.replace(
        "UID u0a150: 6.00 bg: 6.00 ( cpu=6.00 cpu:bg=6.00 )",
        "UID u0a150: 30.0 bg: 30.0 ( cpu=30.0 cpu:bg=30.0 )",
    )
    result = apps.app_background_activity(ctx_factory(live))
    assert "app_background_activity.third-party-share" not in _ids(result)


def test_background_activity_model_above_measured_drain(ctx_factory):
    # The model bills 138.2 mAh to UIDs but the counter measured 100 mAh:
    # nothing is unbilled and shares are of the model, never negative.
    live = dict(LIVE)
    live["batterystats_charged"] = BATTERYSTATS_CHARGED.replace(
        "Discharge: 200 mAh",
        "Discharge: 100 mAh",
    )
    result = apps.app_background_activity(ctx_factory(live))
    m = result.metrics
    assert m["share_basis"] == "model"
    assert m["unbilled_mah"] == pytest.approx(0.0)
    assert m["unbilled_share_pct"] == pytest.approx(0.0)
    assert m["model_excess_mah"] == pytest.approx(38.2)
    assert m["third_party_nonscreen_share_pct"] == pytest.approx(6.7)
    share = _finding(result, "app_background_activity.third-party-share")
    assert share.severity == "info"
    assert "modelled drain" in share.title
    assert "exceeds the 100 mAh measured drain" in share.summary
    assert "(level-based estimate 180-220 mAh)" in share.summary
    assert "billed to no UID" not in share.summary


def test_background_activity_model_above_drain_never_medium(ctx_factory):
    live = dict(LIVE)
    live["batterystats_charged"] = BATTERYSTATS_CHARGED.replace(
        "Discharge: 200 mAh", "Discharge: 100 mAh"
    ).replace(
        "UID u0a150: 6.00 bg: 6.00 ( cpu=6.00 cpu:bg=6.00 )",
        "UID u0a150: 60.0 bg: 60.0 ( cpu=60.0 cpu:bg=60.0 )",
    )
    result = apps.app_background_activity(ctx_factory(live))
    share = _finding(result, "app_background_activity.third-party-share")
    # 63.2 of 192.2 mAh is a main share of the model, but not of the drain.
    assert result.metrics["third_party_nonscreen_share_pct"] == pytest.approx(32.9)
    assert share.severity == "low"


def test_background_activity_top_sleeping_threshold(ctx_factory):
    result = apps.app_background_activity(ctx_factory())
    finding = _finding(result, "app_background_activity.top-sleeping")
    # u0a102 (45 min) crosses 30 min; u0a150 (10 min) does not.
    assert finding.metrics == {"apps": 1, "max_top_sleeping_h": 0.75}
    assert "com.example.active 0.8 h" in finding.summary


def test_background_activity_table(ctx_factory):
    result = apps.app_background_activity(ctx_factory())
    rows = {r["uid"]: r for r in result.tables["apps"]}
    assert result.tables["apps"][0]["uid"] == "u0a199"  # largest background mAh
    assert rows["u0a150"]["wakeup_alarms"] == 30
    assert rows["u0a150"]["class"] == "third_party"
    assert rows["u0a140"]["class"] == "preinstalled_app"
    assert rows["u0a101"]["bt_scan_s"] == 14400
    assert rows["u0a101"]["cpu_s"] == pytest.approx(25.5)
    assert "u0" not in {r["uid"] for r in result.tables["apps"]}


def test_background_activity_truncated_counter_line(ctx_factory):
    live = dict(LIVE)
    live["batterystats_charged"] = BATTERYSTATS_CHARGED + CUT_UID_BLOCK
    result = apps.app_background_activity(ctx_factory(live))
    assert any("1 per-UID batterystats lines" in n for n in result.notes)
    rows = {r["uid"]: r for r in result.tables["apps"]}
    assert rows["u0a169"]["cpu_s"] == pytest.approx(1.5)


def test_background_activity_on_battery_power_states(ctx_factory):
    result = apps.app_background_activity(
        ctx_factory({"batterystats_charged": POWER_STATES}),
    )
    m = result.metrics
    assert m["third_party_mah"] == pytest.approx(40.0)
    assert m["third_party_screen_mah"] == pytest.approx(10.0)
    assert m["third_party_background_mah"] == pytest.approx(16.67)


def test_background_activity_without_third_party_list(context_factory):
    live = {"batterystats_charged": BATTERYSTATS_CHARGED}
    ctx = context_factory(live=live, windows=WINDOWS)
    result = apps.app_background_activity(ctx)
    assert result.metrics["app_mah"] == pytest.approx(68.2)
    assert "third_party_mah" not in result.metrics
    assert "app_background_activity.third-party-share" not in _ids(result)


def test_background_activity_skips_without_batterystats(context_factory):
    ctx = context_factory(live={"packages_3p": PACKAGES_3P}, windows=WINDOWS)
    with pytest.raises(SkipError, match="batterystats"):
        apps.app_background_activity(ctx)


# --- uid_package_map --------------------------------------------------------------


def test_uid_package_map_flags_power_on_unknown_uids(context_factory):
    live = {
        "batterystats_charged": BATTERYSTATS_CHARGED,
        "alarm": ALARM,
        "netstats": NETSTATS,
    }
    ctx = context_factory(live=live, packages=PACKAGES_ALL, windows=WINDOWS)
    result = apps.uid_package_map(ctx)
    m = result.metrics
    assert m["unmapped_app_uids"] == 1
    assert m["unmapped_app_model_mah"] == pytest.approx(7.0)
    assert m["shared_uids"] == 2  # 1000 and u0a140
    assert m["pseudo_uids"] == 1
    assert m["app_uid_coverage_pct"] == pytest.approx(80.0)
    finding = _finding(result, "uid_package_map.unmapped-power")
    assert finding.basis == "modelled"
    assert finding.metrics["uids"] == "u0a199"
    assert finding.evidence[0].excerpt == "UID u0a199: 7.00 ( cpu=7.00 )"
    shared = {r["label"]: r for r in result.tables["shared"]}
    assert shared["u0a140"]["names"] == "com.example.shared.a, com.example.shared.b"
    assert result.tables["pseudo"][0]["seen_in"] == "netstats"


def test_uid_package_map_names_uids_from_checkin(context_factory):
    live = {
        "batterystats_charged": BATTERYSTATS_CHARGED,
        "batterystats_checkin": CHECKIN,
    }
    ctx = context_factory(live=live, packages=PACKAGES_ALL, windows=WINDOWS)
    # analyze.build_packages merges the checkin's package rows.
    ctx.packages = ctx.packages.merge(PackageMap.from_checkin(CHECKIN))
    result = apps.uid_package_map(ctx)
    assert result.metrics["unmapped_app_uids"] == 0
    assert result.metrics["isolated_uids"] == 1
    assert result.findings == []


def test_uid_package_map_without_package_list(context_factory):
    live = {"batterystats_checkin": CHECKIN}
    ctx = context_factory(live=live, windows=WINDOWS)
    result = apps.uid_package_map(ctx)
    assert any("No package list" in n for n in result.notes)
    # u0a101 and u0a199 (the isolated u0i3 is not an app UID).
    assert result.metrics["app_uids_seen"] == 2
    assert result.metrics["app_uids_mapped"] == 0
    ctx.packages = PackageMap.from_checkin(CHECKIN)
    assert apps.uid_package_map(ctx).metrics["app_uids_mapped"] == 1


def test_uid_package_map_skips_without_batterystats(context_factory):
    ctx = context_factory(live={"packages_3p": PACKAGES_3P}, windows=WINDOWS)
    with pytest.raises(SkipError, match="batterystats"):
        apps.uid_package_map(ctx)
