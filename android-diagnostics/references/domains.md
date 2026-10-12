# Domains for the interpretation step

`analysis.json` holds about 60 analyzer results and often a hundred findings.
Reading them by domain keeps each pass small. Every domain below names the
results to read first, the raw source keys behind them, what to verify, and
the traps that misled earlier diagnoses.

Skip a domain when nothing in it relates to the owner's complaint and none of
its findings is above `low`. The battery domains matter for drain, the memory
domain for slowness, and the apps and known-issues domains for both.

## How to run a domain

Inputs: WORKDIR, `WORKDIR/analysis.json`, this section, and
[interpretation.md](interpretation.md) for the rules.

1. Read the listed `results.NAME` entries: metrics, tables, notes and
   findings. Read only those entries, not the whole `analysis.json`, which is
   often close to 1 MB.
2. Open the evidence of every finding at `medium` or above with
   `uv run --script SKILL_DIR/scripts/show_ref.py WORKDIR 'REF' -C 10`, as
   described in [interpretation.md](interpretation.md#opening-evidence).
   A finding's `related` ids point to findings in other domains that state
   the same fact; count it once and cite the owning finding.
3. Read the raw sources when a result is skipped, when a number looks odd, or
   when a question in "Verify" needs it. `analysis.json` > `sources` says
   which file or bugreport section each key came from. Live keys are
   `WORKDIR/live/KEY.txt`.
4. Write `WORKDIR/findings/DOMAIN.json` in the format below. Include findings
   you refuted, so the report does not repeat them.

Do not run `adb` in a domain pass. If the phone is still connected and a
read would settle a question, list the `adb_ro.py` command under
`open_questions` and leave it to the main agent.

### Prompt for a subagent

Replace the capitals. DOMAIN is one of `battery`, `standby`, `network`,
`cpu`, `memory`, `apps` and `known_issues`, the keys of the sections below.

```text
You are checking one domain of an Android battery and slowness diagnosis.
Skill directory: SKILL_DIR. Workdir: WORKDIR. Domain: DOMAIN.
Read SKILL_DIR/references/domains.md (the "How to run a domain" part and the
section for DOMAIN) and SKILL_DIR/references/interpretation.md.
Work from WORKDIR/analysis.json and the raw files it cites. Read only the
results and findings of your domain; the file is large. Open cited evidence
with: uv run --script SKILL_DIR/scripts/show_ref.py WORKDIR 'REF' -C 10
Do not run adb or change anything outside WORKDIR/findings/.
Write WORKDIR/findings/DOMAIN.json in the format from domains.md.
Reply with the file path and at most five lines: the main findings with
severity, basis and window.
```

### Output format

```json
{
  "domain": "standby",
  "findings": [
    {
      "id": "standby.periodic-wifi-wakes",
      "title": "A LAN peer wakes the phone about every 3 s with the screen off",
      "symptom": "battery",
      "severity": "high",
      "basis": "measured",
      "window": "screen_off_on_battery",
      "summary": "980 resumes per hour, 94 % of them from the Wi-Fi interrupt; the resumes repeat on a 3.0 s grid.",
      "metrics": {"resumes_per_h": 980, "top_reason_share_pct": 94.0},
      "evidence": [
        {"ref": "live/batterystats_charged.txt:480", "excerpt": "Wakeup reason ...: (4120 times)"}
      ],
      "based_on": ["standby_wake.awake_share", "wake_periodicity.periodic_sender"],
      "verdict": "confirmed",
      "verification": "",
      "recommendation": "Find the sender on the LAN and stop or slow its traffic.",
      "followups": ["Capture traffic to the phone on the suspected peer."]
    }
  ],
  "ruled_out": [
    {"claim": "Doze does not engage", "evidence": [{"ref": "live/batterystats.txt:120", "excerpt": "Device full idling: ..."}]}
  ],
  "open_questions": ["Which peer sends every 3 s? Needs a capture on the LAN."]
}
```

The numbers above are invented. Field rules:

- `id` is `DOMAIN.SLUG`. `symptom`, `severity`, `basis` and `window` take the
  same values as in `analysis.json`.
- `based_on` lists the analyzer finding ids the finding rests on. Leave it
  empty for a finding the analyzers did not make.
- `verdict` is `confirmed`, `corrected` (numbers or wording changed; say how
  in `summary`), `new` or `refuted`.
- `verification` stays empty in the domain pass. The verify pass fills it with
  what was checked and the result.
- Give peers and networks role labels ("the gateway", "a desktop on the LAN",
  "a VPN peer"), never addresses or names.

## battery: battery hardware

Question: is the battery worn or faulty, and how much of a short runtime is
lost capacity rather than high drain?

- Results: `battery_capacity`, `gauge_quantization`, `daily_steps`,
  `low_battery_shutdowns`, `discharge_accounting`, `battery_saver_drain`, and
  on Qualcomm phones `qcom_charging`.
- Raw sources: `batterystats` (daily step history, history `charge=` values),
  `batterystats_checkin`, `health_hal` or `health_aidl`, `battery`, `getprop`
  (boot reason history), `dmesg` (healthd lines), `power_profile`
  (`battery.capacity`).
- Verify:
  - Learned capacity against design capacity. Say which design value you use:
    the health HAL's, the power profile's or the vendor's specification.
  - Cycle count against the phone's age. A count far too low for the age
    means the counter was reset or the battery was replaced. Then do not
    compare it with a "capacity after N cycles" specification.
  - Low-battery shutdowns: did the level fall fast just before them? A worn
    cell sags under load at low charge.
  - The runtime factor of a new battery is design capacity divided by learned
    capacity. It shortens or lengthens runtime; it does not change mAh/h.
- Traps: the batterystats learned capacity and the HAL full charge are one
  source, not two. Health "GOOD" says nothing about capacity. Charging current
  cannot be derived from the duration of one charge step.

## standby: standby and wakeups

Question: with the screen off on battery, how much of the time is the phone
awake, what wakes it, and how much does each wake cost?

- Results: `discharge_accounting`, `standby_wake`, `wake_periodicity`,
  `wakeup_reasons`, `wakelocks`, `alarms_jobs`, `kernel_suspend`,
  `suspend_stats`, `power_model`, `power_profile`, `previous_cycle`, and
  `drain_budget` when present.
- Raw sources: `batterystats_charged` ("All wakeup reasons", kernel wake
  locks, screen-off and deep-Doze discharge), `batterystats` (history),
  `batterystats_checkin`, `dmesg`, `suspend_control`, `power` (autosuspend
  flags, wake locks, drain stats), `deviceidle`, `alarm`, `jobscheduler`,
  `power_profile`.
- Verify:
  - Screen-off mAh/h, awake share and resumes per hour, all in
    `screen_off_on_battery`. `standby_wake.awake_share` also names the top
    wake reason, its share and the time awake per resume.
  - What the top wake interrupt belongs to. Its name is vendor-specific; see
    [vendor-notes.md](vendor-notes.md).
  - Aborted suspend attempts per real resume (`wakeup_reasons.suspend_aborts`,
    which also cites the since-boot suspend statistics and the kernel-log
    sample), and what precedes the aborts in the kernel log
    (`kernel_suspend.abort-precursor-N`). A precursor seen before nearly
    every abort and rarely before a successful suspend is measured
    co-occurrence; the causal chain stays inferred.
  - Whether Doze engaged: deep idle time and its share.
  - Long holds of `PowerManager.SuspendLockout` (`wakelocks` metric
    `suspend_lockout_screen_off_s`, or `previous_cycle.suspend_blocked` for
    the previous period). Android takes it while autosuspend is off, for
    example while a display or projection stays on.
  - Whether alarms and jobs explain a meaningful share of resumes. Usually
    they do not. `alarms_jobs` compares wakeup alarms with screen-off resumes.
  - The previous charge period (`previous_cycle`, window `previous_charge`)
    is a different window. Compare rates, not totals.
- Traps: triggers, multipliers and consequences are not additive. The kernel
  log covers minutes. Kernel and partial wakelock totals in batterystats
  count only screen-off time on battery. Partial wakelocks often cover a
  small part of the awake time; the rest is time spent in wakes and failed
  suspends. On phones with an always-on display, `screen_doze` counts as
  screen off.

## network: radios and network

Question: which network traffic or radio activity keeps the phone awake or
the modem busy?

- Results: `wifi_multicast`, `qcom_wow`, `wifi_roaming`, `cellular_radio`,
  `ims_handover`, `network_traffic`, `vpn`,
  `background_scanning_sensors_location`. Also `WORKDIR/sample-diff.json`
  when `sample_live.py` ran.
- Raw sources: `wifi` (multicast locks, firmware wake reasons),
  `network_stack` (packet filter and DTIM changes), `connectivity`,
  `netstats`, `telephony_registry`, `isub`, `vpn_management`,
  `app_services_platform`, `bluetooth_manager`, `location`, `sensorservice`,
  `arp`, `ipv6_neigh`, `dmesg` (wake-on-WLAN lines), `logcat_radio`.
- Verify:
  - Which sender dominates the Wi-Fi wakes, its role (gateway, LAN peer, VPN
    peer) and whether it arrives on a fixed period. Per-packet data covers
    only the kernel-log sample; say how many wakes it covers out of how many.
  - Multicast: who holds a Wi-Fi multicast lock, for what share of battery
    time, and what share of wakes was multicast or broadcast.
  - VPN: is it a full tunnel or a mesh with per-peer routes? Steady small
    packets to the VPN app point to peer keepalives. Kernel-sent bare TCP
    segments with no replies point to resets for a peer's connection
    attempts. Both need a host-side check; see
    [followups.md](followups.md).
  - Roaming while the phone lies still, and whether IMS (Wi-Fi calling)
    handovers follow the roams.
  - Cellular active time against the data it carried, and which network
    (internet or IMS) carried it.
  - BLE scans that run for hours with zero results.
- Traps: netstats buckets are 2 hours long and do not align with the battery
  window. The RSSI histogram may cover only screen-on time. MAC and IP
  addresses are personal data.

## cpu: CPU and system processes

Question: which processes use CPU on battery, and is that useful work or a
side effect of wake churn?

- Results: `system_process_cpu_churn`, `battery_proc_cpu`,
  `screen_off_cpu_by_uid`, `process_cpu_since_boot`, `cpuinfo_window`,
  `top_samples`, `am_cpu_intervals`, `thread_cpu`, `qcom_wlan_logging`,
  `logcat_volume`, `crash_anr_audit`.
- Raw sources: `ps`, `ps_threads`, `process_times`, `top`, `cpuinfo`,
  `batterystats_charged` (per-UID and per-process CPU), `logcat_events`
  (`am_cpu`), `dropbox`, `tombstones`, `anr_traces`.
- Verify:
  - Whether a system process's CPU tracks the suspend attempts (a
    consequence) or stands on its own (a cause). `system_process_cpu_churn`
    owns the busy-daemon findings; `process_cpu_since_boot` and
    `cpuinfo_window` report only daemons it did not.
  - Daemon restarts, vendor log daemons, crash loops, and apps killed for
    excessive CPU (`exit_info_audit.excessive_cpu_kills`, memory domain).
  - Which thread inside a busy process holds the CPU.
- Traps: since-boot CPU includes charging time. `top` and `cpuinfo` are short
  snapshots, and `top` costs CPU itself. Log volume rarely costs much energy.
  With less than 15 minutes on battery, `system_process_cpu_churn` skips
  itself and the per-hour CPU rates stay empty.

## memory: memory and slowness

Question: why does the phone feel slow? Candidates are memory kills followed
by cold starts, page-cache thrashing, frame jank, slow launches, thermal
limits, battery saver and settings.

- Results: `exit_info_audit`, `lmkd_kills`, `kills_vs_screen_events`,
  `process_churn`, `memory_snapshot`, `vmstat_reclaim_io`, `psi_pressure`,
  `zone_watermarks_offline`, `am_memory_config`, `frame_jank`,
  `app_launch_times`, `storage_io_per_uid`, `dexopt_status`, `thermal_status`,
  `battery_saver_state`, `settings_audit`.
- Raw sources: `exit_info`, `activity_lmk`, `logcat_events` (kill records,
  process starts), `meminfo`, `meminfo_detail`, `proc_meminfo`,
  `proc_vmstat`, `proc_zoneinfo`, `proc_pressure` or `psi_*`,
  `activity_settings`, `device_config_am`, `device_config`, `graphicsstats`,
  `start_info`, `diskstats`, `storaged`, `package_dexopt`, `thermalservice`,
  `cpufreq`, `settings`.
- Verify:
  - Kills per hour on battery and how many follow a screen-on. Keep the
    plug-in burst apart (`process_churn.plug_in_flood`).
  - Kills while plenty of memory is free (`lmkd_kills.kills_with_free_memory`).
    `zone_watermarks_offline` compares each zone with its own min watermark
    (`zones_below_min`) and repeats stock lmkd's check, the summed
    watermarks of all zones against free memory outside CMA
    (`lmkd_min_watermark_breached`). It is a snapshot taken after the kills.
  - Which apps are janky (`frame_jank.janky_apps` ranks them by janky
    frames), and whether the UI thread or the GPU is slow.
  - Flash reads far above what apps requested mean page-cache churn
    (`vmstat_reclaim_io.page_cache_thrashing`; `storage_io_per_uid` has the
    per-app reads). The figures are since boot and include the charger.
  - Thermal status and CPU caps at capture. They describe charging if the
    phone was plugged in.
  - Battery saver policy. Its effect on launch speed is inferred unless there
    is a saver-off comparison.
- Traps: exit-info is a ring buffer. A memory reading taken after a kill
  burst looks better than the moment of the kills. Links between refaults and
  jank, and between memory offlining and kills, are inferred unless the data
  show them in time order. Within the first hour after boot the since-boot
  counters are dominated by boot itself, so the analyzers give counts
  without rates.

## apps: installed apps

Question: which apps cost battery or memory in the background, and which are
installed but unused?

- Results: `uid_package_map`, `app_background_activity`, `third_party_apps`.
  Per-app rows also appear in `power_model`, `alarms_jobs`, `wifi_multicast`,
  `background_scanning_sensors_location`, `network_traffic`,
  `exit_info_audit` and `memory_snapshot`.
- Raw sources: `packages_uid`, `packages_3p`, `package`, `usagestats`,
  `usagestats_checkin`, `procstats`, `deviceidle_whitelist`,
  `activity_services`, `settings` (notification listeners, accessibility
  services, keyboards), `home_activity`, `batterystats_charged` (per-UID
  sections).
- Verify:
  - Apps exempt from battery optimisation, with foreground services, or
    always alive.
  - Dormant apps: usage stats count only screen time, so a watch companion, a
    push client or a sync tool used only in the background looks dormant.
  - Per-app mAh is modelled and a floor: kernel and radio wakes an app causes
    are not billed to it.
  - The same app can appear in several modules' findings. Merge them into one
    finding per app.
- Traps: never recommend uninstalling without asking the owner. App names
  reveal personal matters; keep them out of anything shared beyond the owner.

## known_issues: known issues for the build

Question: do this build, the vendor image, the kernel or the installed app
versions have known battery or performance problems, and do they apply here?

- Results: `build_identity`, `dexopt_status`, `settings_audit`,
  `am_memory_config`, `power_profile`, `crash_anr_audit`.
- Raw sources: `getprop` (fingerprint, vendor API level, boot reasons),
  `kernel_release`, `rollback`, `update_engine_logs`, `dropbox`, `package`
  (app versions).
- Work:
  - Search the vendor's release notes and community forum for the build ID
    and the symptoms, then the Android issue tracker, then the issue trackers
    of suspect apps. If you have no web access, give the owner the search
    terms.
  - For each known issue, check whether its signature is in this phone's data,
    such as the same wakelock name, setting or kernel message. Mark it
    "applies", "does not apply" or "cannot tell", with evidence.
  - Cite sources by URL. Quote forum posts as claims, not facts.
- Traps: forum workarounds often change `device_config` or settings.
  Recommend one only with its risk stated, never run it, and let the owner
  decide.
