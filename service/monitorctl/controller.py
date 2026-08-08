"""The stateful layer: what the monitor currently is, and how to change it.

Holds a cache of feature values so the HTTP API and the MQTT bridge can answer
instantly. Reads are slow — around 860 ms each — so a full sweep of a dozen
features takes over ten seconds. That is far too slow to do on request, and far
too heavy to do on a tight loop.

The refresh strategy follows from one observation: the input source is the only
feature that changes without us doing it, via the OSD or the monitor's own
auto-switching. Everything else only moves when we move it. So the input source
is polled often and the rest rarely.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .ddc import DDC, DDCError
from .features import CONTINUOUS, SELECT, Feature, FeatureSet

log = logging.getLogger(__name__)


class FeatureNotFound(KeyError):
    pass


class ReadOnlyFeature(PermissionError):
    pass


class GuardRejected(PermissionError):
    """A write was refused because its precondition did not hold."""


@dataclass
class FeatureState:
    name: str
    label: str
    type: str
    category: str
    readonly: bool
    raw: int | None = None
    value: Any = None       # option id for selects, int for continuous
    display: str | None = None
    maximum: int | None = None
    unit: str | None = None
    error: str | None = None
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _render(feature: Feature, raw: int) -> tuple[Any, str]:
    """Turn a raw VCP value into something a person would recognise."""
    if feature.display_format == "version":
        # Complex non-continuous features pack major and minor into one word.
        return f"{raw >> 8}.{raw & 0xFF}", f"{raw >> 8}.{raw & 0xFF}"
    if feature.display_format == "hex":
        return raw, f"0x{raw:02X}"
    if feature.scale != 1.0:
        scaled = round(raw * feature.scale, 2)
        return scaled, f"{scaled:g}{feature.unit or ''}"
    return raw, f"{raw}{feature.unit or ''}"


class MonitorController:
    def __init__(
        self,
        ddc: DDC,
        features: FeatureSet,
        *,
        toggle_between: list[str] | None = None,
        on_change: Callable[[dict[str, FeatureState]], None] | None = None,
    ) -> None:
        self.ddc = ddc
        self.features = features
        self.toggle_between = toggle_between or []
        self._on_change = on_change
        self._state: dict[str, FeatureState] = {}
        self._lock = threading.RLock()
        # Number of user-initiated operations in flight. The background sweep
        # steps aside while this is non-zero: a full sweep is ~20 s of bus time
        # on a Pi Zero, and nobody should wait through it to change an input.
        self._user_ops = 0
        self._full_refresh_wanted = threading.Event()

    @contextmanager
    def _user_operation(self):
        with self._lock:
            self._user_ops += 1
        try:
            yield
        finally:
            with self._lock:
                self._user_ops -= 1

    @property
    def _user_busy(self) -> bool:
        with self._lock:
            return self._user_ops > 0

    # ------------------------------------------------------------------ state

    def state(self) -> dict[str, dict]:
        with self._lock:
            return {name: st.to_dict() for name, st in self._state.items()}

    def _has_value(self, name: str) -> bool:
        with self._lock:
            state = self._state.get(name)
        return state is not None and state.raw is not None

    def _publish(self, changed: dict[str, FeatureState]) -> None:
        if changed and self._on_change:
            try:
                self._on_change(changed)
            except Exception:  # a broken subscriber must not break control
                log.exception("state change subscriber raised")

    # ------------------------------------------------------------------ reads

    def refresh(self, *, fast_only: bool = False) -> dict[str, FeatureState]:
        """Re-read features from the monitor. Returns only what changed.

        Static features (firmware level, controller type) are read once and then
        skipped — they cannot change while the monitor is powered, and at ~860 ms
        a read they are not worth revisiting every cycle.
        """
        if fast_only:
            targets = self.features.fast_poll
        else:
            targets = [
                f
                for f in self.features
                if not (f.static and self._has_value(f.name))
            ]
        changed: dict[str, FeatureState] = {}

        for feature in targets:
            # Yield the bus the moment somebody actually wants something. The
            # remaining features keep until the next cycle; none of them are
            # urgent, which is why they are on the slow tier in the first place.
            if self._user_busy:
                log.debug("refresh yielding to a user request")
                break
            new = self._read(feature)
            with self._lock:
                old = self._state.get(feature.name)
                self._state[feature.name] = new
            if old is None or (old.raw, old.error) != (new.raw, new.error):
                changed[feature.name] = new

        self._publish(changed)
        return changed

    def _read(self, feature: Feature) -> FeatureState:
        try:
            raw, maximum = self.ddc.get_vcp(feature.vcp)
        except DDCError as exc:
            log.warning("reading %s (0x%02X) failed: %s", feature.name, feature.vcp, exc)
            return FeatureState(
                name=feature.name,
                label=feature.label or feature.name,
                type=feature.type,
                category=feature.category,
                readonly=feature.readonly,
                unit=feature.unit,
                error=str(exc),
                updated_at=time.time(),
            )
        return self._state_from_raw(feature, raw, maximum)

    def _state_from_raw(
        self, feature: Feature, raw: int, maximum: int | None = None
    ) -> FeatureState:
        """Build a state from a value already known.

        A verified write has just read the value back; reading it a second time
        would add the better part of a second to every switch for nothing.
        """
        state = FeatureState(
            name=feature.name,
            label=feature.label or feature.name,
            type=feature.type,
            category=feature.category,
            readonly=feature.readonly,
            unit=feature.unit,
            updated_at=time.time(),
        )
        if maximum is None:
            # Carry the previously known maximum rather than dropping it.
            with self._lock:
                previous = self._state.get(feature.name)
            maximum = previous.maximum if previous else None

        state.raw = raw
        state.maximum = maximum
        if feature.type == SELECT:
            option = feature.option_by_read(raw)
            state.value = option.id if option else None
            state.display = option.label if option else f"unknown (0x{raw:02X})"
            if option is None:
                # Worth surfacing: it usually means the profile is incomplete for
                # this monitor, which is exactly what we want a user to notice.
                log.info(
                    "%s read 0x%02X, which no option maps to", feature.name, raw
                )
        else:
            state.value, state.display = _render(feature, raw)
        return state

    def get(self, name: str) -> FeatureState:
        feature = self._feature(name)
        with self._user_operation():
            new = self._read(feature)
        with self._lock:
            old = self._state.get(name)
            self._state[name] = new
        if old is None or (old.raw, old.error) != (new.raw, new.error):
            self._publish({name: new})
        return new

    # ----------------------------------------------------------------- writes

    def set(self, name: str, value: Any) -> FeatureState:
        with self._user_operation():
            return self._set(name, value)

    def _set(self, name: str, value: Any) -> FeatureState:
        feature = self._feature(name)
        if feature.readonly:
            raise ReadOnlyFeature(f"{name} is read-only")

        if feature.type == SELECT:
            option = feature.option_by_id(str(value))
            if option is None:
                valid = ", ".join(o.id for o in feature.options)
                raise ValueError(f"{name}: unknown option {value!r}. Valid: {valid}")
            self._check_guard(feature, option.guard)
            confirmed = self.ddc.set_vcp(
                feature.vcp, option.write, verify_as=option.read
            )
        elif feature.type == CONTINUOUS:
            number = int(value)
            if not feature.min <= number <= feature.max:
                raise ValueError(
                    f"{name}: {number} out of range {feature.min}..{feature.max}"
                )
            confirmed = self.ddc.set_vcp(feature.vcp, number)
        else:
            raise ValueError(f"{name}: unsupported feature type {feature.type!r}")

        # set_vcp only returns once it has read the value back, so the state is
        # already known. Re-reading here would double the cost of every write.
        new = self._state_from_raw(feature, confirmed)
        with self._lock:
            previous = self._state.get(name)
            self._state[name] = new

        # Monitors commonly keep separate settings per input — measured on a
        # Samsung Odyssey G9, brightness reads 11 on HDMI and 60 on DisplayPort.
        # So changing the input invalidates the cached value of everything else.
        # Re-reading inline would add ~20 s to the response, so the sweep is
        # handed to the poller instead.
        if feature.fast_poll and (previous is None or previous.raw != confirmed):
            self.request_full_refresh()

        self._publish({name: new})
        return new

    def request_full_refresh(self) -> None:
        """Ask the poller to re-read everything at its next opportunity."""
        self._full_refresh_wanted.set()

    @property
    def full_refresh_wanted(self) -> bool:
        return self._full_refresh_wanted.is_set()

    def clear_full_refresh(self) -> None:
        self._full_refresh_wanted.clear()

    def _check_guard(self, feature: Feature, guard: str | None) -> None:
        if guard is None:
            return
        if guard == "local_video":
            if not self.ddc.local_video_active():
                raise GuardRejected(
                    f"refusing to set {feature.name}: this machine is not currently "
                    "driving video on its connector. Switching there would leave the "
                    "monitor showing a dead input, which wedges its DDC engine."
                )
            return
        raise GuardRejected(f"{feature.name}: unknown guard {guard!r}")

    # ------------------------------------------------------------ convenience

    @property
    def input_feature(self) -> Feature:
        feature = self.features.get("input_source")
        if feature is None:
            raise FeatureNotFound("this monitor has no input_source feature")
        return feature

    def current_input(self) -> str | None:
        return self.get("input_source").value

    def switch_input(self, option_id: str) -> FeatureState:
        return self.set("input_source", option_id)

    def toggle(self) -> FeatureState:
        """Move to the next input in the configured toggle list."""
        options = self.toggle_between or [o.id for o in self.input_feature.options]
        if len(options) < 2:
            raise ValueError(
                "toggling needs at least two inputs; configure toggle_between"
            )
        current = self.current_input()
        try:
            nxt = options[(options.index(current) + 1) % len(options)]
        except ValueError:
            # Currently on something outside the list — go to the first entry.
            nxt = options[0]
        log.info("toggle: %s -> %s", current, nxt)
        return self.switch_input(nxt)

    def _feature(self, name: str) -> Feature:
        feature = self.features.get(name)
        if feature is None:
            raise FeatureNotFound(f"unknown feature {name!r}")
        return feature
