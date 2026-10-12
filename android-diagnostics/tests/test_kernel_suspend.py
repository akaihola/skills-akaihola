"""Tests for the kernel-log suspend analyzer and the suspend service counters."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from textwrap import dedent

import pytest
from androiddiag.kernel_suspend import (
    kernel_suspend,
    parse_suspend_control,
    suspend_stats,
    template,
)
from androiddiag.model import SkipError, Windows
from androiddiag.source import Text

KERNEL_LOG = "KERNEL LOG (dmesg)"
LOGCAT_KERNEL_LOG = "KERNEL LOG (logcat -b kernel -v threadtime -d *:v)"
RESET_TEMPLATE = "sd N:N:N:N: Power-on or device reset occurred"
EPOCH_START = 1_768_471_200  # 2026-01-15 10:00:00 UTC

# Cycle templates: "<offset seconds> <message>" lines, shifted by the builder.
DEEP = dedent(
    """\
    0.000 PM: suspend entry (deep)
    0.020 Freezing user space processes ... (elapsed 0.020 seconds) done.
    0.100 Disabling non-boot CPUs ...
    0.110 pm_system_irq_wakeup: 41 triggered WLAN_CE_2
    0.150 CPU1 is up
    0.200 Resume caused by IRQ 41, WLAN_CE_2
    0.210 PM: suspend exit
    """,
)
DEEP_WITH_RESET = dedent(
    """\
    0.000 PM: suspend entry (deep)
    0.050 sd 0:0:0:2: Power-on or device reset occurred
    0.100 Disabling non-boot CPUs ...
    0.200 Resume caused by IRQ 41, WLAN_CE_2
    0.210 PM: suspend exit
    """,
)
NETLINK = dedent(
    """\
    0.000 PM: suspend entry (deep)
    0.050 sd 0:0:0:1: Power-on or device reset occurred
    0.080 PM: Pending Wakeup Sources: NETLINK NETLINK
    0.081 PM: Some devices failed to suspend, or early wake event detected
    0.100 Abort: Pending Wakeup Sources: NETLINK NETLINK
    0.110 PM: suspend exit
    """,
)
EVENTPOLL = dedent(
    """\
    0.000 PM: suspend entry (deep)
    0.020 PM: Last active Wakeup Source: eventpoll
    0.021 Freezing of tasks aborted after 0.017 seconds
    0.050 Abort: Last active Wakeup Source: eventpoll
    0.060 PM: suspend exit
    """,
)
# A binder error inside a successful attempt must not count as an abort.
DEEP_WITH_BINDER_ERROR = DEEP.replace(
    "0.110 pm_system",
    "0.105 binder: 1:1 ioctl 40046210 7f00a0b004 returned -22\n0.110 pm_system",
)


def build_log(blocks: list[tuple[float, str]]) -> str:
    """Render ``(start, cycle template)`` pairs as printk lines."""
    out = []
    for start, block in blocks:
        for line in block.splitlines():
            offset, msg = line.split(" ", 1)
            out.append(f"<6>[{start + float(offset):12.6f}] {msg}")
    return "\n".join(out)


def audit(t: float, epoch: float) -> tuple[float, str]:
    return (
        t,
        f'0.000 type=1400 audit({epoch:.3f}:7): avc: denied {{ read }} for comm="x"',
    )


def healthd(t: float, chg: str, status: int = 3) -> tuple[float, str]:
    line = (
        f"0.000 healthd: battery l=50 v=3800 t=25.0 h=2 st={status} c=-100000 "
        f"fc=3000000 cc=100 chg={chg}"
    )
    return t, line


def churn_blocks(
    rounds: int = 12,
    deep: str = DEEP,
    *,
    suspended_s: float = 60.0,
) -> list[tuple[float, str]]:
    """Deep suspend followed by a NETLINK and an eventpoll abort, in two orders."""
    blocks = [healthd(999.0, ""), audit(999.5, EPOCH_START)]
    t = 1000.0
    for i in range(rounds):
        order = (deep, NETLINK, EVENTPOLL) if i % 2 else (deep, EVENTPOLL, NETLINK)
        for block, gap in zip(order, (0.3, 0.3, 2.5), strict=True):
            blocks.append((t, block))
            t += gap
    blocks.extend(
        (
            audit(t, EPOCH_START + (t - 999.5) + suspended_s),
            healthd(t + 0.1, "u", status=2),
            (t + 1.0, DEEP),
        ),
    )
    return blocks


def to_logcat(log: str, asleep_s: float = 5.0) -> str:
    """Rewrite printk lines the way logd prints them for 'logcat -b kernel'.

    logd's clock jumps forward by ``asleep_s`` at the exit of every attempt
    that reached suspend. It splits "healthd: " into the tag, and this
    kernel prints the CPU and PID before other messages.
    """
    start = datetime(2026, 1, 15, 10, 0, 0)
    out = ["--------- beginning of kernel"]
    first = jump = 0.0
    resumed = False
    for line in log.splitlines():
        m = re.match(r"<\d>\[\s*([\d.]+)\] (.*)", line)
        assert m, line
        t, msg = float(m[1]), m[2]
        first = first or t
        resumed = (resumed or "Resume caused by" in msg) and "entry" not in msg
        if "PM: suspend exit" in msg and resumed:
            jump += asleep_s
        stamp = start + timedelta(seconds=round(t - first + jump, 3))
        tag, rest = ("healthd", msg[9:]) if msg.startswith("healthd: ") else ("", msg)
        if not tag:
            rest = f"c1    123 {rest}"
        out.append(
            f"{stamp:%m-%d %H:%M:%S}.{stamp.microsecond // 1000:03d}  root     0"
            f"     0 I {tag:<8}: {rest}",
        )
    return "\n".join(out)


def run(context_factory, log: str, windows: Windows | None = None):
    ctx = context_factory(sections={KERNEL_LOG: log}, windows=windows)
    return kernel_suspend(ctx)


def test_classifies_attempts_and_cuts_at_plug_in(context_factory):
    result = run(context_factory, build_log(churn_blocks()))
    m = result.metrics
    assert m["suspend_attempts"] == 36
    assert m["deep_suspends"] == 12
    assert m["aborted_attempts"] == 24
    assert m["attempts_while_plugged"] == 1
    assert m["aborts_per_deep_resume"] == pytest.approx(2.0)
    plug_in = m["log_last_kernel_s"] - 1.11  # the plug-in precedes one last cycle
    assert m["plug_in_kernel_s"] == pytest.approx(plug_in, abs=0.01)
    reasons = {r["reason"]: r["attempts"] for r in result.tables["abort_reasons"]}
    assert reasons == {
        "Pending Wakeup Sources: NETLINK NETLINK": 12,
        "Last active Wakeup Source: eventpoll": 12,
    }
    assert result.tables["resume_reasons"] == [{"irq": "41 WLAN_CE_2", "resumes": 12}]
    assert result.tables["aborts_between_deep_suspends"] == [
        {"aborts": 2, "times": 11},
    ]
    backoff = result.tables["backoff_by_abort_position"]
    assert [r["median_gap_s"] for r in backoff] == pytest.approx([0.21, 2.39], abs=0.01)
    # The abort rate on battery is wakeup_reasons' finding; here it is a metric.
    assert [f.id for f in result.findings] == ["kernel_suspend.abort-precursor-1"]


def test_attempts_before_a_plugged_first_healthd_line_are_kept(context_factory):
    """On battery healthd may log nothing, so its oldest line can be the plug-in."""
    blocks = [b for b in churn_blocks() if "chg= " not in b[1] + " "]
    result = run(context_factory, build_log(blocks))
    m = result.metrics
    assert m["suspend_attempts"] == 36
    assert m["attempts_charger_unknown"] == 36
    assert m["attempts_while_plugged"] == 1
    assert any("unknown charger state" in n for n in result.notes)
    assert "kernel_suspend.abort-precursor-1" in [f.id for f in result.findings]


def test_overhead_counts_only_the_backoff_after_aborts(context_factory):
    """A gap longer than the back-off is time wakelocks held, not abort cost."""
    blocks = [healthd(999.0, "")]
    t = 1000.0
    for i in range(12):
        held = 4.8 if i == 5 else 0.0
        blocks += [(t, DEEP), (t + 0.31, NETLINK), (t + 0.62 + held, EVENTPOLL)]
        t += 1.08 + held
    blocks.append((t, DEEP))
    result = run(context_factory, build_log(blocks))
    m = result.metrics
    assert m["abort_backoff_gaps_s"] == pytest.approx(7.2)
    assert m["abort_gaps_beyond_backoff_s"] == pytest.approx(4.8)
    assert m["kernel_awake_window_s"] == pytest.approx(18.0)
    assert m["abort_overhead_pct"] == pytest.approx(51.5)
    backoff = result.tables["backoff_by_abort_position"]
    assert [r["backoff_s"] for r in backoff] == pytest.approx([0.2, 0.4])


def test_resume_rate_counts_only_time_off_the_charger(context_factory):
    blocks = [
        healthd(100.0, "u", status=2),
        audit(100.5, EPOCH_START),
        audit(700.5, EPOCH_START + 600),  # ten minutes awake on the charger
        healthd(701.0, ""),
    ]
    t = 702.0
    for _ in range(12):  # 5 s of wall time per cycle
        blocks.append((t, DEEP))
        t += 0.3
    blocks.append(audit(t, EPOCH_START + 661.5))
    m = run(context_factory, build_log(blocks)).metrics
    assert m["unplug_kernel_s"] == pytest.approx(701.0)
    assert m["deep_resumes_per_wall_min"] == pytest.approx(11.8)


def test_resume_rate_uses_only_the_stamped_part_of_the_log(context_factory):
    blocks = [healthd(999.0, "")]
    t, wall = 1000.0, EPOCH_START
    for i in range(30):  # one resume per 10 s of wall time
        if i == 25:
            blocks.append(audit(t - 0.01, wall - 0.01))
        blocks.append((t, DEEP))
        t, wall = t + 0.3, wall + 10.0
    blocks.append(audit(t, wall))
    m = run(context_factory, build_log(blocks)).metrics
    assert m["deep_resumes_per_wall_min"] == pytest.approx(6.0)


def test_logcat_kernel_log_gives_the_dmesg_results(context_factory):
    log = build_log(churn_blocks())
    dmesg = run(context_factory, log)
    ctx = context_factory(sections={LOGCAT_KERNEL_LOG: to_logcat(log)})
    logcat = kernel_suspend(ctx)
    m = logcat.metrics
    assert m["kernel_log_format"] == "logcat"
    for key in (
        "suspend_attempts",
        "deep_suspends",
        "aborted_attempts",
        "attempts_while_plugged",
        "healthd_samples",
        "wall_clock_anchors",
    ):
        assert m[key] == dmesg.metrics[key], key
    for key in (
        "median_deep_attempt_s",
        "median_awake_per_real_wake_s",
        "abort_overhead_pct",
        "log_suspended_s",
    ):
        # Removing logd's jump also drops the 10 ms before each exit line.
        assert m[key] == pytest.approx(dmesg.metrics[key], rel=0.01, abs=0.02), key
    assert [f.metrics["template"] for f in logcat.findings] == [RESET_TEMPLATE]
    assert "Power-on or device reset" in logcat.findings[0].evidence[0].excerpt


def test_wall_clock_from_audit_stamps_and_estimated_offset(context_factory):
    windows = Windows(dump_time=datetime(2026, 1, 15, 12, 2, 0))
    result = run(context_factory, build_log(churn_blocks()), windows)
    m = result.metrics
    assert m["log_first_utc"] == "2026-01-15 10:00:00"
    assert m["log_suspended_s"] == pytest.approx(60.0, abs=0.1)
    assert m["log_first_local"] == "2026-01-15 12:00:00"
    assert m["utc_offset_estimated"] is True


def test_known_offset_is_used_as_is(context_factory):
    windows = Windows(dump_time=datetime(2026, 1, 15, 3, 0), utc_offset="-0700")
    result = run(context_factory, build_log(churn_blocks()), windows)
    assert result.metrics["log_first_local"] == "2026-01-15 03:00:00"
    assert result.metrics["utc_offset_estimated"] is False


def test_android_utc_suspend_stamps_and_caller_ids(context_factory):
    log = dedent(
        """\
        [  100.000000][  T120] PM: suspend entry 2026-01-15 10:00:00.123456789 UTC
        [  100.050000][  T120] PM: Pending Wakeup Sources: example_ws
        [  100.060000][  T120] PM: suspend exit 2026-01-15 10:00:00.183456789 UTC
        [  100.400000][  T120] PM: suspend entry 2026-01-15 10:00:00.523456789 UTC
        [  100.500000][  T120] Disabling non-boot CPUs ...
        [  100.600000][  T120] Resume caused by IRQ 12, example_irq
        [  100.610000][  T120] PM: suspend exit 2026-01-15 10:05:00.633456789 UTC
        """,
    )
    m = run(context_factory, log).metrics
    assert (m["deep_suspends"], m["aborted_attempts"]) == (1, 1)
    assert m["log_suspended_s"] == pytest.approx(299.9, abs=0.05)


def test_precursor_finding_fires_for_the_reset_message(context_factory):
    result = run(context_factory, build_log(churn_blocks()))
    precursors = [f for f in result.findings if "precursor" in f.id]
    assert len(precursors) == 1
    finding = precursors[0]
    assert finding.metrics["template"] == RESET_TEMPLATE
    assert finding.metrics["class_pct"] == pytest.approx(100.0)
    assert finding.metrics["deep_pct"] == pytest.approx(0.0)
    assert finding.basis == "measured"
    assert "inferred" in finding.summary
    assert "Power-on" in finding.evidence[0].excerpt
    assert finding.evidence[1].excerpt.endswith("NETLINK NETLINK")
    rows = {r["template"]: r for r in result.tables["messages_before_aborts"]}
    assert rows[RESET_TEMPLATE]["abort_attempts"] == 12
    assert rows[RESET_TEMPLATE]["deep_attempts"] == 0
    assert rows["CPUN is up"]["abort_attempts"] == 12


def test_precursor_does_not_fire_when_successful_attempts_share_it(context_factory):
    result = run(context_factory, build_log(churn_blocks(deep=DEEP_WITH_RESET)))
    assert not [f for f in result.findings if "precursor" in f.id]
    row = next(
        r
        for r in result.tables["abort_cooccurrence"]
        if r["template"].startswith("sd N")
    )
    assert row["deep_pct"] == pytest.approx(100.0)


def test_errors_inside_successful_attempts_are_not_aborts(context_factory):
    calm = run(
        context_factory,
        build_log([(1000.0 + 5 * i, DEEP_WITH_BINDER_ERROR) for i in range(12)]),
    )
    assert calm.metrics["aborted_attempts"] == 0
    assert not calm.findings


def test_no_attempts_and_no_anchors(context_factory):
    result = run(context_factory, "<6>[  10.000000] example: hello\n")
    assert result.metrics["suspend_attempts"] == 0
    assert result.metrics["wall_clock_anchors"] == 0
    assert any("No suspend attempts" in n for n in result.notes)


def test_missing_or_unparsable_kernel_log_skips(context_factory):
    with pytest.raises(SkipError, match="no kernel log"):
        kernel_suspend(context_factory(live={"battery": "level: 50"}))
    with pytest.raises(SkipError, match="neither dmesg nor logcat"):
        run(context_factory, "not a kernel log\nat all\n")


def test_template_normalises_numbers_and_addresses():
    assert template("sd 0:0:0:4: Power-on or device reset occurred") == (RESET_TEMPLATE)
    assert template(
        "[soft_i][0x1a2b3c4d][10:00:00.700000] wlan: Src_mac: 02:00:00:00:00:01",
    ) == ("wlan: Src_mac: <mac>")
    assert template("ioctl 7f00a0b004 from 192.0.2.7") == "ioctl <hex> from <ip>"


SUSPEND_CONTROL = dedent(
    """\
    Service host process PID: 100

    Wakeups:
    WakeupInfo{name: 41 WLAN_CE_2, count: 500}
    WakeupInfo{name: Abort: Pending Wakeup Sources: NETLINK NETLINK, count: 700}
    WakeupInfo{name: Abort: Last active Wakeup Source: eventpoll, count: 300}
    WakeupInfo{name: 10 example_irq, count: 20}

    ----- Suspend Stats -----
    success: SUCCESS_COUNT
    fail: FAIL_COUNT
    failed_freeze: 300
    failed_suspend: 700

    Last Failures:
        last_failed_dev: example_device
        last_failed_errno: -16
        last_failed_step: suspend
    ----------

    Suspend Info:
    suspend attempts: 1520
    total suspend time: 6000000 ms
    failed suspend overhead: 900000 ms
    new backoffs: 450
    """,
)


def stats_ctx(context_factory, success: int, fail: int):
    body = SUSPEND_CONTROL.replace("SUCCESS_COUNT", str(success))
    body = body.replace("FAIL_COUNT", str(fail))
    return context_factory(services={"suspend_control_internal": body})


def test_parse_suspend_control():
    body = SUSPEND_CONTROL.replace("SUCCESS_COUNT", "520")
    body = body.replace("FAIL_COUNT", "1000")
    stats, wakeups = parse_suspend_control(Text("example", body))
    assert stats["success"] == 520
    assert stats["total_suspend_time"] == 6_000_000
    assert stats["last_failed_dev"] == "example_device"
    assert [w["kind"] for w in wakeups] == ["resume", "abort", "abort", "resume"]


def test_suspend_stats_metrics(context_factory):
    result = suspend_stats(stats_ctx(context_factory, 520, 1000))
    m = result.metrics
    assert m["fail_share_pct"] == pytest.approx(65.8)
    assert m["total_suspend_time_ms"] == 6_000_000
    assert m["wakeup_aborts"] == 1000
    assert m["aborts_per_resume"] == pytest.approx(1.92)
    top = result.tables["wakeup_reasons"][0]
    assert top["reason"].endswith("NETLINK NETLINK")
    assert top["ref"].startswith("bugreport:")
    # wakeup_reasons.suspend_aborts owns the finding about failed attempts.
    assert not result.findings


def test_suspend_stats_quiet_when_most_attempts_succeed(context_factory):
    result = suspend_stats(stats_ctx(context_factory, 1400, 120))
    assert result.metrics["fail_share_pct"] == pytest.approx(7.9)
    assert not result.findings


def test_suspend_stats_skips_without_counters(context_factory):
    ctx = context_factory(services={"suspend_control_internal": "Threads in use: 0/10"})
    with pytest.raises(SkipError):
        suspend_stats(ctx)
