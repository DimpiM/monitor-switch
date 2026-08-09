# Project status

Last updated **2026-08-09**.

This file is honest about what has been verified on real hardware and what has
not. Everything below marked ✅ was exercised against a Samsung Odyssey G9 on a
Raspberry Pi Zero 2 W.

## Done

| | Verified by |
|---|---|
| ✅ DDC/CI works on the Pi Zero 2 W | `0x37` answers on `/dev/i2c-2`, `ddcutil detect` reports the monitor at VCP 2.1 |
| ✅ Switching is reliable | 20 of 20 switches landed on the first attempt, ~2.0 s each |
| ✅ DDC survives while the Pi is the displayed input | Read brightness and usage hours with the monitor showing HDMI |
| ✅ Forced video output | `D` forces the connector on across reboots — `enabled`, `dpms On`, live framebuffer, guard reporting true every time. The *resolution* is not deterministic; see Known limitations. |
| ✅ HTTP API and SSE | Switching, concurrent requests, live state push |
| ✅ Web UI | Driven in a browser against the running service, desktop and phone widths |
| ✅ Ansible role | First run installs; second run reports `changed=0` |
| ✅ Unprivileged operation | Service runs as its own user, in group `i2c`, no root |
| ✅ MQTT and Home Assistant | 21 entities announced and registered; a command sent over MQTT reached the monitor and came back; stopping the service flipped availability to `offline` |

## Not verified yet

| | Why it matters |
|---|---|
| ⬜ **Any monitor other than the reference one** | The `generic` profile and auto-detection are exercised only by unit tests against recorded output. |
| ⬜ **The `probe` calibration command** | Implemented with a commit-or-revert timer, but never run against a monitor that actually needs it. |
| ⬜ **Behaviour while the monitor sleeps** | Unknown whether DDC answers at all in standby. This is why `0xD6` (power) ships read-only. |
| ⬜ **Long-run endurance** | The longest continuous run so far is 20 switches. |
| ⬜ **Survives a Pi reboot** | ✅ actually — service, MQTT and the web UI all came back unattended after a reboot. Listed here only because it was verified once, not repeatedly. |

## Known limitations

**Settings are per input.** Monitors commonly keep an independent set of values
for each input — measured: brightness reads `11` on HDMI and `60` on
DisplayPort 2 on the same monitor. Changing the input therefore invalidates
every other cached value, and the service schedules a full re-read when it
happens. A full sweep takes around 20 seconds on a Pi Zero, so the other values
lag briefly after a switch.

**Switching to a machine that is off** shows a black screen. The service cannot
detect this in advance. The `local_video` guard only protects its own input.
Recover through the OSD or another API call.

**No authentication.** The service is meant for a trusted LAN. It binds to a
configurable address rather than `0.0.0.0` by default.

**The forced video resolution is a request, not a promise.** `video=…@60D` reliably
forces the connector *on*, which is what the design depends on. The resolution
depends on the monitor serving an EDID for that input, and the reference monitor
did so on one boot and not on the next, unprompted. When it does not, the mode
falls back to around 1024×768 — a signal still exists, so nothing breaks. Details
in [hardware-findings.md](hardware-findings.md).

**A toggle costs one extra read.** `POST /api/toggle` reads the current input
before deciding where to go (~2.7 s). `POST /api/input/<target>` skips that
(~2.0 s), so bind hotkeys to explicit targets where you know the destination.

## Next

Nothing is outstanding on the reference hardware. What would move the project
forward now is coverage of monitors it has never seen — see
[profiles.md](profiles.md).

### Measured and dropped: `log2ram`

An always-on machine on an SD card invites moving `/var/log` to RAM. Measured on
the running system instead of assumed:

| | |
|---|---|
| Journal growth | **0 bytes** over 60 s, 8.1 MB total |
| Whole-disk writes | ~264 KiB over 120 s ≈ **185 MiB/day** |
| `noatime` | already set on `/` |

That is roughly 67 GiB a year, which no reasonable card minds. And `log2ram`
only redirects `/var/log` — precisely the part already writing nothing, because
the service asks `ddcutil` not to log to syslog (`--syslog NEVER`). Adding a
third-party apt repository to fix a non-problem is not worth it.

Worth revisiting if the log ever gets chatty again, or if you add something that
writes continuously.

`clients/monitor-switch.sh` wraps the API for scripts and terminals. Binding it
to a hotkey is a one-liner in any desktop environment, but no ready-made hotkey
integration ships here — the web UI covers the same ground without one.

## Contributing what is missing

The most useful thing anyone can add is **a profile for a monitor that is not
this one**. See [profiles.md](profiles.md). Reports that auto-detection worked
without a profile are just as valuable — that is the path with the least
evidence behind it.
