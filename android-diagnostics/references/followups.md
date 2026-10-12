# Follow-ups

The first analysis often points at a cause without naming it. For example, a
LAN peer wakes the phone every 3 seconds, but the phone's data cannot say
which program sends the packets. This file lists the next checks, on the phone
and on the owner's other machines.

Ask the owner before running anything on another machine. Some commands need
root, and packet captures contain other people's traffic. Keep captures on
that machine, quote only counts and intervals, and delete the captures
afterwards.

## On the phone

Use `adb_ro.py`; it refuses anything that is not a plain read. Save outputs
into the workdir with `--save NEW_KEY --workdir WORKDIR` and grep
`WORKDIR/live/NEW_KEY.txt` on the computer, because the phone command cannot
contain pipes. `--save` refuses a key that already exists, so pick a new one
per read, such as `tcp_1` and `tcp_2`.

| Question | Command after `--` |
|---|---|
| Which sockets exist, with their owning UID | `cat /proc/net/tcp`, then `/proc/net/tcp6`, `/proc/net/udp`, `/proc/net/udp6` |
| Connection list in readable form | `netstat -tun` |
| Does the VPN route everything or only its peers | `ip route show table all` |
| Kernel TCP and UDP counters, read twice some minutes apart | `cat /proc/net/snmp` (or run `sample_live.py`) |
| What an app is allowed to do and did lately | `cmd appops get PACKAGE` |
| App version and last update | `dumpsys package PACKAGE` |
| Widgets and their update periods | `dumpsys appwidget` |
| Memory of one process | `dumpsys meminfo PID` |
| CPU per thread of one process | `ps -T -p PID -o TID,TIME,CMD` |
| Is autosuspend on, is a display still on | `dumpsys power`, `dumpsys display` |
| Suspend counters | `dumpsys suspend_control_internal` (often refused from the shell user; a bugreport has it) |
| One setting | `settings get global NAME` |
| Does battery saver cap the CPU | `cat /sys/devices/system/cpu/cpu7/cpufreq/scaling_max_freq`, read unplugged with saver on |

Anything measured live must be measured in the condition you care about:
unplugged, screen off, a few minutes into Doze, connected by wireless
debugging.

## On other machines: who wakes the phone

Do this when the analysis shows packets from the LAN or a VPN driving the
wakes. Typical findings are `qcom_wow.dominant-sender` with role `lan_peer`
or `gateway`, `wake_periodicity.periodic_sender`, `vpn.mesh_vpn_keepalives`,
`network_traffic.steady_background_packets` and `wifi_multicast.lock_held`.
A `sample-diff.json` with a UID that receives a packet on a fixed period, or
with a steady rate of TCP resets sent (`OutRsts`), points the same way.

### 1. Map the sender to a machine

- `results.qcom_wow.tables.wake_senders` holds each sender's MAC and IP
  addresses. The bugreport's ARP and IPv6 neighbour caches map MACs to
  addresses. These are personal data; keep them local.
- On a computer in the same LAN: `ip neigh show` and look for the MAC,
  `getent hosts IP`, or `avahi-resolve -a IP` for an mDNS name. The router's
  list of connected clients also maps MACs to device names.
- For an address inside a mesh VPN, the VPN's own status command lists the
  peers and which of them has an active session with the phone. For
  Tailscale that is `tailscale status`, and `tailscale whois IP` names a
  peer.

### 2. See what the peer sends

On the suspected peer, with the phone's LAN or VPN address as PHONE_IP:

```bash
sudo ss -tunp dst PHONE_IP           # which process holds a connection to the phone
ss -tnoi dst PHONE_IP                # keepalive timers, last send and receive; run a few times
sudo tcpdump -ni IFACE host PHONE_IP -c 200   # what is sent, and how often
```

IFACE is the LAN interface, or the VPN interface for VPN traffic. Compute the
gaps between packets and compare them with the period that
`wake_periodicity` or the `wake_senders` table reports.

### 3. Read the pattern

- **Small packets on a fixed period** are keepalives or heartbeats. Find the
  service and lengthen its interval, or stop it while the phone is idle.
  Mesh VPNs are a frequent source. Tailscale, for example, pings a peer every
  few seconds while their session is active, and a session stays active for
  a while after the last real packet. Any app keepalive between the two
  machines that is shorter than that keeps the pings going all night.
- **Repeated connection attempts answered by resets.** The phone's kernel
  sends bare 40-byte TCP segments, counted in the `kernel_vpn_bare_tx_segments`
  metric of `vpn` and `network_traffic`, and `OutRsts` in a live sample climbs
  steadily. A peer is
  dialing a port on the phone where nothing listens. Each attempt wakes the
  phone, the kernel refuses it, and the peer tries again. A typical case is a
  file-sync or companion service on a desktop that keeps redialing the phone
  after the phone's app was stopped or restricted. The fix is on the peer:
  pause or remove the phone there, or lengthen its retry interval.
- **Multicast and broadcast** (mDNS, SSDP, NetBIOS) reach the phone in Doze
  when an app holds a Wi-Fi multicast lock. The lock holder is in
  `wifi_multicast`. Restricting that app releases the lock. On the network,
  multicast filtering in the access points helps everyone's phones.
- **HTTPS from the gateway** is internet traffic: push notifications and app
  sync. Per-UID packet counts in `network_traffic` show which app receives
  it.

### 4. Confirm the change

- On the peer: no packets to the phone for several minutes while the phone
  idles, and the VPN status no longer shows the phone as active.
- On the phone: run `sample_live.py --workdir WORKDIR/sample-after`, a new
  directory next to the `WORKDIR/sample-before` run, and check that the
  packet rate for that UID is near zero. Then run an A/B window as in
  [experiments.md](experiments.md).

## Access points and router

For `wifi_roaming.stationary_roaming`, a phone lying still that roams many
times an hour between access points:

- Check minimum RSSI, BSS transition (802.11v), band steering and fast
  roaming (802.11r) settings, and lower the transmit power of access points
  whose coverage overlaps where the phone rests. As a rule of thumb, a phone
  on a nightstand should roam fewer than about 10 times a night.
- Check the DTIM interval and multicast-to-unicast or multicast filtering
  options.

These are changes to the owner's network. Describe them; the owner or their
network administrator makes them.

## Suspend blocked after car projection or casting

When `PowerManager.SuspendLockout` was held for hours, autosuspend was off,
for example while a projection display stayed on after a drive. After the
next such session, with the phone locked and unplugged, read twice 5 minutes
apart:

- `dumpsys suspend_control_internal`: does the success count grow? If the
  shell user is refused, take a bugreport instead.
- `dumpsys display`: is a virtual or projection display still present?
- `dumpsys power`: the wakefulness state and the autosuspend flags.

If the phone does not suspend, the owner can force-stop the projection app
and the case is worth a bug report to the app or phone vendor.

## Researching known issues

- Search the vendor's release notes and community forum for the build ID from
  `build_identity` and for the symptom, then the Android issue tracker and the
  issue trackers of suspect apps.
- Look up unfamiliar wakeup source, interrupt or service names in the AOSP
  sources (cs.android.com) and in the device's kernel sources, where the
  vendor publishes them.
- Quote what you find as claims with links. A forum consensus is not evidence
  about this phone; the matching signature in this phone's data is.

## Reporting to the vendor

Problems the owner cannot fix, such as kernel suspend aborts or a power
profile that prices sleep at 0 mA, belong in a bug report to the vendor.
Give the owner the build fingerprint, the signature (the kernel message and
its counts per wake), the window, and how to reproduce it. Attaching the
bugreport is the owner's decision: it contains personal data.
