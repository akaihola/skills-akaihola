# Vendor notes

These are signs seen on real phones, most of them on Qualcomm hardware. Treat
each one as something to check in this phone's data, not as a fact about all
phones. The vendor-specific analyzers (`qcom_wow`, `qcom_charging`,
`qcom_wlan_logging`) skip themselves when their log lines are missing.

## Wake interrupt names

The battery history and "All wakeup reasons" in batterystats name each wake
by interrupt number and name, such as `41 WLAN_CE_2`. The names come from the
kernel and depend on the chip. The analyzers guess the device from parts of
the name:

| Part of the name | Usually |
|---|---|
| `wlan`, `wifi`, `_ce_`, `cnss`, `icnss` | Wi-Fi: the chip received a packet |
| `ipcc`, `glink`, `smp2p`, `modem`, `rmnet`, `ipa` | the modem or its data path |
| `alarm`, `rtc` | a timer or alarm |
| `uart`, `bt`, `bluetooth` | Bluetooth |
| `pon`, `kpdpwr`, `gpio_keys` | a key press |
| `typec`, `usb`, `pd_`, `charger` | the USB or charger port |
| `sensor`, `ssc`, `slpi` | a sensor hub |

To check a name, read `cat /proc/interrupts` with `adb_ro.py`. It lists each
interrupt number with its controller and name. Entries that start with
`Abort:` are failed suspend attempts, not wakes.

On Qualcomm Wi-Fi, `WLAN_CE_n` is a copy-engine interrupt: the Wi-Fi firmware
hands a received packet to the main processor. Many such wakes mean packets
the firmware did not filter out. The next section shows how to find their
sender.

## Wake-on-WLAN lines in the kernel log

The Qualcomm Wi-Fi host driver logs each wake packet, when its logging is on:

- `WLAN triggered wakeup: REASON (CODE)`;
- `wma_wow_parse_data_pkt: ... Src_mac: ..., Dst_mac: ...`;
- `WOW Wakeup: ... rcvd` and `Pkt_len: N, src_port: N, dst_port: N`.

`qcom_wow` decodes these into senders, protocols and periods. The kernel log
covers only minutes, so the result is a sample of the wakes. `dumpsys wifi`
has firmware counters since the driver started, in a line such as
`Wlan Wake Reasons: totalRxDataWake N rxUnicast N rxMulticast N rxBroadcast N`.

Other Wi-Fi drivers log wake packets differently or not at all. Then only the
counters in `dumpsys wifi`, where present, and the periodicity of resumes in
`wake_periodicity` remain.

## Wi-Fi multicast locks, packet filter and DTIM

This is Android behaviour, not vendor-specific. While an app holds a Wi-Fi
multicast lock, Android lets multicast through the packet filter (APF) even
in Doze, and on recent versions lowers the DTIM multiplier, so the chip wakes
for multicast traffic more often. The network stack's IpClient log
(`dumpsys network_stack`) records the filter installs with their multicast
and Doze flags and the DTIM changes. Check `wifi_multicast` for the lock
holders and the share of multicast wakes.

## cnss_diag, the Qualcomm Wi-Fi logger

`cnss_diag` is a vendor daemon that streams Wi-Fi firmware logs. On some
builds it runs all the time and uses a few percent of one core, more while
Wi-Fi is busy. Its CPU on battery is in `system_process_cpu_churn` (the
finding `system_process_cpu_churn.cnss-diag`). `qcom_wlan_logging` says
whether it runs and gives its CPU since boot. Check the daemon's arguments
in `ps`.
Also check that Wi-Fi verbose logging in Developer options is off, so the
logging is not the owner's own setting. The owner cannot stop the daemon
without root; a lasting cost of more than about 1 % of a core on battery is
worth a report to the vendor.

## Storage resets that abort suspend

Signature in the kernel log: after a resume, the storage driver prints
`sd N:N:N:N: Power-on or device reset occurred`, and the next suspend attempt
aborts with `Abort: Pending Wakeup Sources: NETLINK ...` or
`Last active Wakeup Source: eventpoll`. The likely chain: UFS storage reports a unit
attention after each resume, the kernel sends a uevent over netlink, a
listener holds a wakeup source while it handles the event, and the suspend
attempt fails. Android then backs off and retries. `ueventd` and the suspend
service burn CPU on every wake.

Where to look:

- `kernel_suspend`: the `messages_before_aborts` and `abort_cooccurrence`
  tables and the `kernel_suspend.abort-precursor-N` findings;
- `wakeup_reasons.suspend_aborts`, the finding for the abort counts. It cites
  the since-boot share of failed suspends (`suspend_stats` metric
  `fail_share_pct`) and the aborts per resume in the kernel-log sample
  (`kernel_suspend` metric `aborts_per_deep_resume`), each in its own window;
- `system_process_cpu_churn` for `ueventd` and the suspend service.

The co-occurrence is measured; the chain is inferred. The owner cannot fix it.
Fewer wakes shrink it in proportion, and it belongs in a vendor bug report
with the counts per wake. Other precursors seen on some kernels are CPU
hotplug messages (`CPUn is up`) and driver wakelocks such as
`qcom_rx_wakelock`.

## Power profiles that price sleep at 0 mA

`dumpsys batterystats --power-profile` prints the currents the power model
uses. It exists only live, never in a bugreport. Check:

- `cpu.suspend` and `cpu.idle`. If they are 0 or 0.1 mA, the model charges
  nearly nothing for time spent awake or asleep in standby. AOSP's
  documentation gives example values of a few mA.
- `wifi.on`, `modem.controller.sleep` and the radio idle currents.
- The CPU tables. A cluster with fewer power entries than the kernel has
  frequencies prices the extra steps at 0 mA (`power_profile.cpu_steps_unpriced`).

With such a profile a large share of the drain falls in no component
(`power_model.unmodelled_drain`), and Settings > Battery usage blames the
screen and the apps in the foreground. Some phones have on-device power
meters. Their per-rail energy appears in the power statistics dump and is
measured data. `power_profile.no_energy_metering` says whether this phone has
none.

## Fuel gauge and charger logs

- On phones with the Qualcomm QG gauge, the batterystats charge counter is
  the state of charge times the learned capacity, in whole percent. Every mAh
  figure is then plus or minus one step; see `gauge_quantization`. `QG-K:`
  kernel lines carry the gauge's battery resistance estimates.
- Qualcomm charger lines (`[SMBLIB]`, `QCOM-STEPCHG`) show the negotiated
  source, current limits and temperature (JEITA) handling.
  `start_usb_peripheral` at plug-in means the phone charges from a
  computer's USB port, so that charge says nothing about the owner's charger.
  `qcom_charging` reads these lines.

## Memory taken offline and kills with free memory

Some Qualcomm kernels take memory blocks offline while the screen is off to
save refresh power. The kernel log shows `mem-offline: Offlined memory block`
and `Onlined memory block` lines, and `/proc/zoneinfo` shows a Movable zone of
a few GiB.

lmkd can kill with the reason "min watermark is breached" while the free
memory in its own kill record is in the gigabytes. Stock lmkd adds up the min
watermark and the largest lowmem reserve of every zone and compares the sum
with free memory outside CMA. A vendor lmkd may check differently. The kernel
itself compares each zone with its own min watermark; the larger lowmem
reserve only refuses allocations that fall back from a higher zone.

Check `lmkd_kills.kills_with_free_memory` and `zone_watermarks_offline`:
zones below their own minimum (`zones_below_min`), stock lmkd's summed check
(`lmkd_min_watermark_breached`), the Movable share and the hotplug messages.
The zone figures are a snapshot taken at capture, after the kills. Why lmkd
saw a breach is not shown by the data, and offlining as the cause of the
kills stays inferred unless the timeline shows kills right after it. The kernel log rarely covers screen-off time; a bugreport taken
right after the screen was off for over 5 minutes has a better chance to
contain the messages.

Some vendor builds also ship with the cached-app freezer or app compaction
off. `am_memory_config` reports both. Forum workarounds turn them on with
`device_config put`. That is the owner's decision, never yours, and it can
be reset by an update.

## Other signs worth a look

- **Modem data-path wakelocks.** Kernel wakelocks with `RMNET` or `DFC` in
  the name come up often in forum reports about standby drain on Qualcomm
  phones. Look for them among the kernel wakelocks; their absence rules this
  cause out.
- **Firmware roaming.** Qualcomm drivers log `[ROAM_TRIGGER]` and
  `[ROAM_RESULT]` lines with the reason and the signal strength;
  `wifi_roaming` counts them.
- **Old vendor image.** A vendor API level far below the Android version
  means the OS was upgraded on an old vendor base
  (`build_identity.old_vendor_image`). Known issues of the vendor's release
  are then more likely; search for them.
- **Battery current limit sensors.** Thermal sensors whose names contain
  `BCL` measure battery current limits, not temperatures.
- **Receive wakelocks.** Wi-Fi driver wakelocks such as `qcom_rx_wakelock`
  keep the system awake for a moment after each received packet. Many
  activations follow from many packets; they are a consequence, not a cause.
