# Project status

Last updated **2026-08-08**.

This file is honest about what has been verified on real hardware and what has
not. Everything below marked ✅ was exercised against a Samsung Odyssey G9 on a
Raspberry Pi Zero 2 W.

## Done

| | Verified by |
|---|---|
| ✅ DDC/CI works on the Pi Zero 2 W | `0x37` answers on `/dev/i2c-2`, `ddcutil detect` reports the monitor at VCP 2.1 |
| ✅ Switching is reliable | 20 of 20 switches landed on the first attempt, ~2.0 s each |
| ✅ DDC survives while the Pi is the displayed input | Read brightness and usage hours with the monitor showing HDMI |
| ✅ Forced video mode | 1920×1080 instead of a 1024×768 fallback; `0x37` still answers afterwards |
| ✅ HTTP API and SSE | Switching, concurrent requests, live state push |
| ✅ Web UI | Driven in a browser against the running service, desktop and phone widths |
| ✅ Ansible role | First run installs; second run reports `changed=0` |
| ✅ Unprivileged operation | Service runs as its own user, in group `i2c`, no root |

## Not verified yet

| | Why it matters |
|---|---|
| ⬜ **MQTT bridge** | Written and documented, but never connected to a broker. Credentials are an open question — see [home-assistant.md](home-assistant.md). |
| ⬜ **Any monitor other than the reference one** | The `generic` profile and auto-detection are exercised only by unit tests against recorded output. |
| ⬜ **The `probe` calibration command** | Implemented with a commit-or-revert timer, but never run against a monitor that actually needs it. |
| ⬜ **Behaviour while the monitor sleeps** | Unknown whether DDC answers at all in standby. This is why `0xD6` (power) ships read-only. |
| ⬜ **Long-run endurance** | The longest continuous run so far is 20 switches. |

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

**A toggle costs one extra read.** `POST /api/toggle` reads the current input
before deciding where to go (~2.7 s). `POST /api/input/<target>` skips that
(~2.0 s), so bind hotkeys to explicit targets where you know the destination.

## Next

- Connect the MQTT bridge to a broker and verify the entities in Home Assistant
- CI that rebuilds the frontend and fails if the committed build has drifted
- `log2ram`, since this is a permanently-powered machine on an SD card

`clients/monitor-switch.sh` wraps the API for scripts and terminals. Binding it
to a hotkey is a one-liner in any desktop environment, but no ready-made hotkey
integration ships here — the web UI covers the same ground without one.

## Contributing what is missing

The most useful thing anyone can add is **a profile for a monitor that is not
this one**. See [profiles.md](profiles.md). Reports that auto-detection worked
without a profile are just as valuable — that is the path with the least
evidence behind it.
