"""Home Assistant integration over MQTT discovery.

Every feature the profile exposes becomes an entity: selects for the input
source and picture modes, numbers for the sliders, sensors for the read-only
values. Home Assistant learns the whole set from the discovery messages, so
adding a feature to a profile is enough — nothing needs configuring in HA.

State is published from the same cache the web UI uses, which is fed by polling
the monitor rather than by remembering what we last told it. That distinction
matters: someone pressing buttons on the monitor's own OSD shows up in Home
Assistant within a poll interval.

This is an integration, not a dependency. Every failure here is logged and
swallowed; the HTTP API and web UI keep working without it.
"""

from __future__ import annotations

import json
import logging
import threading

import paho.mqtt.client as mqtt

from .app import Runtime
from .controller import FeatureState
from .features import CONTINUOUS, SELECT, SENSOR, Feature

log = logging.getLogger(__name__)


class MQTTBridge:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.config = runtime.config.mqtt
        self.controller = runtime.controller
        self._lock = threading.Lock()

        self.base = self.config.base_topic
        self.availability_topic = f"{self.base}/availability"

        # paho 2.x requires the callback API version; 1.x does not know the
        # argument at all. Both are in the wild across Debian releases.
        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"monitorctl-{self.config.node_id}",
            )
        except AttributeError:  # paho-mqtt 1.x
            self._client = mqtt.Client(client_id=f"monitorctl-{self.config.node_id}")

        if self.config.username:
            self._client.username_pw_set(self.config.username, self.config.password)
        if self.config.tls:
            self._client.tls_set()

        # Last will, so Home Assistant marks the entities unavailable if this
        # process dies rather than showing a frozen last-known value.
        self._client.will_set(self.availability_topic, "offline", retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        log.info("connecting to MQTT at %s:%d", self.config.host, self.config.port)
        self._client.connect_async(self.config.host, self.config.port, keepalive=60)
        # loop_start owns reconnection; a broker restart recovers by itself.
        self._client.loop_start()
        self.controller.add_listener(self._on_state_change)

    def stop(self) -> None:
        try:
            self._client.publish(self.availability_topic, "offline", retain=True)
            self._client.disconnect()
            self._client.loop_stop()
        except Exception:
            log.exception("error while shutting the MQTT bridge down")

    # ------------------------------------------------------------- callbacks

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", reason_code != 0):
            log.error("MQTT connection refused: %s", reason_code)
            return
        log.info("MQTT connected")
        self._announce()
        client.publish(self.availability_topic, "online", retain=True)
        for feature in self.controller.features:
            if not feature.readonly:
                client.subscribe(self._command_topic(feature.name))
        self._publish_all()

    def _on_disconnect(self, client, userdata, *args):
        log.warning("MQTT disconnected; paho will keep retrying")

    def _on_message(self, client, userdata, message):
        name = message.topic.rsplit("/", 2)[-2]
        payload = message.payload.decode(errors="replace").strip()
        log.info("MQTT command: %s = %r", name, payload)

        feature = self.controller.features.get(name)
        if feature is None:
            log.warning("MQTT command for unknown feature %r", name)
            return
        try:
            if feature.type == CONTINUOUS:
                value = int(payload)
            else:
                value = self._option_id(feature, payload)
            self.controller.set(name, value)
        except Exception as exc:
            # Home Assistant has no channel to show this, so the log is the only
            # place it can surface. Re-publishing current state below keeps the
            # dashboard from sitting on a value that never took effect.
            log.error("MQTT command %s=%r failed: %s", name, payload, exc)
            self._publish_feature(name)

    def _on_state_change(self, changed: dict[str, FeatureState]) -> None:
        for name, state in changed.items():
            self._publish_state(name, state)

    # ------------------------------------------------------- option naming

    # Home Assistant shows a select's options verbatim and sends the chosen one
    # straight back, so the list has to be human-readable — "dp1" in a dropdown
    # helps nobody. Labels are used unless two of them collide, in which case
    # the whole feature falls back to ids rather than becoming ambiguous.
    @staticmethod
    def _use_labels(feature: Feature) -> bool:
        labels = [o.label or o.id for o in feature.options]
        return len(set(labels)) == len(labels)

    @classmethod
    def _option_names(cls, feature: Feature) -> list[str]:
        if cls._use_labels(feature):
            return [o.label or o.id for o in feature.options]
        return [o.id for o in feature.options]

    @classmethod
    def _option_name(cls, feature: Feature, option_id: str | None) -> str | None:
        option = feature.option_by_id(option_id) if option_id else None
        if option is None:
            return option_id
        return (option.label or option.id) if cls._use_labels(feature) else option.id

    @staticmethod
    def _option_id(feature: Feature, payload: str) -> str:
        """Accept either the label shown in Home Assistant or the raw id."""
        for option in feature.options:
            if payload in ((option.label or option.id), option.id):
                return option.id
        # Let the controller reject it, so the error message lists valid values.
        return payload

    # -------------------------------------------------------------- topics

    def _state_topic(self, name: str) -> str:
        return f"{self.base}/{name}/state"

    def _command_topic(self, name: str) -> str:
        return f"{self.base}/{name}/set"

    # ------------------------------------------------------------ discovery

    @property
    def _device(self) -> dict:
        info = self.runtime.display
        return {
            "identifiers": [f"monitorctl_{self.config.node_id}"],
            "name": self.config.device_name,
            "manufacturer": info.mfg or "Unknown",
            "model": info.model or "Monitor",
            "sw_version": _version(),
            "configuration_url": f"http://{self.runtime.config.host}:{self.runtime.config.port}/",
        }

    def _announce(self) -> None:
        for feature in self.controller.features:
            component, payload = self._discovery_for(feature)
            topic = (
                f"{self.config.discovery_prefix}/{component}/"
                f"{self.config.node_id}/{feature.name}/config"
            )
            self._client.publish(topic, json.dumps(payload), retain=True)
        log.info("announced %d entities to Home Assistant",
                 len(self.controller.features))

    def _discovery_for(self, feature: Feature) -> tuple[str, dict]:
        payload = {
            "name": feature.label or feature.name,
            "unique_id": f"monitorctl_{self.config.node_id}_{feature.name}",
            "object_id": f"{self.config.node_id}_{feature.name}",
            "state_topic": self._state_topic(feature.name),
            "availability_topic": self.availability_topic,
            "device": self._device,
        }

        if feature.readonly or feature.category == SENSOR:
            if feature.unit:
                payload["unit_of_measurement"] = feature.unit
            # Usage hours only ever increases; telling HA makes long-term
            # statistics work instead of being discarded as noise.
            if feature.name == "usage_hours":
                payload["state_class"] = "total_increasing"
                payload["device_class"] = "duration"
            payload["entity_category"] = "diagnostic"
            return "sensor", payload

        payload["command_topic"] = self._command_topic(feature.name)

        if feature.type == SELECT:
            payload["options"] = self._option_names(feature)
            return "select", payload

        payload.update(
            {
                "min": feature.min,
                "max": feature.max,
                "step": 1,
                "mode": "slider",
            }
        )
        if feature.unit:
            payload["unit_of_measurement"] = feature.unit
        return "number", payload

    # ---------------------------------------------------------------- state

    def _publish_all(self) -> None:
        for name, item in self.controller.state().items():
            self._publish_raw(name, item)

    def _publish_feature(self, name: str) -> None:
        item = self.controller.state().get(name)
        if item:
            self._publish_raw(name, item)

    def _publish_state(self, name: str, state: FeatureState) -> None:
        self._publish_raw(name, state.to_dict())

    def _publish_raw(self, name: str, item: dict) -> None:
        if item.get("error"):
            # "unknown" is a real state in Home Assistant and reads better on a
            # dashboard than a stale number that happens to look plausible.
            value = "unknown"
        else:
            value = item.get("value")
            feature = self.controller.features.get(name)
            # The state has to match one of the announced options exactly, or
            # Home Assistant shows the entity as having an invalid value.
            if feature is not None and feature.type == SELECT and value is not None:
                value = self._option_name(feature, str(value))
            if value is None:
                value = "unknown"
        with self._lock:
            self._client.publish(self._state_topic(name), str(value), retain=True)


def _version() -> str:
    from . import __version__

    return __version__
