"""Wiring: turn a Config into a live MonitorController plus its background poller."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from .config import Config
from .controller import MonitorController
from .ddc import DDC, DDCError, DDCSettings
from .events import EventBus
from .profiles import build_feature_set, load_profiles, select_profile

log = logging.getLogger(__name__)


@dataclass
class Runtime:
    config: Config
    ddc: DDC
    controller: MonitorController
    events: EventBus
    display: object
    profile_name: str


def build_runtime(config: Config) -> Runtime:
    """Detect the monitor, pick a profile, and assemble the controller."""
    events = EventBus()

    ddc = DDC(connector_glob=config.connector, bus=config.bus)
    display = ddc.detect()
    log.info(
        "detected %s %s on bus %s (VCP %s)",
        display.mfg,
        display.model,
        ddc.bus,
        display.vcp_version,
    )

    profiles = load_profiles(config.profile_dir)
    profile = select_profile(display, profiles, forced=config.profile)
    if profile:
        ddc.settings = profile.settings

    try:
        capabilities = ddc.capabilities()
    except DDCError as exc:
        # Not fatal. A profile can describe the monitor completely, and some
        # monitors refuse the capabilities read while answering everything else.
        log.warning("capabilities read failed (%s) — relying on the profile", exc)
        capabilities = ""

    features = build_feature_set(
        capabilities,
        profile,
        config.feature_overrides,
        include_unknown=config.include_unknown_features,
    )
    if not len(features):
        raise DDCError(
            "no features available: the capabilities read failed and no profile "
            "supplied any. Set `profile:` in the configuration."
        )
    log.info("%d features available", len(features))

    controller = MonitorController(
        ddc,
        features,
        toggle_between=config.toggle_between,
        on_change=lambda changed: events.publish(
            "state", {name: st.to_dict() for name, st in changed.items()}
        ),
    )

    return Runtime(
        config=config,
        ddc=ddc,
        controller=controller,
        events=events,
        display=display,
        profile_name=profile.name if profile else "auto-detected",
    )


class Poller(threading.Thread):
    """Keeps the cached state honest.

    Two cadences, because a full sweep costs upwards of ten seconds on a Pi Zero
    and the bus is shared with every user-initiated request.
    """

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(name="poller", daemon=True)
        self.runtime = runtime
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        config = self.runtime.config
        controller = self.runtime.controller

        try:
            controller.refresh()
        except Exception:
            log.exception("initial refresh failed")

        last_slow = time.monotonic()
        while not self._stop.wait(config.fast_poll_interval):
            now = time.monotonic()
            full = now - last_slow >= config.slow_poll_interval
            try:
                controller.refresh(fast_only=not full)
            except Exception:
                log.exception("poll failed")
            if full:
                last_slow = now
