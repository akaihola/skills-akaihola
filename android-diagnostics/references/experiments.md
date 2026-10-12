# Experiments

An analysis shows what happened and suggests why. An experiment shows how
much a change helps. On phones whose power model cannot see standby drain, an
experiment is the only way to put a number on a fix.

The owner makes every change on the phone. You collect and compare.

## Rules

1. **One change per window.** Two changes at once cannot be told apart.
2. **Same conditions.** Same place and network, same time of day, phone lying
   still with the screen off. Overnight windows work well. Note anything
   unusual, such as a trip, a call or an update.
3. **Long enough.** At least 2 hours of screen-off time on battery, and long
   enough that the screen-off discharge spans several gauge steps.
   `results.gauge_quantization.metrics` gives the step (`step_mah`) and the
   minimum test length (`min_screen_off_test_h`). At low drain rates that
   means a whole night.
4. **Counters, not the display.** Compare the counter-based screen-off
   discharge. The displayed percentage lags in Doze. Settings > Battery usage
   shows the power model, which on many phones prices sleep at 0 mA and
   cannot show what a wake costs.
5. **Disconnect adb during the window.** adb traffic over Wi-Fi wakes the
   phone. Run `adb disconnect`, or turn wireless debugging off, and connect
   again at the end.

## Protocol

The simplest protocol uses one charge per window:

1. Charge to full and unplug. Android starts new since-charge statistics.
2. The owner applies the change, or nothing for the baseline.
3. The phone lies screen-off for the window. Some use is fine; the analyzers
   separate screen-on from screen-off time.
4. Before plugging in, collect:
   `uv run --script SKILL_DIR/scripts/collect.py --out /tmp/android-diagnostics --no-bugreport`.
   Leave out `--no-bugreport` if the kernel log matters, for example to see
   which sender wakes the phone. The kernel log covers only the last minutes.
5. Analyse the new workdir.
6. Next charge: the other condition.

Two windows within one charge also work. Save a snapshot at the start and end
of each window, for example
`adb_ro.py --save batterystats_charged_a1 --workdir WORKDIR -- dumpsys batterystats --charged`,
and subtract the counters by hand: screen-off discharge, screen-off time,
wakeup reason counts. `analyze.py` does not read such extra keys, and its
history-based results cover the whole charge, so this is more work.

## What to compare

| Measure | Where in analysis.json |
|---|---|
| Screen-off drain, mAh/h | `results.discharge_accounting.metrics.screen_off_mah_per_h` |
| Deep-Doze drain, mAh/h | `results.discharge_accounting.metrics.deep_doze_mah_per_h` |
| Awake share with the screen off, % | `results.standby_wake.metrics.awake_share_pct` |
| Resumes per hour, screen off | `results.standby_wake.metrics.resumes_per_h` |
| Top wake reason and its share | `results.standby_wake.metrics.top_wake_reason`, `top_wake_reason_share_pct` |
| Aborted suspends per real resume | `results.wakeup_reasons.metrics.abort_to_resume_ratio` |
| Gauge step, mAh | `results.gauge_quantization.metrics.step_mah` |

A small comparison of two workdirs:

```bash
python3 - /tmp/android-diagnostics/A/analysis.json /tmp/android-diagnostics/B/analysis.json <<'PY'
import json
import sys

KEYS = [
    ("discharge_accounting", "screen_off_s"),
    ("discharge_accounting", "screen_off_mah_per_h"),
    ("discharge_accounting", "deep_doze_mah_per_h"),
    ("standby_wake", "awake_share_pct"),
    ("standby_wake", "resumes_per_h"),
    ("standby_wake", "top_wake_reason"),
    ("wakeup_reasons", "abort_to_resume_ratio"),
    ("gauge_quantization", "step_mah"),
]
docs = [json.load(open(path)) for path in sys.argv[1:]]
for analyzer, key in KEYS:
    values = [d["results"].get(analyzer, {}).get("metrics", {}).get(key) for d in docs]
    print(f"{analyzer}.{key}: " + " | ".join(str(v) for v in values))
PY
```

## Deciding

- Count a change as real when the screen-off drain differs by more than about
  two gauge steps over the window, and the resumes per hour or the awake
  share move the same way.
- If the resumes drop but the drain does not, wakes were not the main cost.
  Look at the radios next: cellular active time, roaming, IMS handovers.
- Convert to what the owner feels: runtime in hours is the usable capacity in
  mAh divided by the drain in mAh/h.
- Repeat a window when the result is close or the conditions differed.

## Quick checks with live samples

`sample_live.py` takes minutes, not hours. Use it before and after a change to
see whether a sender stopped: the packet rate of one UID, the TCP resets the
phone sends, the multicast that reaches it. It shows that the trigger is gone,
not how much energy that saves. The A/B window does that.

Give each run its own directory, or the second run stops with exit code 2:

```bash
uv run --script SKILL_DIR/scripts/sample_live.py --workdir WORKDIR/sample-before
# the owner makes the change; wait a few minutes in Doze
uv run --script SKILL_DIR/scripts/sample_live.py --workdir WORKDIR/sample-after
```

Then compare `WORKDIR/sample-before/sample-diff.json` with
`WORKDIR/sample-after/sample-diff.json`. Do not use `--force` on a directory
whose sample you still need; it overwrites it.

## Slowness experiments

Change one thing per day and collect at the end of the day, before charging.

- Low-memory kills: `results.kills_vs_screen_events.metrics.on_battery_kills_per_screen_on`
  and `results.exit_info_audit.metrics.low_memory_kills_per_h_on_battery`.
- Frame jank: `frame_jank` works from daily graphicsstats buckets, so each
  condition needs at least a day with enough frames for the apps you compare.
- Launch times: `app_launch_times` reads the log, which rotates. Collect soon
  after opening the apps you care about.

## Comparing two batteries

Capacity belongs to the battery. Drain in mAh/h belongs to the phone, its
software and its surroundings. Runtime is capacity divided by drain. Keep the
two apart:

1. After a battery swap, let the gauge relearn: charge to 100 %, use the
   phone down to about 15 % or lower without charging in between, then charge
   to 100 % again. Some gauges need two or three such cycles. Until then the
   phone may report the old battery's capacity.
2. Read `results.battery_capacity.metrics`: `learned_capacity_mah`, the
   minimum and maximum learned values, and `state_of_health_pct`. The cycle
   count may or may not restart, depending on where the phone stores it.
3. Compare drain in mAh/h under the same conditions, as A/B windows above.
   It should be about the same for both batteries. Percent per hour differs
   because the capacities differ, so never compare batteries by %/h.
4. A worn battery also sags at low charge. Check whether the low-battery
   shutdowns and the fast drops below about 10 % (`low_battery_shutdowns`,
   `daily_steps`) stop with the new one.

Do not compare a new battery's first day with the old battery's long-term
average. Compare like with like: the same window type and the same
conditions.
