# Home Assistant

`monitorctl` announces itself over MQTT discovery. Every feature in the active
profile becomes an entity, so adding a feature to a profile is enough — nothing
needs configuring in Home Assistant.

| Feature kind | Entity |
|---|---|
| Input source, picture mode, colour preset, mute | `select` |
| Brightness, contrast, volume, RGB gain and black level | `number` (slider) |
| Usage hours, frequencies, firmware, power state | `sensor`, marked diagnostic |

State comes from polling the monitor, not from remembering the last command
sent. So changing the input at the monitor's own OSD shows up in Home Assistant
within a poll interval — by default 15 seconds for the input source.

A last will marks everything unavailable if the service dies, instead of leaving
a stale value on the dashboard.

## What you need

- An MQTT broker Home Assistant is connected to. On Home Assistant OS this is
  usually the **Mosquitto broker** add-on.
- Credentials the Pi can use.

## Credentials

The Mosquitto add-on has its own `logins` list, and that is the cleanest place
for a device credential — it is independent of Home Assistant user accounts, so
nothing about your own login is involved, and it can be revoked on its own.

**Settings → Add-ons → Mosquitto broker → Configuration:**

```yaml
logins:
  - username: monitorswitch
    password: <something long and random>
```

Save, then **restart the add-on**. That briefly disconnects every MQTT client;
Home Assistant's own integration reconnects by itself.

> Generate the password rather than inventing one:
> ```bash
> python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(32)))"
> ```

### Alternatives

The add-on also authenticates against **Home Assistant user accounts**, so a
dedicated person created under Settings → People works too — give it *Local
access only*. That is a reasonable choice if you would rather manage device
access alongside your other accounts.

What is not a good idea is reusing Home Assistant's own broker credentials: the
Pi and Home Assistant then look identical to the broker, cannot be revoked
separately, and share a fate if either is compromised.

## Configuration

In `ansible/group_vars/all.yml`:

```yaml
monitorctl_mqtt_enabled: true
monitorctl_mqtt_host: homeassistant.local   # or the broker's address
monitorctl_mqtt_port: 1883
monitorctl_mqtt_username: monitorswitch
monitorctl_mqtt_password: "…"
monitorctl_mqtt_device_name: "Desk monitor"
```

Keep the password out of the repository — `group_vars/all.yml` is gitignored,
and [Ansible Vault](https://docs.ansible.com/ansible/latest/vault_guide/index.html)
is better still:

```bash
ansible-vault encrypt_string 'the-password' --name monitorctl_mqtt_password
```

Then re-run the playbook. It installs `python3-paho-mqtt` and restarts the
service.

## Topics

Discovery lands under `homeassistant/<component>/<node_id>/<feature>/config`.
Runtime traffic uses:

```
monitorctl/<node_id>/availability        online | offline
monitorctl/<node_id>/<feature>/state     current value
monitorctl/<node_id>/<feature>/set       write a value here
```

`<node_id>` is `monitorctl` unless you change `monitorctl_mqtt_node_id`. Set it
per device if you run more than one.

### Which values travel on the wire

For selects, the **labels** from the profile — `Windows`, `Linux`, `7500 K` —
not the internal ids. Home Assistant shows a select's options verbatim and sends
the chosen one straight back, so `dp1` in a dropdown would help nobody.

Two consequences worth knowing:

- **Renaming a label changes what automations must send.** The command topic
  also accepts the raw id, so `dp2` keeps working alongside `Linux`; only the
  dropdown and the published state follow the label.
- **If two options share a label**, that feature falls back to ids rather than
  becoming ambiguous.

The HTTP API is unaffected and always speaks ids.

### Naming the inputs

`dp1` and `dp2` describe the cable, not the machine. Put the names you actually
use in `monitorctl_feature_overrides` — the local layer, not the shipped
profile, because "Windows" is a property of your desk rather than of the
monitor:

```yaml
monitorctl_feature_overrides:
  input_source:
    options:
      - { id: dp1,  label: Windows, write: 0x0f, read: 0x03 }
      - { id: dp2,  label: Linux,   write: 0x10, read: 0x04 }
      - { id: hdmi, label: Pi,      write: 0x11, read: 0x01, guard: local_video }
```

Copy `write` and `read` from the profile you are overriding, or the values are
lost.

## Dashboard cards

Ready-made examples, including a two-button variant for when a third input
exists but has no place on the dashboard:
[`lovelace-example.yaml`](lovelace-example.yaml).

## Automations

Switching the input from a script:

```yaml
action: select.select_option
target:
  entity_id: select.monitorctl_input_source
data:
  option: dp2
```

A physical button, wired to whichever input you want:

```yaml
triggers:
  - trigger: device
    domain: mqtt
    type: action
    subtype: single
    device_id: <your button>
actions:
  - action: select.select_option
    target:
      entity_id: select.monitorctl_input_source
    data:
      option: dp1
```

## If nothing appears

- Check the service is talking to the broker: `journalctl -u monitorctl | grep -i mqtt`
- `MQTT connection refused: Not authorized` means the credentials are wrong, or
  the account cannot log in.
- Entities showing as unavailable means the availability topic says `offline` —
  the service is down or was stopped. `systemctl status monitorctl`.
- Discovery messages are retained. If you renamed something and stale entities
  linger, delete the device in Home Assistant and restart the service to have it
  announce again.
