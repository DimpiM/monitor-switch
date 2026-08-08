# Monitor profiles

A profile describes what a monitor really does, as opposed to what it claims.

Most of the time you do not need one. `monitorctl` reads the monitor's
capabilities string and builds its feature list from that, which is enough for
well-behaved hardware.

You need a profile when the capabilities string is wrong. That is not rare. The
monitor this project was built around declares input source values `01: VGA-1`
and `03: DVI-1` — neither exists — while hiding the values that actually work.
It also returns different values than it accepts.

## How the layers stack

Three sources, each overriding the previous:

1. **Auto-detection** — parsed from `ddcutil capabilities`
2. **Monitor profile** — a YAML file matched against the EDID
3. **Local overrides** — `monitorctl_feature_overrides` in your Ansible vars

A profile can add features the monitor never declared, correct the ones it did,
and remove ones you do not want.

## Anatomy

```yaml
name: Samsung Odyssey G9 (LC49G95T)

# Matched against the EDID. Every key listed must agree.
# An empty match block never matches automatically.
match:
  mfg: SAM
  model: LC49G95T

ddc:
  sleep_multiplier: 4                # normal reads and writes
  capabilities_sleep_multiplier: 8   # reading capabilities is far more fragile
  maxtries: [15, 15, 15]             # ddcutil caps each at 15
  write_settle: 0.3                  # pause before the verify read
  write_attempts: 3

features:
  brightness: { vcp: 0x10, label: Brightness }

  input_source:
    vcp: 0x60
    type: select
    label: Input source
    fast_poll: true          # polled often: changes at the OSD too
    options:
      - { id: dp1, label: DisplayPort 1, write: 0x0f, read: 0x03 }

  osd_language: false        # remove a feature entirely
```

### Feature fields

| Field | Meaning |
|---|---|
| `vcp` | The VCP code. `0x60`, `"0x60"` and `96` are all accepted. |
| `type` | `select` or `continuous` |
| `label` | What a person sees |
| `category` | `control` (default) or `sensor` |
| `readonly` | Show it, never write it |
| `min` / `max` | For `continuous`, defaults 0–100 |
| `unit` | Appended when displaying |
| `fast_poll` | Poll every 15 s instead of every 5 min |
| `static` | Never changes while powered — read once at startup |
| `options` | For `select`, see below |

### Options

```yaml
- { id: dp2, label: DisplayPort 2, write: 0x10, read: 0x04, guard: local_video }
```

- `id` — the stable identifier. This is what the API and MQTT use, so renaming a
  `label` never breaks an automation.
- `write` — what to send.
- `read` — what comes back afterwards. **Defaults to `write`**, so you only set
  it for monitors that do not round-trip.
- `guard` — a precondition. Currently only `local_video`, which refuses the
  write unless this machine is verifiably producing a video signal. Put it on
  the input this machine is plugged into: a monitor displaying an input with no
  signal wedges its DDC engine, recoverable only through the OSD.

## Finding your values

Install the service first, then on the Pi:

```bash
sudo -u monitorctl MONITORCTL_CONFIG=/etc/monitorctl/config.yaml \
  python3 -m monitorctl --config /etc/monitorctl/config.yaml features
```

That lists what auto-detection found. If the input source options are missing or
wrong, probe for the real ones:

```bash
python3 -m monitorctl probe --feature input_source
```

The probe walks candidate values, writes each one, and reports what reads back.
**Every write reverts on its own after about twelve seconds unless you confirm
it**, so landing on a dead input resolves itself — you do not have to be able to
see the screen to recover.

At the end it prints an `options:` block ready to paste into a profile.

Narrow the search if you already have a guess:

```bash
python3 -m monitorctl probe --feature input_source --values 0x0f,0x10,0x11
```

## Installing a profile

Drop the file into `service/profiles/` and re-run the playbook. It is picked up
automatically if its `match` block agrees with your EDID. Check with:

```bash
python3 -m monitorctl detect
```

To force one regardless of the EDID, set `monitorctl_profile: your-profile-name`.

## Contributing

**A profile for a monitor that is not the reference one is the single most
useful contribution to this project.** Open a pull request with:

- the profile file
- the output of `ddcutil detect` and `ddcutil capabilities` (redact the serial
  number if you would rather not publish it)
- a note on which values you verified by watching the screen, as opposed to
  inferring

That last point matters. Everything in the reference profile was confirmed by
eye, and the documentation says so. Keeping that distinction is worth more than
covering more monitors quickly.
