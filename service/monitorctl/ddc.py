"""The only place in this project that shells out to ``ddcutil``.

Three things make DDC/CI awkward enough to justify a dedicated layer:

* **The bus is not safely shared.** Two concurrent transactions on the same I²C bus
  corrupt each other, so every invocation goes through one process-wide lock.
* **Default timing is too fast.** Without ``--sleep-multiplier`` even reading the
  capabilities aborts with "Maximum DDC retries exceeded".
* **Writes can be swallowed.** A write that returns success may not have taken
  effect, so every write is verified by reading the value back.

See ``docs/hardware-findings.md`` for the measurements behind these choices.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# One lock for the whole process. ddcutil talks to a single I²C bus and the
# waitress worker pool is multi-threaded, so this is not optional.
_BUS_LOCK = threading.Lock()

# A getvcp takes ~860 ms and a setvcp ~785 ms at sleep-multiplier 4 (measured on a
# Pi Zero 2 W). Capabilities can take far longer because it needs multiplier 8.
DEFAULT_TIMEOUT = 30
CAPABILITIES_TIMEOUT = 240


class DDCError(RuntimeError):
    """A ddcutil invocation failed or returned something unusable."""


class VerifyError(DDCError):
    """A write was accepted but reading the value back never confirmed it."""


@dataclass(frozen=True)
class DDCSettings:
    """Timing knobs. Monitors differ wildly, so profiles may override these."""

    sleep_multiplier: float = 4.0
    capabilities_sleep_multiplier: float = 8.0
    maxtries: tuple[int, int, int] = (15, 15, 15)  # ddcutil caps each at 15
    # Pause between a write and the read that verifies it. Measured on a Samsung
    # Odyssey G9: 1.0 s, 0.6, 0.3 and even 0.1 all landed 18/18 writes on the
    # first attempt. 0.3 keeps a margin on a monitor documented as temperamental
    # while cutting ~0.6 s off every switch; the retry loop covers the rest.
    write_settle: float = 0.3
    write_attempts: int = 3


@dataclass(frozen=True)
class DisplayInfo:
    """What the EDID says about the attached monitor. Used to pick a profile."""

    mfg: str | None = None
    model: str | None = None
    product_code: str | None = None
    vcp_version: str | None = None
    connector: str | None = None


class DDC:
    """Serialised access to one monitor on one I²C bus.

    The bus number is resolved from sysfs rather than configured, because it can
    move across reboots. ``connector`` selects which DRM connector to follow; the
    default matches the HDMI output a Raspberry Pi drives.
    """

    def __init__(
        self,
        connector_glob: str = "/sys/class/drm/card*-HDMI-A-1",
        settings: DDCSettings | None = None,
        bus: int | None = None,
        ddcutil: str = "ddcutil",
    ) -> None:
        self.connector_glob = connector_glob
        self.settings = settings or DDCSettings()
        self.ddcutil = ddcutil
        self._bus = bus
        self._pinned_bus = bus is not None
        self._connector_path: str | None = None

    # ------------------------------------------------------------------ bus

    @property
    def bus(self) -> int:
        if self._bus is None:
            self._bus = self.resolve_bus()
        return self._bus

    def invalidate_bus(self) -> None:
        """Forget the cached bus number so the next call re-resolves it.

        Called after a failure: bus numbering can shift when the graphics stack
        re-probes, and a stale number produces confusing errors.
        """
        if not self._pinned_bus:
            self._bus = None
            self._connector_path = None

    def resolve_bus(self) -> int:
        """Find the DDC bus by following the connector's ``ddc`` symlink."""
        for path in sorted(glob.glob(self.connector_glob)):
            ddc_link = os.path.join(path, "ddc")
            if not os.path.exists(ddc_link):
                continue
            target = os.path.basename(os.path.realpath(ddc_link))
            match = re.fullmatch(r"i2c-(\d+)", target)
            if match:
                self._connector_path = path
                log.debug("resolved DDC bus %s via %s", match.group(1), ddc_link)
                return int(match.group(1))
        raise DDCError(
            f"no DDC bus found for connector glob {self.connector_glob!r}. "
            "Is the monitor connected, and is the i2c_dev module loaded?"
        )

    @property
    def connector_path(self) -> str | None:
        if self._connector_path is None:
            try:
                self.resolve_bus()
            except DDCError:
                return None
        return self._connector_path

    # -------------------------------------------------------------- local video

    def local_video_active(self) -> bool:
        """True when this machine is verifiably driving video on its connector.

        This is the guard that makes switching to our own input safe. A monitor
        that ends up *displaying* an input with no signal wedges its DDC engine —
        recoverable only via the OSD or a link reset. Refusing the switch unless
        we know we are painting pixels removes that failure mode entirely.
        """
        path = self.connector_path
        if not path:
            return False
        try:
            status = _read_sysfs(os.path.join(path, "status"))
            enabled = _read_sysfs(os.path.join(path, "enabled"))
            dpms = _read_sysfs(os.path.join(path, "dpms"))
        except OSError as exc:
            log.warning("cannot read connector state from %s: %s", path, exc)
            return False
        active = status == "connected" and enabled == "enabled" and dpms.lower() == "on"
        if not active:
            log.warning(
                "local video not active (status=%s enabled=%s dpms=%s)",
                status,
                enabled,
                dpms,
            )
        return active

    # ------------------------------------------------------------- invocation

    def _run(
        self,
        args: list[str],
        *,
        sleep_multiplier: float | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        with_bus: bool = True,
    ) -> str:
        multiplier = (
            sleep_multiplier
            if sleep_multiplier is not None
            else self.settings.sleep_multiplier
        )
        cmd = [self.ddcutil]
        # `detect` scans every display and rejects a display selector outright,
        # so it is the one subcommand that must run without --bus.
        if with_bus:
            cmd += ["--bus", str(self.bus)]
        cmd += [
            "--sleep-multiplier",
            str(multiplier),
            "--maxtries",
            ",".join(str(n) for n in self.settings.maxtries),
            # ddcutil writes informational lines straight to the system log on
            # every invocation. At a poll every 15 s on a machine that runs on
            # an SD card, that is a steady write for no benefit — and stderr is
            # captured here anyway, so nothing diagnostic is lost.
            "--syslog",
            "NEVER",
            *args,
        ]
        with _BUS_LOCK:
            log.debug("running %s", " ".join(cmd))
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                self.invalidate_bus()
                raise DDCError(f"ddcutil timed out after {timeout}s: {args}") from exc
            except FileNotFoundError as exc:
                raise DDCError(
                    f"{self.ddcutil!r} not found — is the ddcutil package installed?"
                ) from exc

        if proc.returncode != 0:
            self.invalidate_bus()
            detail = (proc.stderr or proc.stdout or "").strip()
            raise DDCError(f"ddcutil {' '.join(args)} failed: {detail}")
        return proc.stdout

    # ------------------------------------------------------------------ reads

    def get_vcp(self, code: int) -> tuple[int, int | None]:
        """Read a VCP feature.

        Returns ``(value, maximum)``. ``maximum`` is ``None`` for non-continuous
        features. The terse format is stable across ddcutil versions and avoids
        the mislabelling that the human-readable output does (this monitor's
        input value ``0x04`` is rendered as "DVI-2", which is nonsense).
        """
        out = self._run(["getvcp", f"{code:02X}", "--terse"])
        return _parse_terse_getvcp(out, code)

    def capabilities(self) -> str:
        """Raw capabilities string. Needs much slower timing than normal reads."""
        return self._run(
            ["capabilities"],
            sleep_multiplier=self.settings.capabilities_sleep_multiplier,
            timeout=CAPABILITIES_TIMEOUT,
        )

    def detect(self) -> DisplayInfo:
        """Identify the attached monitor, for profile matching.

        ``detect`` enumerates every display it can find, so the output is split
        per display and only the block belonging to our bus is used. Anything
        else would misidentify the monitor on a machine with two of them.
        """
        out = self._run(["detect"], timeout=90, with_bus=False)
        block = _block_for_bus(out, self.bus)
        if block is None:
            raise DDCError(
                f"ddcutil detect found no display on bus {self.bus}. "
                "Is the monitor powered on and does it answer DDC/CI on this input?"
            )
        return _parse_detect(block)

    # ----------------------------------------------------------------- writes

    def set_vcp(self, code: int, value: int, *, verify_as: int | None = None) -> int:
        """Write a VCP feature and confirm it took effect.

        ``verify_as`` covers monitors whose read value differs from the value you
        write — the Samsung Odyssey G9 accepts ``0x10`` for DisplayPort 2 but
        reports ``0x04`` afterwards. When ``None``, the written value is expected
        to read back unchanged.

        Returns the value actually read back. Raises :class:`VerifyError` if the
        write never confirmed.
        """
        expected = value if verify_as is None else verify_as
        last_seen: int | None = None

        for attempt in range(1, self.settings.write_attempts + 1):
            self._run(["setvcp", f"{code:02X}", str(value)])
            time.sleep(self.settings.write_settle)
            try:
                current, _ = self.get_vcp(code)
            except DDCError as exc:
                log.warning("verify read failed on attempt %d: %s", attempt, exc)
                continue
            if current == expected:
                if attempt > 1:
                    log.info("VCP 0x%02X took %d attempts", code, attempt)
                return current
            last_seen = current
            log.warning(
                "VCP 0x%02X attempt %d: read 0x%02X, expected 0x%02X — retrying",
                code,
                attempt,
                current,
                expected,
            )

        raise VerifyError(
            f"VCP 0x{code:02X}: wrote 0x{value:02X}, expected to read "
            f"0x{expected:02X}, last saw "
            + (f"0x{last_seen:02X}" if last_seen is not None else "nothing")
            + f" after {self.settings.write_attempts} attempts"
        )


# --------------------------------------------------------------------- parsing


def _read_sysfs(path: str) -> str:
    with open(path) as handle:
        return handle.read().strip()


# ddcutil's terse output has three shapes:
#   VCP 10 C 60 100                 continuous: current, maximum
#   VCP 60 SNC x04                  simple non-continuous: one byte
#   VCP DF CNC xff xff x02 x01      complex non-continuous: mh ml sh sl
#
# For CNC features the meaning of the four bytes is per-feature. The low word
# (sh, sl) carries the payload for everything we surface — VCP version 2.1
# arrives as x02 x01 — so that is what gets returned, with the high word kept
# out of the way.
_TERSE_C = re.compile(r"^VCP\s+([0-9A-Fa-f]{2})\s+C\s+(\d+)\s+(\d+)", re.M)
_TERSE_SNC = re.compile(r"^VCP\s+([0-9A-Fa-f]{2})\s+SNC\s+x([0-9A-Fa-f]+)", re.M)
_TERSE_CNC = re.compile(
    r"^VCP\s+([0-9A-Fa-f]{2})\s+CNC\s+"
    r"x([0-9A-Fa-f]+)\s+x([0-9A-Fa-f]+)\s+x([0-9A-Fa-f]+)\s+x([0-9A-Fa-f]+)",
    re.M,
)


def _parse_terse_getvcp(out: str, code: int) -> tuple[int, int | None]:
    match = _TERSE_C.search(out)
    if match and int(match.group(1), 16) == code:
        return int(match.group(2)), int(match.group(3))

    match = _TERSE_SNC.search(out)
    if match and int(match.group(1), 16) == code:
        return int(match.group(2), 16), None

    match = _TERSE_CNC.search(out)
    if match and int(match.group(1), 16) == code:
        high = int(match.group(4), 16)
        low = int(match.group(5), 16)
        return (high << 8) | low, None

    raise DDCError(f"cannot parse getvcp output for 0x{code:02X}: {out.strip()!r}")


def _block_for_bus(out: str, bus: int) -> str | None:
    """Split ``ddcutil detect`` output per display and return ours.

    Blocks start at column 0 ("Display 1", "Invalid display", ...); everything
    indented below belongs to the preceding block.
    """
    blocks: list[list[str]] = []
    for line in out.splitlines():
        if line and not line[0].isspace():
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)

    needle = f"/dev/i2c-{bus}"
    for block in blocks:
        text = "\n".join(block)
        for line in block:
            if line.strip().startswith("I2C bus:") and line.strip().endswith(needle):
                return text
    return None


_DETECT_FIELDS = {
    "Mfg id": "mfg",
    "Model": "model",
    "Product code": "product_code",
    "VCP version": "vcp_version",
    "DRM connector": "connector",
}


def _parse_detect(out: str) -> DisplayInfo:
    found: dict[str, str] = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        field = _DETECT_FIELDS.get(key.strip())
        if field and field not in found:
            found[field] = value.strip()

    # "SAM - Samsung Electric Company" -> "SAM"
    if "mfg" in found:
        found["mfg"] = found["mfg"].split("-")[0].strip()
    # "28754  (0x7052)" -> "0x7052"
    if "product_code" in found:
        match = re.search(r"\(0x([0-9A-Fa-f]+)\)", found["product_code"])
        if match:
            found["product_code"] = f"0x{match.group(1).lower()}"

    return DisplayInfo(**found)
