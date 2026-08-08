"""Feature model, built-in MCCS knowledge, and the capabilities-string parser.

A *feature* is one controllable or readable property of the monitor, backed by one
VCP code. Features come from three stacked sources — auto-detection, a monitor
profile, and local overrides — merged in :mod:`monitorctl.profiles`.

The capabilities string tells us *which* VCP codes a monitor supports and, for
non-continuous features, which values it accepts. It does not tell us whether a
feature is continuous, what to call it, or what unit it carries. That knowledge is
MCCS-standard and lives in :data:`KNOWN_VCP`.

Do not trust the capabilities string blindly. At least one monitor in the wild
declares input-source values that do not exist and omits the ones that work; see
``docs/hardware-findings.md``. That is what profiles are for.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace

log = logging.getLogger(__name__)

CONTINUOUS = "continuous"
SELECT = "select"

CONTROL = "control"
SENSOR = "sensor"


@dataclass(frozen=True)
class SelectOption:
    """One value of a non-continuous feature.

    ``write`` and ``read`` are separate because some monitors do not round-trip:
    the Samsung Odyssey G9 accepts ``0x10`` to select DisplayPort 2 but reports
    ``0x04`` when asked afterwards.

    ``guard`` names a precondition that must hold before this value may be
    written. Currently only ``local_video`` exists, which requires that this
    machine is verifiably driving video on its own connector.
    """

    id: str
    label: str
    write: int
    read: int
    guard: str | None = None


@dataclass(frozen=True)
class Feature:
    name: str
    vcp: int
    type: str = CONTINUOUS
    label: str = ""
    category: str = CONTROL
    readonly: bool = False
    options: tuple[SelectOption, ...] = ()
    min: int = 0
    max: int = 100
    unit: str | None = None
    display_format: str | None = None
    scale: float = 1.0
    # Polling tier. Reads cost ~860 ms each, so what gets read how often matters.
    #   fast_poll  the input source, which changes behind our back via the OSD
    #   static     never changes while powered — read once at startup
    #   neither    slow cycle; only we change these
    fast_poll: bool = False
    static: bool = False

    def option_by_id(self, option_id: str) -> SelectOption | None:
        return next((o for o in self.options if o.id == option_id), None)

    def option_by_read(self, value: int) -> SelectOption | None:
        return next((o for o in self.options if o.read == value), None)


@dataclass
class VCPInfo:
    """Static MCCS knowledge about a VCP code."""

    name: str
    label: str
    type: str = CONTINUOUS
    category: str = CONTROL
    readonly: bool = False
    unit: str | None = None
    fast_poll: bool = False
    static: bool = False
    # "version" renders 0x0201 as "2.1"; "hex" renders 0x12 as "0x12".
    display_format: str | None = None
    # MCCS units are not always whole: vertical frequency arrives in 0.01 Hz.
    scale: float = 1.0
    # Standard value tables for features whose meaning MCCS fixes. Monitors
    # rarely list these in their capabilities string even though they answer.
    default_options: tuple[tuple[int, str], ...] = ()


# Deliberately not exhaustive — these are the codes worth surfacing in a UI.
# Anything else a monitor declares is exposed under a generic name.
KNOWN_VCP: dict[int, VCPInfo] = {
    0x10: VCPInfo("brightness", "Brightness"),
    0x12: VCPInfo("contrast", "Contrast"),
    0x14: VCPInfo("color_preset", "Colour preset", type=SELECT),
    0x16: VCPInfo("gain_red", "Red gain"),
    0x18: VCPInfo("gain_green", "Green gain"),
    0x1A: VCPInfo("gain_blue", "Blue gain"),
    0x60: VCPInfo("input_source", "Input source", type=SELECT, fast_poll=True),
    0x62: VCPInfo("volume", "Volume"),
    0x6C: VCPInfo("black_red", "Red black level"),
    0x6E: VCPInfo("black_green", "Green black level"),
    0x70: VCPInfo("black_blue", "Blue black level"),
    0x8D: VCPInfo("mute", "Mute", type=SELECT),
    0xAC: VCPInfo("h_frequency", "Horizontal frequency",
                  category=SENSOR, readonly=True, unit="Hz"),
    # MCCS defines this in units of 0.01 Hz. Spec-derived, not independently
    # verified against a known refresh rate.
    0xAE: VCPInfo("v_frequency", "Vertical frequency",
                  category=SENSOR, readonly=True, unit="Hz", scale=0.01),
    0xB6: VCPInfo("display_technology", "Display technology",
                  type=SELECT, category=SENSOR, readonly=True, static=True,
                  default_options=(
                      (0x01, "CRT (shadow mask)"),
                      (0x02, "CRT (aperture grill)"),
                      (0x03, "LCD (active matrix)"),
                      (0x04, "LCoS"),
                      (0x05, "Plasma"),
                      (0x06, "OLED"),
                      (0x07, "Electroluminescent"),
                      (0x08, "MEM"),
                  )),
    0xC0: VCPInfo("usage_hours", "Usage hours",
                  category=SENSOR, readonly=True, unit="h"),
    0xC8: VCPInfo("controller_type", "Controller type",
                  category=SENSOR, readonly=True, static=True,
                  display_format="hex"),
    0xC9: VCPInfo("firmware_level", "Firmware level",
                  category=SENSOR, readonly=True, static=True,
                  display_format="version"),
    0xCC: VCPInfo("osd_language", "OSD language", type=SELECT),
    # Power is read-only by default on purpose: a monitor that will not answer
    # DDC while asleep cannot be woken again over DDC, and you would be locked
    # out. A profile can override this if a given monitor is known to be safe.
    0xD6: VCPInfo("power", "Power state", type=SELECT, readonly=True),
    0xDC: VCPInfo("display_mode", "Display mode", type=SELECT),
    0xDF: VCPInfo("vcp_version", "VCP version",
                  category=SENSOR, readonly=True, static=True,
                  display_format="version"),
}

# Write-only MCCS actions: "restore factory defaults" and friends. Reading them
# is meaningless and each read costs the better part of a second, so they are
# never auto-exposed. A profile can still declare one deliberately.
ACTION_ONLY_VCP = frozenset({0x02, 0x03, 0x04, 0x05, 0x06, 0x08, 0x0A, 0x0B, 0x0C})


@dataclass
class FeatureSet:
    """All features for one monitor, keyed by name."""

    features: dict[str, Feature] = field(default_factory=dict)

    def __iter__(self):
        return iter(self.features.values())

    def __len__(self) -> int:
        return len(self.features)

    def get(self, name: str) -> Feature | None:
        return self.features.get(name)

    def by_vcp(self, code: int) -> Feature | None:
        return next((f for f in self.features.values() if f.vcp == code), None)

    def add(self, feature: Feature) -> None:
        self.features[feature.name] = feature

    @property
    def controls(self) -> list[Feature]:
        return [f for f in self.features.values() if f.category == CONTROL]

    @property
    def sensors(self) -> list[Feature]:
        return [f for f in self.features.values() if f.category == SENSOR]

    @property
    def fast_poll(self) -> list[Feature]:
        return [f for f in self.features.values() if f.fast_poll]

    @property
    def static(self) -> list[Feature]:
        return [f for f in self.features.values() if f.static]


# ------------------------------------------------------------------- parsing

_FEATURE_LINE = re.compile(r"^\s*Feature:\s*([0-9A-Fa-f]{2})\s*(?:\((.*?)\))?\s*$")
_VALUE_LINE = re.compile(r"^\s*([0-9A-Fa-f]{2}):\s*(.+?)\s*$")
_VALUES_HEADER = re.compile(r"^\s*Values:\s*$")


def parse_capabilities(text: str, *, include_unknown: bool = False) -> FeatureSet:
    """Build a FeatureSet from ``ddcutil capabilities`` output.

    Values are only present for non-continuous features. A declared feature with
    no value list is assumed continuous unless :data:`KNOWN_VCP` says otherwise —
    the same assumption ddcutil itself makes.

    Codes outside :data:`KNOWN_VCP` are skipped by default. Monitors declare
    plenty of codes that are useless to read, and each read costs ~860 ms of bus
    time on every poll. Set ``include_unknown`` to surface them anyway when
    exploring an unfamiliar monitor; the proper home for a useful one is a
    profile, which can name and type it correctly.
    """
    raw: dict[int, list[tuple[int, str]]] = {}
    current: int | None = None
    in_values = False

    for line in text.splitlines():
        match = _FEATURE_LINE.match(line)
        if match:
            current = int(match.group(1), 16)
            raw.setdefault(current, [])
            in_values = False
            continue
        if current is None:
            continue
        if _VALUES_HEADER.match(line):
            in_values = True
            continue
        if in_values:
            value_match = _VALUE_LINE.match(line)
            if value_match:
                raw[current].append((int(value_match.group(1), 16),
                                     value_match.group(2)))
            else:
                in_values = False

    result = FeatureSet()
    skipped: list[int] = []
    for code, values in raw.items():
        if code in ACTION_ONLY_VCP:
            continue
        if code not in KNOWN_VCP and not include_unknown:
            skipped.append(code)
            continue
        result.add(_feature_from_capabilities(code, values))

    if skipped:
        log.info(
            "monitor declares %d code(s) this build has no metadata for: %s. "
            "Declare any you want in a profile.",
            len(skipped),
            ", ".join(f"0x{c:02X}" for c in sorted(skipped)),
        )
    return result


def _feature_from_capabilities(
    code: int, values: list[tuple[int, str]]
) -> Feature:
    info = KNOWN_VCP.get(code) or VCPInfo(
        name=f"vcp_{code:02x}",
        label=f"VCP 0x{code:02X}",
        type=SELECT if values else CONTINUOUS,
        category=SENSOR,
        readonly=True,
    )

    # A monitor that lists values wins; otherwise fall back to the MCCS-standard
    # table if this build ships one for the code.
    declared = values or list(info.default_options)

    options: tuple[SelectOption, ...] = ()
    feature_type = info.type
    if declared:
        feature_type = SELECT
        options = tuple(
            SelectOption(
                id=_slug(label) or f"v{value:02x}",
                label=label,
                write=value,
                read=value,
            )
            for value, label in declared
        )

    # A select whose values the monitor did not list stays a select with no
    # options: unsettable in practice, but a profile can supply the values. It
    # deliberately does NOT become read-only here — that flag would survive the
    # profile overlay and silently disable a feature the profile just fixed.
    return Feature(
        name=info.name,
        vcp=code,
        type=feature_type,
        label=info.label,
        category=info.category,
        readonly=info.readonly,
        options=options,
        unit=info.unit,
        fast_poll=info.fast_poll,
        static=info.static,
        display_format=info.display_format,
        scale=info.scale,
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def merge_feature(base: Feature | None, override: dict) -> Feature:
    """Apply a profile's dict onto a detected feature, or create one outright."""
    options = base.options if base else ()
    if "options" in override:
        options = tuple(
            SelectOption(
                id=str(opt["id"]),
                label=str(opt.get("label", opt["id"])),
                write=_as_int(opt["write"]),
                read=_as_int(opt.get("read", opt["write"])),
                guard=opt.get("guard"),
            )
            for opt in override["options"]
        )

    fields = {k: v for k, v in override.items() if k not in {"options", "vcp"}}
    if "vcp" in override:
        fields["vcp"] = _as_int(override["vcp"])
    fields["options"] = options

    if base is None:
        fields.setdefault("name", override.get("name", ""))
        fields.setdefault("type", SELECT if options else CONTINUOUS)
        fields.setdefault("label", fields.get("name", ""))
        return Feature(**fields)
    return replace(base, **fields)


def _as_int(value) -> int:
    """Accept ``0x60``, ``"0x60"`` and ``96`` alike — YAML makes all three easy."""
    if isinstance(value, int):
        return value
    return int(str(value), 0)
