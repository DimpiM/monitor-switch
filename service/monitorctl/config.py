"""Configuration loading.

Settings come from a YAML file, with secrets kept separate in the environment so
that the config file can stay world-readable while credentials do not.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import yaml

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "/etc/monitorctl/config.yaml"


@dataclass
class MQTTConfig:
    enabled: bool = False
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    tls: bool = False
    discovery_prefix: str = "homeassistant"
    node_id: str = "monitorctl"
    device_name: str = "Monitor"

    @property
    def base_topic(self) -> str:
        return f"monitorctl/{self.node_id}"


@dataclass
class Config:
    # Bind to the loopback by default. There is no authentication, so opening
    # this up is a deliberate act, not an accident.
    host: str = "127.0.0.1"
    port: int = 8765

    connector: str = "/sys/class/drm/card*-HDMI-A-1"
    bus: int | None = None
    profile: str | None = None
    profile_dir: str | None = None
    feature_overrides: dict = field(default_factory=dict)
    # Surface VCP codes this build has no metadata for. Off by default: they
    # cost a slow read each poll and are usually not worth reading.
    include_unknown_features: bool = False

    toggle_between: list[str] = field(default_factory=list)

    fast_poll_interval: float = 15.0    # input source — changes behind our back
    slow_poll_interval: float = 300.0   # everything else — only we change it

    mqtt: MQTTConfig = field(default_factory=MQTTConfig)

    log_level: str = "INFO"

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        path = path or os.environ.get("MONITORCTL_CONFIG", DEFAULT_CONFIG_PATH)
        data: dict = {}
        if os.path.exists(path):
            try:
                with open(path) as handle:
                    data = yaml.safe_load(handle) or {}
            except (OSError, yaml.YAMLError) as exc:
                log.error("cannot read config %s: %s — using defaults", path, exc)
        else:
            log.warning("config %s not found, using defaults", path)

        mqtt_data = data.pop("mqtt", None) or {}
        config = cls(**{k: v for k, v in data.items() if k in cls.__annotations__})
        config.mqtt = MQTTConfig(
            **{k: v for k, v in mqtt_data.items() if k in MQTTConfig.__annotations__}
        )
        config._apply_environment()
        return config

    def _apply_environment(self) -> None:
        """Environment wins over the file. Secrets belong here, not in YAML."""
        env = os.environ
        if "MONITORCTL_HOST" in env:
            self.host = env["MONITORCTL_HOST"]
        if "MONITORCTL_PORT" in env:
            self.port = int(env["MONITORCTL_PORT"])
        if "MONITORCTL_LOG_LEVEL" in env:
            self.log_level = env["MONITORCTL_LOG_LEVEL"]
        if "MONITORCTL_MQTT_HOST" in env:
            self.mqtt.host = env["MONITORCTL_MQTT_HOST"]
            self.mqtt.enabled = True
        if "MONITORCTL_MQTT_PORT" in env:
            self.mqtt.port = int(env["MONITORCTL_MQTT_PORT"])
        if "MONITORCTL_MQTT_USERNAME" in env:
            self.mqtt.username = env["MONITORCTL_MQTT_USERNAME"]
        if "MONITORCTL_MQTT_PASSWORD" in env:
            self.mqtt.password = env["MONITORCTL_MQTT_PASSWORD"]
