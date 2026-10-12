# Interpreting analysis.json

`analyze.py` turns a workdir into `analysis.json`. This file explains its
structure, the rules for reading its numbers, and how to check a finding
against the raw dumps.

The file is large, often close to 1 MB. Read it selectively: the high and
medium `findings` first (SKILL.md shows a one-line listing), then the
`results.NAME` entries your domain needs.

## Top-level structure

| Key | Content |
|---|---|
| `schema`, `generated_at`, `workdir` | Format version, when and from which workdir the file was written. |
| `device` | Build fields: model, build, fingerprint, SDK, kernel. No serial. |
| `windows` | Time anchors shared by all analyzers. Any field may be `null`. |
| `sources` | Logical input key mapped to the file or bugreport section it came from. |
| `results` | One entry per analyzer: `analyzer`, `status`, `reason`, `window`, `metrics`, `tables`, `findings`, `notes`. |
| `findings` | All findings of all analyzers, sorted by severity, then id. |
| `errors` | Tracebacks of analyzers that crashed, and `module NAME` entries for analyzer modules that failed to import. Not empty means exit code 3. |
| `notes` | Inputs that could not be read, such as a truncated zip or a broken `manifest.json`. |

`windows` holds:

- `dump_time` and `boot_time`, in the phone's local wall time;
- `since_charge_start`, when the current since-charge period began;
- `on_battery_s` and `screen_off_on_battery_s`, the lengths of those windows
  in wall time, and `on_battery_uptime_s` and `screen_off_uptime_s`, the time
  the processor was awake in them;
- `on_battery_at_capture`, `false` when the phone was charging during the
  capture;
- `plugged_at`, the plug-in time when it is known, and `plugged_at_source`,
  which says how it was found: "battery history plug-in record", "event log
  battery_status", or "since-charge start + time on battery (estimate)";
- `utc_offset`, such as `+0300`, and `zone`, such as `Europe/Berlin`, when
  they could be determined. Analyzers convert epoch times with the zone, so
  daylight saving time is respected.

## Finding fields

| Field | Meaning |
|---|---|
| `id` | `ANALYZER.SLUG`. Stable across runs, so you can compare two workdirs. |
| `title`, `summary` | One line and one or two sentences with the key numbers. |
| `symptom` | `battery`, `slowness`, `both` or `info`. |
| `severity` | `high`, `medium`, `low` or `info`. |
| `basis` | `measured`, `modelled` or `inferred`. See below. |
| `window` | Which time the numbers cover. See below. |
| `metrics` | The numbers behind the summary. The unit is in the key name. |
| `evidence` | `ref` and a short `excerpt` of each cited line. |
| `recommendation` | Generic advice: a Settings path or what to look into. |
| `followups` | Checks that would confirm or refute the finding. Phone reads are written as `adb_ro.py --save KEY --workdir WORKDIR -- COMMAND`. |
| `related` | Ids of other findings that state the same fact or part of it. Links usually go both ways. The report lists the weaker finding under the stronger one as "Also reported"; count the fact once. |

Severity comes from thresholds in each analyzer module. They are rules of
thumb, and each module sets them on its own. A `high` in one module and a
`medium` in another are not calibrated against each other. Rank causes
yourself by their share of the drain or of the slowness.

## Windows

| Window | Covers | Typical sources |
|---|---|---|
| `since_charge` | Since the last full charge, plugged time included | `batterystats --charged` |
| `on_battery` | Time on battery since the last full charge | batterystats summary and history |
| `screen_off_on_battery` | The screen-off part of that | battery history spans |
| `since_boot` | Since the last boot, charging time included | `ps` CPU time, exit-info, vmstat, PSI totals, alarm stats, suspend statistics, power drain stats |
| `last_24h` | The last 24 hours | `procstats --hours 24`, usage stats |
| `daily` | The daily step history, about 10 days | batterystats daily steps, graphicsstats daily buckets |
| `previous_charge` | The charge period before the current one | a saved `--checkin` file, `live/batterystats_checkin_previous.txt` (see [collection.md](collection.md)) |
| `recent_history` | Records kept across reboots | dropbox, exit info, start info |
| `log_coverage` | Whatever the log buffer still holds | logcat (minutes to hours), kernel log (often only minutes) |
| `snapshot` | The moment of collection | meminfo, thermal status, settings |

Rules:

- Label every number with its window, and never add, subtract or compare
  numbers across windows.
- A `since_boot` figure on a phone that charged overnight mostly describes the
  night on the charger.
- Never subtract counters across a reboot.
- A `log_coverage` figure is a sample. A kernel log of 5 minutes says how each
  wake behaves, not how many wakes there were in 5 hours.

## Basis

- **measured.** A gauge, kernel or system counter: charge counter mAh, resume
  counts, awake time, packet counts, kill records. Say "the phone recorded".
- **modelled.** The batterystats power model. It multiplies times by currents
  from the vendor's power profile. Settings > Battery usage shows the same
  model. Say "Android estimates".
- **inferred.** A heuristic or a mechanism the data does not show directly,
  such as "this sender is probably a VPN heartbeat". Say "probably" and name
  the check that would confirm it.

## Rules for reading the numbers

These come from mistakes made and corrected in real diagnoses.

1. **Causes do not add up.** Packet senders, alarms and jobs trigger wakes.
   Suspend aborts and slow re-suspend multiply the cost of each wake. CPU
   time of the suspend service or `ueventd` is a consequence of the wakes.
   Per-cause mAh claims, added up, easily exceed the drain that was observed.
   Build one budget and give shares, or give per-cause figures as upper
   bounds.
2. **The model can be blind.** Many power profiles price CPU suspend and idle
   at 0 or 0.1 mA. Then the cost of a phone that stays awake in standby
   appears in no component. Check `power_model.unmodelled_*` and
   `power_profile`. If much of the drain is unmodelled, do not rank fixes by
   per-app mAh and do not trust Settings > Battery usage.
3. **mAh figures move in gauge steps.** On many phones the batterystats charge
   counter is the state of charge times the learned capacity, in whole
   percent. Every mAh figure is then plus or minus one step, about 1 % of
   capacity. `gauge_quantization` reports the step and the minimum test
   length.
4. **The displayed level lags in Doze.** It stays put while the phone idles,
   then drops when the screen turns on, so owners blame screen time for idle
   drain. Level-based figures, including the daily step extrapolations,
   understate idle drain. Compare counter-based with counter-based.
5. **Ring buffers give lower bounds.** Exit-info keeps 16 exits per package.
   Logcat, the kernel log, the job history and the network stack's log all
   rotate. Write "at least".
6. **Short samples stay short.** A minutes-long kernel log or a 2-minute live
   sample shows a pattern. Do not scale it to hours without saying so.
7. **Live state after plug-in describes charging.** If
   `windows.on_battery_at_capture` is `false`, thermal status, battery saver,
   Doze and live counters describe the charger, not the battery window.
8. **Check where a statistic comes from.** Verifiers repeatedly caught a
   longest-span figure quoted as the overall figure, two equal numbers
   presented as a match, and values read minutes apart presented side by
   side.
9. **UIDs are indirect.** A wakelock can be billed to the app that asked for
   the work. VPN traffic is counted on the tunnel and on the underlying
   network. UID 1000 covers many system packages. Negative UIDs in netstats
   are pseudo-UIDs, and UID 0 is the kernel and root daemons.
10. **Formats vary by locale.** In some locales batterystats and procstats
    print decimal commas (`87,4%`, `4,52MB`) in the same dump as decimal
    points in other lines. Byte units in batterystats are 1024-based. The
    analyzers handle this; when you grep yourself, mind it.
11. **Clocks differ.** The battery history counts from a reset point. Logcat
    uses local wall time. Wi-Fi driver brackets in the kernel log are often
    UTC. Kernel printk seconds stop during suspend. Netstats buckets and boot
    reasons use epoch seconds. Convert before you correlate.
12. **Baselines are rules of thumb.** "A phone that sleeps well idles at
    roughly 10 to 20 mA" and similar figures are general expectations. Say so
    when you use them.

## Building one drain budget

`results.drain_budget` puts the measured discharge, the model's share of it,
the screen-off awake share, the wake triggers and the effect of battery wear
in one place, as layers with shares and no per-cause mAh.
`results.bottom_line` picks the strongest battery and slowness findings and
lists what the data could not show. Quote these instead of summing findings.
If they are missing, build the budget yourself:

1. Start from the counter-based discharge in one window:
   `discharge_accounting` gives screen-on, screen-off and deep-Doze mAh and
   mAh/h.
2. Split the screen-off part by state: `standby_wake` gives the awake share,
   the resumes per hour and the time spent per resume.
3. Attribute wakes by share of resumes, not by mAh: `wakeup_reasons` for the
   interrupt names, `wake_periodicity` for a periodic sender, `qcom_wow` for
   per-packet senders when the kernel log has them.
4. Treat the power model's components as a floor for screen, CPU and radio,
   and report the unmodelled remainder as such.
5. Say what one fix would remove, and on what assumption. For example: "a
   sender that causes 40 % of resumes accounts for roughly 40 % of the awake
   time, if its wakes last as long as the others". Then confirm it with an
   experiment.

## Skipped and failed analyzers

`status: skipped` with a `reason` means an input was missing or the analyzer
does not apply, for example a Qualcomm log parser on another chip. If a
live-only input is missing and the phone is at hand, save it under its catalog
key with `adb_ro.py --save KEY --workdir WORKDIR -- COMMAND` and run
`analyze.py` again. This works only while `live/KEY.txt` does not exist.
[collection.md](collection.md) lists those inputs and the command for each.

`status: error` means the analyzer crashed. The traceback is in `errors`.
Report it as a gap in the analysis; do not guess the missing numbers.

## Opening evidence

`show_ref.py` prints the lines behind one or more refs, with context, and
reads the bugreport zip in place:

```bash
uv run --script SKILL_DIR/scripts/show_ref.py WORKDIR 'bugreport:KERNEL LOG:123456' 'live/batterystats_charged.txt:462' -C 10
```

Quote each ref, because section names contain spaces. The cited line is
marked with `>`. Exit code 2 means a ref did not resolve.

The ref forms:

- `live/KEY.txt:N` is line N of `WORKDIR/live/KEY.txt`.
- `bugreport:SECTION:N` and `bugreport:dumpsys SERVICE:N` are line N of the
  main bugreport text, counted from the top of the whole file, not of the
  section.
- `bugreport:PATH/IN/ZIP:N` is line N of that file inside the zip.

To read more than a few lines around a ref, extract the zip once into a new,
empty directory:

```bash
python3 -m zipfile -e WORKDIR/bugreport.zip WORKDIR/bugreport/
```

The main text is the file named in `main_entry.txt`, or else the largest
`bugreport-*.txt`. It has about a million lines and contains binary bytes.
Read line ranges, for example with `sed -n '1200,1240p' FILE` or your
harness's file reader with an offset. Use `grep -a`. Never print the whole
file.

## Checking a finding

For each finding you verify:

1. Open every evidence line with about 10 lines of context
   (`show_ref.py WORKDIR 'REF' -C 10`). Does the excerpt say what the summary
   claims? Is the line inside the claimed window?
2. Recompute the headline number from the raw lines or from `metrics`.
3. Check the window. Does a `since_boot` number include a night on the
   charger? Does an `on_battery` number include screen-on time?
4. Check the basis. A model value must not be worded as a measurement, and a
   mechanism the data does not show must be labelled inferred.
5. Check for lower bounds and samples: ring buffers, a minutes-long kernel
   log, a two-sample live diff.
6. Look for another explanation: a one-off download, a car trip, a reboot, the
   plug-in burst, the collection itself.
7. Cross-check with an independent source where one exists. For example,
   compare resume counts from batterystats wakeup reasons, from the battery
   history and from the suspend statistics.
8. Give a verdict: confirmed, corrected (with the new numbers), refuted, or
   unverifiable.

## Leads that often turn out false

- "Doze does not work." Check the device-idle time first. Doze can work while
  incoming packets keep waking the phone.
- "Battery saver will fix it." If it was already on, the drain happened with
  it on.
- "Weak signal or 5G." Check signal levels and radio types before blaming
  coverage.
- "Many connectivity changes mean the network flaps." They are often
  capability updates of the same network while the screen is on.
- "A big download is a runaway app." Check whether it ran once, in the
  foreground.
- "Battery health GOOD means the battery is fine." That field only flags
  overheat, dead, over-voltage or cold. Capacity fade shows in the learned
  capacity.
- "Estimated battery capacity" in batterystats is the charge counter divided
  by the level at reset. It is not a capacity measurement.
- On Android 15, "Computed drain" in the power-use header equals the counter
  discharge. It is not the sum of the model.
- "The phone is out of RAM." Check MemAvailable and the memory pressure
  history before blaming total memory. Kills with lots of free memory point
  to other causes; see [vendor-notes.md](vendor-notes.md).
- Forum fixes for one build or app apply only if this phone has that build
  and that app.
