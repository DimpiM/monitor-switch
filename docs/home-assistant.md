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

The Mosquitto add-on authenticates MQTT clients against **Home Assistant user
accounts**. So the clean path is a dedicated account:

1. Settings → People → Add person
2. Give it a name such as `monitorswitch`, enable *Allow person to login*
3. Turn on *Local access only* — this account never needs to reach the internet
4. Use that username and password below

A dedicated account can be revoked on its own, and the broker log tells you
which device did what. Reusing Home Assistant's own broker credentials works
too, but then the Pi and Home Assistant are indistinguishable to the broker and
share a fate if either is compromised.

> The add-on's own `logins:` option is an alternative, but changing it requires
> the Supervisor API — which the SSH add-on blocks while protection mode is on.

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

Values on the wire are the **option ids** from the profile (`dp1`, `dp2`,
`hdmi`), not the labels — so automations keep working if you rename a label.

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
