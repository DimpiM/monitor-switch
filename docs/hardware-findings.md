# Hardware findings — Samsung Odyssey G9 (LC49G95T)

Everything documented here was measured on real hardware unless explicitly marked as
"derived" or "unverified". This file is the project's evidence base — it explains why
`monitor-switch` is built the way it is.

Deutsche Fassung: [hardware-findings.de.md](hardware-findings.de.md)

| | |
|---|---|
| Monitor | Samsung Odyssey G9, **LC49G95T**, 5120×1440 |
| Scaler | Novatek, capabilities identifier "FALCON", MCCS 2.0 |
| DP1 | Machine A (Windows) |
| DP2 | Machine B (Linux, KDE Plasma on Wayland, Intel i915) |
| HDMI | Control channel — Raspberry Pi Zero 2 W |

## The core finding

**DDC/CI does not work over DisplayPort on this monitor — only over HDMI.**

The DDC/CI slave at `0x37` does not answer at all on the DisplayPort inputs:

```
$ i2cdetect -y -r 14          # the monitor over DisplayPort
30: 30 -- -- -- -- -- -- --   # only EDID (0x50) and segment pointer (0x30)
50: 50 -- -- -- -- -- -- --   # no 0x37
```

```
$ ddcutil detect
Invalid display
   I2C bus:  /dev/i2c-14
   Model: LC49G95T
   This monitor does not support DDC/CI. (I2C slave address x37 is unresponsive.)
```

On the same machine, an Acer X34 P sitting next to it speaks DDC/CI over DisplayPort
just fine (VCP 2.2). So this is **not** a driver, GPU, cable or permission problem —
it is the monitor's firmware. This matches reports going back to 2020, across AMD and
Intel GPUs, independent of the DisplayPort version selected in the OSD and independent
of firmware updates (see sources).

Over HDMI the monitor answers cleanly — and crucially, **it answers even when HDMI is
not the input currently being displayed.** HDMI can therefore stay a pure control
channel while the picture runs over DisplayPort. That is the foundation of the whole
design.

## The value table for VCP `0x60` (input source)

The central trap: **write values and read values are different.**

| Input | write (`setvcp`) | read (`getvcp`) |
|---|---|---|
| **DP1** | **`0x0f`** | `0x03` |
| **DP2** | **`0x10`** | `0x04` |
| HDMI | `0x11` | `0x01` |

You write the **MCCS standard values** and get vendor-specific ones back. `ddcutil`
interprets the read value `0x04` per the standard and mislabels it as "DVI-2" — a
display artefact, not evidence of a DVI input.

The sweep that established the write values:

```
write 0x01 : x04 -> x01  HDMI
write 0x02 : x01 -> x01  (no effect)
write 0x04 : x01 -> x01  (no effect)
write 0x05 : x01 -> x01  (no effect)
write 0x06 : x01 -> x01  (no effect)
write 0x09 : x01 -> x01  (no effect)
write 0x0f : x01 -> x03  DP1     ✅
write 0x10 : x03 -> x04  DP2     ✅
write 0x11 : x04 -> x01  HDMI
```

The read values were verified independently by switching manually at the OSD while
logging `getvcp 60` once per second:

```
09:51:44  x04   ← DP2
09:52:21  x03   ← DP1   (switched manually at the OSD)
09:52:49  x04   ← DP2   (switched back)
```

**This finding is precisely why `monitor-switch` has monitor profiles.** Any design
that trusts the capabilities string would fail here.

## Pitfalls

**The capabilities string lies.** For `0x60` the monitor declares only `01: VGA-1` and
`03: DVI-1` — neither the write values that actually work (`0x0f`/`0x10`) nor the read
value that is actually active (`0x04`) appear in it. Do not trust that list.

**The default timing is too fast.** Without `--sleep-multiplier`, even reading the
capabilities aborts with "Maximum DDC retries exceeded". On the Raspberry Pi, 4 and 6
were not enough — only **8** carried. For normal operation (`getvcp`/`setvcp`), 4 is
sufficient. (`--maxtries` accepts at most 15.)

**Writes are sluggish.** On the Linux machine the first write attempt was regularly
swallowed; a verify-and-retry loop over `getvcp 60` was mandatory.

> On the Raspberry Pi this did **not happen once** in 6 switching operations — every
> write landed on the first try. The retry loop stays in the code anyway; it costs
> nothing when the write succeeds.

**Settings are kept per input.** Reading brightness while the monitor displayed HDMI
returned `11`; the same read while it displayed DisplayPort 2 returned `60`. The
monitor stores an independent set of values for each input, so **changing the input
invalidates every other cached value**. `monitorctl` reacts by scheduling a full
re-read whenever the input source changes.

Worth knowing if you write your own tooling: a cached brightness that looks wrong
after a switch is not a bug in the read, it is a different setting entirely.

**Never switch to an input without a signal.** This is the most dangerous point, and
the one that shaped the architecture. As soon as the monitor *displays* an input with
no signal, its DDC engine wedges: `0x37` still ACKs at the I²C level, but every DDC
transaction fails with "DDC communication failed". Reproduced twice.

`monitor-switch` addresses this with the `local_video` guard: before switching to its
own input, the service checks via `/sys/class/drm/` that its connector is `enabled`
and `dpms On`.

> **One counter-observation.** The monitor was switched to a DisplayPort input whose
> machine was powered off, left there for roughly two seconds, and switched back. DDC
> kept working throughout, and reads afterwards were clean. So the wedge is not
> instant, and brief exposure is survivable — at least on this monitor, in this one
> instance. The original wedges were both on the HDMI control channel and lasted
> longer.
>
> This was accidental rather than designed, and it has not been repeated: finding
> where the boundary lies means deliberately provoking a state that needs the OSD to
> escape. Treat the guard as the rule and this as a footnote, not a licence.

**Recovering from a wedge:** trigger a link reset on the HDMI connector, i.e. re-assert
HPD. Under KDE Wayland:

```bash
kscreen-doctor output.HDMI-A-1.enable    # put a signal on HDMI, DDC comes back
# ... now setvcp to a valid input ...
kscreen-doctor output.HDMI-A-1.disable
```

Alternatively switch manually at the OSD to an input that has a signal. `xrandr` does
not help under Wayland — it only reaches Xwayland and fails with `BadMatch`.

## Measurements on the Raspberry Pi Zero 2 W

Raspberry Pi OS Lite on Debian 13 (Trixie), kernel 6.18.39, `ddcutil` 2.2.0.

```
$ readlink -f /sys/class/drm/card0-HDMI-A-1/ddc
/sys/devices/platform/soc/3f805000.i2c/i2c-2

$ i2cdetect -y 2
30: 30 -- -- -- -- -- -- 37 -- -- 3a -- -- -- -- --     ← 0x37 answers
50: 50 -- -- -- 54 -- -- -- -- -- -- -- -- -- -- --

$ ddcutil detect
Display 1
   I2C bus:         /dev/i2c-2
   DRM connector:   card0-HDMI-A-1
   Model:           LC49G95T
   Product code:    28754  (0x7052)
   VCP version:     2.1
```

| Check | Result |
|---|---|
| DDC bus | `/dev/i2c-2` — the Pi-3-class assumption holds under kernel 6.18 with KMS |
| `0x37` | answers |
| `getvcp 60` | stable across 5 consecutive reads |
| without root | works, provided the user is in group `i2c` |
| switching test | 3 rounds DP2 ↔ DP1, **6 out of 6 on the first attempt** |

All measurements ran while the monitor was displaying DP2 — confirming on the Pi as
well that DDC over HDMI carries even when another source is active.

### Timings

These set the API's timeout budget:

| Operation | Duration |
|---|---|
| `getvcp 60 --sleep-multiplier 4` | ~860 ms |
| `setvcp 60 --sleep-multiplier 4` | ~785 ms |
| `ddcutil detect` (warm) | ~24 ms |

A complete switch including one verify read takes **~1.7 s**.

### Video signal

The DRM mode list initially topped out at 1024×768 — over HDMI the monitor evidently
serves only a minimal EDID while that input is inactive. Adding
`video=HDMI-A-1:1920x1080@60D` to `/boot/firmware/cmdline.txt` fixed that, and after
the reboot the framebuffer was 1920×1080 with `0x37` still answering.

**But the resolution is not deterministic, and that matters less than it looks.** A
later reboot came up at 1024×768 with the same kernel command line. The reason is in
the log:

```
[drm] forcing HDMI-A-1 connector on
[drm] User-defined mode not supported: "1920x1080": 60 148500 …
```

and `/sys/class/drm/card0-HDMI-A-1/edid` was **0 bytes** — that boot, the monitor
served no EDID at all over HDMI. Without one the driver will not accept the requested
mode and falls back to a default list topping out at 1024×768.

What *is* reliable is the part that matters: **`D` forces the connector on regardless
of EDID**, so a signal always exists. Both boots had `enabled`, `dpms On`, a live
framebuffer, and the service's `local_video` guard returning true. Only the pixel
count differed, and for a device whose display exists solely so the monitor never
shows a dead input, that is cosmetic.

Whether the monitor serves an EDID over HDMI appears to depend on state we do not
control — the same monitor did and did not, across two reboots, with the same input
selected. Anyone who needs a fixed resolution can supply a synthetic EDID with
`drm.edid_firmware=HDMI-A-1:edid/…bin`; note that current kernels no longer ship
built-in EDID blobs, so you have to provide the file yourself. Untested here.

## Capabilities string

Read in full with `--sleep-multiplier 8 --maxtries 15,15,15`:

**Continuous:** `0x10` brightness · `0x12` contrast · `0x62` volume ·
`0x16`/`0x18`/`0x1A` RGB gain · `0x6C`/`0x6E`/`0x70` RGB black level

**Selects:**

| VCP | Feature | Values |
|---|---|---|
| `0x14` | Colour preset | `01` sRGB · `04` 5000 K · `05` 6500 K · `06` 7500 K · `07` 8200 K · `08` 9300 K · `0a` 11500 K · `0b` User 1 |
| `0xDC` | Display mode | `00` Standard · `01` Productivity · `02` Mixed · `03` Movie · `04` User defined |
| `0xD6` | Power | `01` On · `02` Standby · `04` Off |
| `0xCC` | OSD language | German, English, French, … |
| `0x8D` | Mute | — |
| `0x60` | Input source | **`01: VGA-1`, `03: DVI-1` — both wrong, see above** |

**Read-only:** `0xC0` usage hours · `0xAC`/`0xAE` H/V frequency ·
`0xB6` display technology · `0xC8` controller type · `0xC9` firmware level

The monitor reports different EDIDs over HDMI and DisplayPort: product code `0x7052`
(HDMI) versus `0x7053` (DP), with an identical serial number.

## Alternatives that were rejected

| Option | Verdict |
|---|---|
| USB macropad on the Linux machine | rejected — that machine is not always on |
| Small service on the Linux machine, triggered remotely | rejected, same reason |
| ESP32 in the HDMI port ([`hardwareddc`](https://github.com/TeaRex-coder/hardwareddc)) | rejected — see below |
| Raspberry Pi 4 with touch display | rejected — 3–5 W idle |
| **Raspberry Pi Zero 2 W, headless** | **chosen** |

### Why not the ESP

1. **Sourcing.** HDMI breakout boards on a 2.54 mm grid are hard to get. On top of
   that the level question: the ESP32-C3 is not 5 V tolerant.
2. **The ESP produces no video signal.** The HDMI input would have stayed permanently
   dead — exactly the situation that wedges the DDC engine. The firmware would have
   had to dance around that failure mode forever.

### Why the Pi Zero 2 W

- **It outputs a real video signal.** The most dangerous failure class disappears
  structurally instead of through discipline in firmware.
- No soldering, no breakout, no level shifting — one cable.
- **0.4–0.7 W** idle, against 3–5 W for a Pi 4.
- The occupied HDMI port turns from a sacrifice into a gain: a genuine, usable third
  source.
- Brings Wi-Fi, an operating system, and therefore a web service plus Home Assistant
  integration at no extra cost.

The price: an OS that needs maintenance, an SD card that ages, and boot time instead
of instant readiness.

## Appendix: DDC/CI at the protocol level

Not needed for the chosen solution — `ddcutil` handles this. Kept in case a
microcontroller is ever used after all. **Derived from the specification, not verified
on the device.**

HDMI type A, the relevant pins:

| Pin | Signal |
|---|---|
| 15 | SCL |
| 16 | SDA |
| 17 | DDC ground |
| 18 | +5 V — supplied by the source, powers the sink's EDID logic |
| 19 | HPD — driven by the monitor, not needed for DDC alone |

I²C address `0x37` (8-bit write address `0x6E`), 100 kHz maximum, at least 40 ms
between messages. Payload for "Set VCP Feature":

```
0x51  0x84  0x03  0x60  <value-high>  <value-low>  <checksum>
 │     │     │     │
 │     │     │     └── VCP code 0x60 (input source)
 │     │     └──────── opcode "Set VCP Feature"
 │     └────────────── length: 0x80 | 4 data bytes
 └──────────────────── host source address
```

Checksum = XOR over **all** bytes including the destination address `0x6E`:

| Target | Frame | Checksum |
|---|---|---|
| DP1 (`0x0f`) | `6E 51 84 03 60 00 0F` | `0xD7` |
| DP2 (`0x10`) | `6E 51 84 03 60 00 10` | `0xC8` |

## Sources

- [ddcutil #388 — Samsung Odyssey, switching between DP1 and DP2](https://github.com/rockowitz/ddcutil/issues/388)
- [ddcutil #398 — setvcp fails intermittently](https://github.com/rockowitz/ddcutil/issues/398)
- [MonitorControl #1580 — Samsung G9, DDC does not work over DP](https://github.com/MonitorControl/MonitorControl/discussions/1580)
- [BetterDisplay #2498 — Unable to Change Input on Samsung Odyssey G9](https://github.com/waydabber/BetterDisplay/discussions/2498)
- [ddcutil — Raspberry Pi documentation](https://www.ddcutil.com/raspberry/)
- [ddcutil #472 — Pi 4 "Display not found", works on Pi 3](https://github.com/rockowitz/ddcutil/issues/472)
- [TeaRex-coder/hardwareddc — ESP32 board for DDC over HDMI](https://github.com/TeaRex-coder/hardwareddc)
- [ddcutil monitor notes](https://www.ddcutil.com/archived/monitor_notes/)
