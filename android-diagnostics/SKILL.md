---
name: android-diagnostics
description: >-
  Android battery drain, poor standby time, overheating, lag and background app
  kills: diagnose them on a phone connected over adb, or from a bugreport zip.
  Collects read-only dumpsys, batterystats, logcat and bugreport data, turns it
  into ranked findings with cited evidence using bundled standard-library
  Python scripts, and guides verification, follow-up tests and a report for
  the phone's owner. Use when someone says their Android phone drains its
  battery, dies early, wakes up all night, runs hot, stutters, is slow, or
  keeps killing apps, or asks for a health check of a phone with USB or
  wireless debugging enabled.
compatibility: >-
  Needs adb (Android platform-tools) and a phone that has authorized USB or
  wireless debugging, plus uv or Python 3.11 or newer. A bugreport zip can be
  analysed without adb. The scripts never change the phone's settings.
metadata:
  version: "0.1.0"
---

# Android battery and slowness diagnostics

Find out why an Android phone drains its battery or feels slow, using data the
phone already keeps. Scripts collect and parse the data; you check, explain and
report what they find.

## Read-only rule

- Never change the phone's state. Do not run `settings put`,
  `device_config put`, `pm`/`am`/`cmd` verbs that change things,
  `appops set`, `svc`, `reboot`, `logcat -c`, or `dumpsys ... reset`.
- Never run `dumpsys batterystats --checkin`. It prints the stored previous
  charge period and then deletes it. The scripts use the harmless `-c`.
- Send commands to the phone only through the scripts. For an ad-hoc read, use
  `scripts/adb_ro.py`. It accepts only an allow-list of read-only programs and
  argument forms, and prints the allowed forms when it refuses a command. Do
  not call `adb shell` or `adb logcat` yourself.
- Collection leaves one thing behind: `adb bugreport` keeps a copy of the zip
  in the phone's own bug report storage. Tell the owner.
- Never apply fixes. Recommend them; the owner decides and changes the phone.
- The workdir holds personal data: network names, MAC and IP addresses, the app
  list, account names. Keep it on this machine and out of shared reports.

## Steps

1. Check the prerequisites.
2. Ask about the symptom, then collect at the right moment: `collect.py`.
3. Analyse: `analyze.py` writes `analysis.json`.
4. Draft the report: `report.py`.
5. Interpret by domain, then try to refute every high-severity finding.
6. If needed, run follow-ups on the phone or on other machines, and
   experiments that confirm a fix.
7. Present the results to the owner.

## Script paths

All paths below are relative to this skill's directory, the one that contains
this SKILL.md. Your harness shows it as the skill's location or as "Base
directory for this skill". Below, SKILL_DIR stands for that absolute path and
WORKDIR for the workdir that `collect.py` prints. Write both out in full in
every command. Shell state may not survive between commands, so do not rely
on an earlier `cd` or variable.

Run scripts as `uv run --script SKILL_DIR/scripts/NAME.py ...`. Without uv use
`python3 SKILL_DIR/scripts/NAME.py ...` (`py -3` on Windows). The scripts use
only the standard library. Each has `--help` with its exit codes. They write
results to files and print a short summary.

| Script | What it does | Talks to the phone |
|---|---|---|
| `collect.py` | About 60 read-only dumps and a bugreport into a new WORKDIR | yes |
| `analyze.py WORKDIR` | Parses WORKDIR into `WORKDIR/analysis.json` | no |
| `report.py WORKDIR` | Renders `WORKDIR/report.md` from `analysis.json` | no |
| `show_ref.py WORKDIR REF` | Prints the dump lines behind an evidence ref | no |
| `adb_ro.py -- COMMAND` | Runs one read from the allow-list | yes |
| `sample_live.py --workdir DIR` | Samples live packet and wake counters | yes |
| `perfetto_sql.py` | Optional cross-check with Perfetto | no |

## 1. Prerequisites

Check with `command -v adb uv python3` and `adb devices -l`.

- No adb: ask the owner to install Android platform-tools and to enable
  Settings > System > Developer options > USB debugging or Wireless debugging.
  Stop until they have. If they have a bugreport zip, go to step 3.
- No uv: use `python3` as above. Python must be 3.11 or newer. Offer uv but
  install nothing without the owner's consent.
- The device shows as `unauthorized`: ask the owner to accept the debugging
  prompt on the phone.
- adb cannot connect to its daemon, or fails to start it: the harness sandbox
  is probably blocking localhost TCP port 5037. Rerun the command with the
  harness's approval or escalation mechanism.
- Several devices: pass `--serial SERIAL` to the scripts that talk to the
  phone: `collect.py`, `adb_ro.py` and `sample_live.py`. The others read only
  files and have no such option.

## 2. Timing and collection

Ask what the owner notices, since when, after which update or new app, and
whether the battery was ever replaced. Then collect.

The best moment is right after a typical stretch on battery, before the phone
is plugged in. Plugging in ends the on-battery period, turns a sticky battery
saver off, releases deferred jobs and changes the thermal state. The
since-last-charge statistics stay valid, but every live state then describes
charging. USB debugging charges the phone, so prefer wireless debugging,
especially for live experiments. If the phone is already plugged in, collect
anyway; `collect.py` records it and warns.

```bash
uv run --script SKILL_DIR/scripts/collect.py --out /tmp/android-diagnostics
```

It runs about 60 read-only dumps, then takes a bugreport. Allow 5 to 10
minutes; run it in the background if your harness can. The last line of
stdout is WORKDIR. Exit code 3 means some dumps failed and 4 that the
bugreport failed; the rest is still usable. Optional dumps that the phone
refuses do not count as failures. `--dry-run` shows the adb commands without
running them and `--no-bugreport` saves time but loses the kernel log.
Details, including wireless pairing: [references/collection.md](references/collection.md).

## 3. Analyse

```bash
uv run --script SKILL_DIR/scripts/analyze.py WORKDIR
```

This takes seconds and writes `WORKDIR/analysis.json`. It prints the bottom
line and the strongest findings. For a bugreport zip taken elsewhere, pass
`--bugreport PATH/TO/bugreport.zip` with a new, empty WORKDIR. Exit code 2
means the workdir holds no usable data. Exit code 3 means an analyzer crashed
or a module failed to import (see `errors`). The other analyzers still ran;
mention the gap as a limitation. Inputs that could not be read, such as a
truncated zip, are listed under `notes`.

## 4. Draft the report

```bash
uv run --script SKILL_DIR/scripts/report.py WORKDIR
```

It writes the Markdown draft `WORKDIR/report.md` and runs `analyze.py` first
if `analysis.json` is missing (`--refresh` reruns it). `--format json-summary`
writes a shorter `WORKDIR/report.json`. Each findings list shows its
`--detail N` strongest findings in full (default 6) and the rest in one line,
up to `--max-rows N` entries (default 12). `--appendix` adds every analyzer's
key metrics. `--analysis FILE` and `--output FILE` read and write elsewhere.
Treat the draft as a starting point. Steps 5 and 7 decide what goes to the
owner.

For anything that leaves this machine, render a redacted copy:
`report.py WORKDIR --redact --output WORKDIR/report-redacted.md`. It replaces
MAC and IP addresses, network names, serial-like numbers, e-mail addresses
and phone numbers with placeholders. It does not hide app names; remove those
yourself where they reveal too much.

## How to read analysis.json

`analysis.json` comes close to 1 MB, and the report is about 35 KB with the
default options. Do not read either one whole. Start with the "Bottom
line" section at the top of the report, or the summary `analyze.py` prints.
Then list the high and medium findings:

```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); [print(f['severity'], f['window'], f['id'], '-', f['title']) for f in d['findings'] if f['severity'] in ('high', 'medium')]" WORKDIR/analysis.json
```

Read a single `results.NAME` entry or finding only when a domain needs it.

- `results.bottom_line` and `results.drain_budget`, when present, pick the
  strongest findings and give one drain budget with shares.
- `findings` are sorted by severity. Each has `id`, `title`, `symptom`,
  `severity`, `basis`, `window`, `summary`, `metrics`, `evidence`,
  `recommendation`, `followups` and `related`. `related` links findings that
  state the same fact or part of it. The report lists the weaker one under
  the stronger ("Also reported"). Count that fact once.
- `basis` says how a number was obtained. `measured` comes from a gauge, a
  kernel or a counter. `modelled` comes from the batterystats power model,
  which on many phones prices sleep at 0 mA and misses much of the standby
  drain. `inferred` is a heuristic or a mechanism the data does not show.
- `window` says what time a number covers: `since_charge`, `on_battery`,
  `screen_off_on_battery`, `since_boot`, `last_24h`, `daily`,
  `previous_charge` (the charge period before the current one),
  `recent_history` (records kept across reboots), `log_coverage` or
  `snapshot`. Never add or compare numbers across windows.
- `evidence[].ref` is `live/KEY.txt:LINE` or `bugreport:SECTION:LINE`. Print
  the cited lines with context:
  `uv run --script SKILL_DIR/scripts/show_ref.py WORKDIR 'REF' -C 10`.
  Quote the ref; section names contain spaces.
- `results.NAME` holds each analyzer's `status`, `metrics` (the unit is in the
  key name), capped `tables` and `notes`. Read the notes; they state lower
  bounds and which tables were cut.
- Causes do not add up. Packet senders and alarms trigger wakes, suspend
  aborts multiply each wake, and system CPU is a consequence. Ring-buffer
  counts are lower bounds. Battery mAh figures move in whole-percent steps.

Details: [references/interpretation.md](references/interpretation.md).

## 5. Interpret and verify

[references/domains.md](references/domains.md) splits the work into domains:
battery hardware, standby and wakeups, radios and network, CPU and system,
memory and slowness, apps, and known issues for the build. Each section lists
the results and raw sources to read and the output format.

- If you can start subagents (for example Claude Code's Agent tool, Codex
  `spawn_agent`, OpenCode's task tool or a Pi subagent extension), start one
  per relevant domain in parallel with the prompt given in domains.md. Each
  writes `WORKDIR/findings/DOMAIN.json`.
- Otherwise do the relevant domains yourself, one at a time, and write each
  file before starting the next.
- Then verify. For every high-severity finding and every claim you will lead
  with, open the cited evidence with `show_ref.py` and try to refute it:
  wrong window, a ring buffer read as a total, a short sample extrapolated, a
  model value presented as measured, a coincidence presented as a match. Use
  a fresh subagent per finding if you can. Correct, downgrade or drop what
  does not survive, and record the verdict in the domain file.

## 6. Follow-ups and experiments

- Read one more thing from the phone:
  `uv run --script SKILL_DIR/scripts/adb_ro.py --save wifi_later --workdir WORKDIR -- dumpsys wifi`,
  then grep `WORKDIR/live/wifi_later.txt` locally. `--save` refuses a KEY
  whose file exists, so pick a new name; `collect.py` already used the
  catalog keys. Without `--save` the output goes to stdout.
- Measure what the phone does right now, unplugged, screen off and in Doze:
  `uv run --script SKILL_DIR/scripts/sample_live.py --workdir WORKDIR/sample-before`.
  To compare before and after a change, run it again with
  `--workdir WORKDIR/sample-after` and compare the two `sample-diff.json`
  files. A second run into the same directory stops with exit code 2, and
  `--force` would overwrite the first sample.
- When packets from LAN or VPN peers wake the phone, the fix is often on the
  peer. Capture its traffic to the phone and find the process. Repeated
  connection attempts answered by resets mean a peer keeps dialing a closed
  port. A typical case is a file-sync or companion service on a computer that
  keeps redialing a phone whose app is stopped.
  See [references/followups.md](references/followups.md).
- Confirm a fix with A/B screen-off windows of at least 2 hours each on
  battery, one change at a time. Compare the counter-based screen-off
  discharge in mAh/h, the awake share and the resumes per hour. Do not judge
  by Settings > Battery usage, which shows the power model.
  See [references/experiments.md](references/experiments.md).
- Comparing two batteries: let the new one relearn its capacity over at least
  one full cycle first. Then compare drain in mAh/h, which belongs to the
  phone and its software, separately from capacity, which belongs to the
  battery. Runtime is capacity divided by drain.

Vendor-specific signs, such as Qualcomm Wi-Fi interrupt names, storage resets
that abort suspend, or power profiles that price sleep at 0 mA, are in
[references/vendor-notes.md](references/vendor-notes.md).

## 7. Present the results

- Bottom line first: the one or two main causes and the first thing to do.
- Then the causes ranked by effect, each with its number, window and basis.
  Give one drain budget with shares; never add per-cause mAh. Add what was
  ruled out and what stays uncertain, with the measurement that would settle
  it.
- Actions as Settings paths or steps, ordered by benefit for the effort. Mark
  those that need the owner's judgement.
- Ask before suggesting a purchase, such as a new battery, or uninstalling or
  restricting an app. The owner may rely on it in ways the data cannot show.
- Do not change anything yourself. If the owner asks you to, give the steps.
- Call general expectations what they are. A phone that sleeps well often
  idles at roughly 10 to 20 mA, but that is not a measurement of this phone.
- Refer to other machines and people by role, such as "a desktop on the LAN",
  not by name or address, in anything that leaves this machine. Share only
  the `--redact` rendering of the report (step 4), and read it first.

## Optional tools

- `scripts/perfetto_sql.py` runs SQL over a bugreport with the Perfetto trace
  processor. It downloads a native binary on first use. Use it to cross-check
  battery history numbers, never as the only source.
- [ui.perfetto.dev](https://ui.perfetto.dev) opens `bugreport.zip` in the
  browser and draws a battery timeline. The file is parsed locally. Battery
  Historian is archived; do not use it.

## Reference files

- [references/collection.md](references/collection.md): what `collect.py`,
  `adb_ro.py` and `sample_live.py` do, the `adb_ro.py` allow-list, wireless
  debugging, the workdir layout, privacy and `report.py --redact`.
- [references/interpretation.md](references/interpretation.md): analysis.json
  in detail, windows, pitfalls, and how to open evidence.
- [references/domains.md](references/domains.md): per-domain instructions and
  the finding format.
- [references/followups.md](references/followups.md): host-side and phone-side
  follow-ups.
- [references/experiments.md](references/experiments.md): A/B tests, fix
  confirmation, comparing batteries.
- [references/vendor-notes.md](references/vendor-notes.md): vendor-specific
  things to check.
