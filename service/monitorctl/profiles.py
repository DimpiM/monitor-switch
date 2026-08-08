"""Monitor profiles: YAML overlays on top of what the monitor reports about itself.

Three layers, each overriding the previous:

1. **Auto-detection** — parse ``ddcutil capabilities``.
2. **Monitor profile** — a YAML file matched against the EDID.
3. **Local overrides** — from the instance configuration.

Layer 2 exists because capabilities strings can be wrong. The monitor this project
was built around declares input-source values that do not exist and hides the ones
that work, so no amount of auto-detection would find them. A profile states the
measured truth and wins.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import yaml

from .ddc import DDCSettings, DisplayInfo
from .features import Feature, FeatureSet, merge_feature, parse_capabilities

log = logging.getLogger(__name__)

DEFAULT_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "profiles")


@dataclass
class Profile:
    name: str
    match: dict = field(default_factory=dict)
    settings: DDCSettings = field(default_factory=DDCSettings)
    features: dict = field(default_factory=dict)
    source: str = "<builtin>"

    def matches(self, info: DisplayInfo) -> bool:
        """A profile matches when every key it names agrees with the EDID.

        An empty match block never matches automatically — that is how the
        ``generic`` fallback avoids hijacking real monitors.
        """
        if not self.match:
            return False
        for key, expected in self.match.items():
            actual = getattr(info, key, None)
            if actual is None:
                return False
            if str(actual).strip().lower() != str(expected).strip().lower():
                return False
        return True


def load_profiles(directory: str | None = None) -> list[Profile]:
    directory = os.path.abspath(directory or DEFAULT_PROFILE_DIR)
    profiles: list[Profile] = []
    if not os.path.isdir(directory):
        log.warning("profile directory %s does not exist", directory)
        return profiles

    for entry in sorted(os.listdir(directory)):
        if not entry.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(directory, entry)
        try:
            with open(path) as handle:
                data = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError) as exc:
            log.error("cannot read profile %s: %s", path, exc)
            continue
        profiles.append(_profile_from_dict(data, source=path))
    return profiles


def _profile_from_dict(data: dict, *, source: str) -> Profile:
    ddc_block = data.get("ddc") or {}
    defaults = DDCSettings()
    settings = DDCSettings(
        sleep_multiplier=float(
            ddc_block.get("sleep_multiplier", defaults.sleep_multiplier)
        ),
        capabilities_sleep_multiplier=float(
            ddc_block.get(
                "capabilities_sleep_multiplier",
                defaults.capabilities_sleep_multiplier,
            )
        ),
        maxtries=tuple(ddc_block.get("maxtries", defaults.maxtries)),  # type: ignore[arg-type]
        write_settle=float(ddc_block.get("write_settle", defaults.write_settle)),
        write_attempts=int(
            ddc_block.get("write_attempts", defaults.write_attempts)
        ),
    )
    return Profile(
        name=str(data.get("name", os.path.basename(source))),
        match=data.get("match") or {},
        settings=settings,
        features=data.get("features") or {},
        source=source,
    )


def select_profile(
    info: DisplayInfo, profiles: list[Profile], forced: str | None = None
) -> Profile | None:
    """Pick a profile by explicit name, else by matching the EDID."""
    if forced:
        for profile in profiles:
            if profile.name == forced or os.path.basename(profile.source).startswith(
                forced
            ):
                log.info("using forced profile %r", profile.name)
                return profile
        log.warning("forced profile %r not found, falling back to matching", forced)

    for profile in profiles:
        if profile.matches(info):
            log.info("matched profile %r for %s %s", profile.name, info.mfg, info.model)
            return profile

    log.info(
        "no profile matched %s %s — using auto-detection only", info.mfg, info.model
    )
    return None


def build_feature_set(
    capabilities: str,
    profile: Profile | None = None,
    overrides: dict | None = None,
    *,
    include_unknown: bool = False,
) -> FeatureSet:
    """Apply the three layers and return the resulting feature set."""
    features = parse_capabilities(capabilities, include_unknown=include_unknown)

    for layer in (profile.features if profile else {}, overrides or {}):
        _apply_layer(features, layer)

    return features


def _apply_layer(features: FeatureSet, layer: dict) -> None:
    for name, override in layer.items():
        if override is None or override is False:
            features.features.pop(name, None)
            continue
        if not isinstance(override, dict):
            log.error("feature %r: expected a mapping, got %r", name, type(override))
            continue
        if override.get("enabled") is False:
            features.features.pop(name, None)
            continue

        spec = {k: v for k, v in override.items() if k != "enabled"}
        spec.setdefault("name", name)

        base: Feature | None = features.get(name)
        if base is None and "vcp" in spec:
            # A profile may introduce a feature the monitor never declared. That
            # is the whole point for monitors whose capabilities string lies.
            base = features.by_vcp(int(str(spec["vcp"]), 0))

        try:
            features.add(merge_feature(base, spec))
        except (KeyError, TypeError, ValueError) as exc:
            log.error("feature %r in profile is invalid: %s", name, exc)
