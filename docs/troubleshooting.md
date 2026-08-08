# Troubleshooting

## Nothing works: is DDC/CI there at all?

```bash
BUS=$(basename "$(readlink -f /sys/class/drm/card*-HDMI-A-1/ddc)" | sed 's/i2c-//')
echo "bus $BUS"
sudo i2cdetect -y "$BUS" | grep '^30:'
```

- **`37` appears** → the monitor speaks DDC/CI. Good.
- **Only `30` and `50`** → an EDID is there but no DDC/CI on this connector. Try
  a different input on the monitor, or a different cable. Many monitors answer
  on HDMI but not on DisplayPort; this project exists because of one of them.
- **No `/dev/i2c-*` at all** → `i2c_dev` is not loaded:
  ```bash
  echo i2c_dev | sudo tee /etc/modules-load.d/i2c-dev.conf
  sudo modprobe i2c_dev
  ```
- **`readlink` finds nothing** → the connector name differs. `ls /sys/class/drm/`
  and set `monitorctl_connector` accordingly.

## "Maximum DDC retries exceeded"

The default timing is too fast for many monitors. Raise it in the profile:

```yaml
ddc:
  sleep_multiplier: 4
  capabilities_sleep_multiplier: 8
```

Reading the capabilities string is far more fragile than reading a single
feature. On the reference monitor, `4` and `6` both aborted and only `8`
carried, while normal reads were fine at `4`.

If capabilities never succeed, the service can still run entirely from a
profile — that is the fallback, and it will log that it took it.

## The service starts but sees very few features

Check the log for the capabilities read:

```bash
journalctl -u monitorctl | grep -i capabilit
```

If it failed, the feature list is whatever the profile alone supplies. One cause
worth knowing: `ddcutil` keeps a timing-adaptation cache under
`$XDG_CACHE_HOME`, and if that directory is not writable it loses the data it
uses to adapt — which is enough to make a marginal capabilities read fail. The
shipped systemd unit handles this with `CacheDirectory=`; a hand-rolled unit
with `ProtectSystem=strict` and no writable cache will hit it.

## The monitor stopped answering entirely

This is the wedge. It happens when the monitor *displays* an input with no
signal: `0x37` still acknowledges at the I²C level, but every DDC transaction
fails with "DDC communication failed".

Recover by giving it something to display:

- Switch to a live input at the monitor's own OSD, **or**
- Re-assert HPD on the connector to force a link reset

The `local_video` guard exists to make this unreachable through the API. If you
hit it anyway, it was through the OSD, another tool, or a profile whose guard is
missing.

## A switch reports success but the screen is black

The target machine is off or asleep. Nothing can detect this in advance — the
monitor accepted the command and switched. Switch back through the API or the
OSD.

## Values look wrong right after switching inputs

They are probably not wrong. Monitors commonly keep **separate settings per
input** — measured on the reference monitor: brightness reads `11` on HDMI and
`60` on DisplayPort 2. The service re-reads everything after an input change,
but a full sweep takes around 20 seconds on a Pi Zero, so there is a window
where the other values still describe the previous input.

## Switching is slower than expected

A verified switch is roughly two seconds: write, settle, read back. Beyond that:

- `POST /api/toggle` costs about 0.7 s more than `POST /api/input/<target>`,
  because it reads the current input before deciding. Bind hotkeys to explicit
  targets where you know the destination.
- A request that arrives mid-poll waits for the in-flight `ddcutil` call. The
  poller steps aside as soon as a request arrives, so this costs one call, not a
  whole sweep.

## The web UI shows "offline" or "reconnecting"

The SSE stream dropped. It reconnects on its own with a backoff up to 15 s. If
it stays down:

```bash
systemctl status monitorctl
journalctl -u monitorctl -n 50
curl http://127.0.0.1:8765/healthz
```

## Home Assistant entities never appear

See [home-assistant.md](home-assistant.md#if-nothing-appears).

## Starting over

```bash
sudo systemctl stop monitorctl
sudo journalctl --vacuum-time=1s -u monitorctl
sudo systemctl start monitorctl
journalctl -u monitorctl -f
```

Raising the log level shows every `ddcutil` invocation:

```yaml
monitorctl_log_level: DEBUG
```
