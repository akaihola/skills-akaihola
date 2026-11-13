# Stutter in real-time voice apps

Use this when audio in a voice call or a live voice assistant stutters,
rather than the battery or the interface. The notes below were verified on
2026-11-12 on a Fairphone 4 running Android 15 (build FP4.QREL.15.20.0),
during a ChatGPT voice chat through Bluetooth earbuds. Other phones may
differ.

## Collect within minutes

The phone's default log buffers are 256 KiB each. On that phone the `main`
log then held only 2 to 3 minutes during busy periods, `system` about 25
minutes and `events` about 30 minutes. Collect as soon as possible after the
stutter, and ask the owner for the times it started and stopped.

Larger buffers help the next occurrence. Recommend Settings > System >
Developer options > Logger buffer sizes > 16M, which survives a reboot.
`adb logcat -b all -G 16M` worked from the adb shell but resets at reboot,
and `setprop persist.logd.size` was refused for the shell user. Both change
the phone, so run them only when the owner asks you to.

## Where the timeline is

The app's own logs are usually gone, but these dumps keep a timeline:

- `dumpsys audio`
  - "recording activity" shows when the app's microphone started and
    stopped, which marks each voice session.
  - "phone state" shows `setMode(MODE_IN_COMMUNICATION)` by the app.
  - "playback activity" keeps only about 100 entries.
  - "Communication route clients" shows where call audio goes now.
- `dumpsys bluetooth_manager`, section HeadsetService, StateMachineLog
  (about 20 records per headset)
  - It shows when call audio to the headset (SCO) went on and off.
  - `DEVICE_STATE_CHANGED` records carry the signal bars that were sent to
    the headset. This is a cheap history of mobile signal strength.
  - `+IPHONEACCEV=1,1,N` is the headset's battery level, N from 0 to 9.
- `dumpsys telephony.registry` keeps the last 199 service-state changes
  with `mChannelNumber` (the LTE channel) and `mCellBandwidths`. It has no
  cell IDs, so moving between cells on the same channel does not show.
  Channel 2147483647 means the phone briefly had no cell identity.
- `dumpsys wifi` has connection records and a score row every 3 seconds
  (signal, frequency, transmit retries). The rows start only when the phone
  joins a network; the default network is in `dumpsys connectivity`.
- The `events` log entry `stream_devices_changed: [stream, old, new]` uses
  device bits: 0x1 earpiece, 0x2 speaker, 0x10 Bluetooth call audio (SCO),
  0x80 Bluetooth media audio (A2DP).
- `dumpsys thermalservice`: "Thermal Status: 3" is severe. A cooling device
  with a non-zero value is actively limiting, for example, the CPU speed.

## ChatGPT for Android

- Voice mode runs as `com.openai.voice.webrtc.VoiceModeForegroundService`,
  which uses WebRTC.
- The app writes WebRTC's Java-side messages under the log tag `Logging`.
  They include `NetworkMonitorAutoDetect` network changes and `VolumeLogger`.
  No jitter-buffer or connection-path messages were seen.
- During voice mode, `system_server` logs "PackageConfigPersister:
  App-specific configuration not found for packageName: com.openai.chatgpt"
  200 to 340 times a minute. This is noise, not the cause of a stutter.
