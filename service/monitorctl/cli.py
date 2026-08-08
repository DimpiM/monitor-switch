"""Command line interface — the layer that needs no HTTP server to be useful.

``probe`` is the interesting one. Finding out which values your monitor accepts
means writing values and seeing what happens, and a wrong guess can leave the
monitor showing an input with no signal, which wedges its DDC engine. So every
probe write is provisional: it reverts on its own unless you confirm it in time.
That is the same bargain a display-resolution dialog offers, for the same reason.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time

from .app import build_runtime
from .config import Config
from .controller import GuardRejected, MonitorController
from .ddc import DDCError
from .features import SELECT

log = logging.getLogger(__name__)

PROBE_REVERT_SECONDS = 12


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="monitorctl",
        description="Control a DDC/CI monitor from the command line.",
    )
    parser.add_argument("-c", "--config", help="path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("detect", help="show the monitor and the selected profile")
    sub.add_parser("features", help="list available features")

    p_state = sub.add_parser("state", help="read every feature")
    p_state.add_argument("--json", action="store_true")

    p_get = sub.add_parser("get", help="read one feature")
    p_get.add_argument("feature")

    p_set = sub.add_parser("set", help="write one feature")
    p_set.add_argument("feature")
    p_set.add_argument("value")

    p_input = sub.add_parser("input", help="switch input source")
    p_input.add_argument("target", nargs="?", help="option id; omit to read")

    sub.add_parser("toggle", help="switch to the next configured input")

    p_probe = sub.add_parser(
        "probe", help="discover which values a feature really accepts"
    )
    p_probe.add_argument("--feature", default="input_source")
    p_probe.add_argument(
        "--values",
        help="comma-separated values to try, e.g. 0x0f,0x10,0x11 "
        "(default: the MCCS input source range)",
    )
    p_probe.add_argument(
        "--revert-after",
        type=int,
        default=PROBE_REVERT_SECONDS,
        help="seconds before an unconfirmed value is reverted",
    )

    p_bench = sub.add_parser("bench", help="switch back and forth to measure reliability")
    p_bench.add_argument("--rounds", type=int, default=10)

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    config = Config.load(args.config)
    try:
        runtime = build_runtime(config)
    except DDCError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    controller = runtime.controller

    try:
        return _dispatch(args, runtime, controller)
    except (DDCError, ValueError, KeyError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(args, runtime, controller: MonitorController) -> int:
    if args.command == "detect":
        info = runtime.display
        print(f"Manufacturer : {info.mfg}")
        print(f"Model        : {info.model}")
        print(f"Product code : {info.product_code}")
        print(f"VCP version  : {info.vcp_version}")
        print(f"Connector    : {info.connector}")
        print(f"I2C bus      : {runtime.ddc.bus}")
        print(f"Profile      : {runtime.profile_name}")
        print(f"Local video  : {'active' if runtime.ddc.local_video_active() else 'INACTIVE'}")
        return 0

    if args.command == "features":
        for feature in sorted(controller.features, key=lambda f: f.vcp):
            flags = [feature.category]
            if feature.readonly:
                flags.append("read-only")
            if feature.fast_poll:
                flags.append("fast-poll")
            if feature.static:
                flags.append("static")
            print(f"0x{feature.vcp:02X}  {feature.name:<20} {feature.type:<11} "
                  f"{feature.label:<24} [{', '.join(flags)}]")
            for option in feature.options:
                guard = f"  guard={option.guard}" if option.guard else ""
                print(f"          {option.id:<16} write=0x{option.write:02X} "
                      f"read=0x{option.read:02X}  {option.label}{guard}")
        return 0

    if args.command == "state":
        controller.refresh()
        state = controller.state()
        if args.json:
            print(json.dumps(state, indent=2))
        else:
            for name, item in state.items():
                value = item["error"] or item["display"]
                print(f"{name:<20} {value}")
        return 0

    if args.command == "get":
        state = controller.get(args.feature)
        print(state.error or state.display)
        return 1 if state.error else 0

    if args.command == "set":
        state = controller.set(args.feature, args.value)
        print(f"{args.feature} = {state.display}")
        return 0

    if args.command == "input":
        if not args.target:
            print(controller.get("input_source").display)
            return 0
        state = controller.switch_input(args.target)
        print(f"input_source = {state.display}")
        return 0

    if args.command == "toggle":
        state = controller.toggle()
        print(f"input_source = {state.display}")
        return 0

    if args.command == "probe":
        return _probe(controller, args)

    if args.command == "bench":
        return _bench(controller, args.rounds)

    raise ValueError(f"unhandled command {args.command!r}")


# --------------------------------------------------------------------- probe


def _probe(controller: MonitorController, args) -> int:
    feature = controller.features.get(args.feature)
    if feature is None:
        raise KeyError(f"unknown feature {args.feature!r}")
    if feature.type != SELECT:
        raise ValueError("probe only makes sense for select features")

    if args.values:
        candidates = [int(v.strip(), 0) for v in args.values.split(",")]
    else:
        candidates = list(range(0x01, 0x13))  # MCCS input source range

    before = controller.get(feature.name)
    if before.raw is None:
        raise DDCError("cannot read the current value; refusing to probe blind")

    print(f"Probing {feature.name} (VCP 0x{feature.vcp:02X})")
    print(f"Current value reads back as 0x{before.raw:02X}.")
    print()
    print("Each value is written, then reverted automatically after "
          f"{args.revert_after}s unless you confirm it.")
    print("If the screen goes black, just wait — it comes back on its own.")
    print()

    results: list[tuple[int, int | None, bool]] = []
    for value in candidates:
        print(f"--- writing 0x{value:02X} ...", flush=True)
        try:
            controller.ddc.set_vcp(feature.vcp, value, verify_as=value)
            confirmed_raw: int | None = value
        except DDCError:
            # The write may still have worked while reading back something else,
            # which is the entire reason this project has profiles.
            try:
                confirmed_raw, _ = controller.ddc.get_vcp(feature.vcp)
            except DDCError as exc:
                print(f"    unreadable after write: {exc}")
                results.append((value, None, False))
                continue

        changed = confirmed_raw != before.raw
        marker = "CHANGED" if changed else "no effect"
        print(f"    reads back 0x{confirmed_raw:02X}  ({marker})")

        keep = False
        if changed:
            keep = _confirm_or_revert(args.revert_after)
            if not keep:
                print("    reverting ...")
                try:
                    controller.ddc.set_vcp(
                        feature.vcp, _write_for(feature, before.raw) or before.raw,
                        verify_as=before.raw,
                    )
                except DDCError as exc:
                    print(f"    !! revert failed: {exc}", file=sys.stderr)
                    print("    !! recover via the monitor's OSD before continuing.",
                          file=sys.stderr)
                    return 3
        results.append((value, confirmed_raw, changed))

    print()
    print("Summary — put the CHANGED rows into a profile:")
    print()
    print("  options:")
    for value, read_back, changed in results:
        if changed and read_back is not None:
            print(f"    - {{ id: input{value:02x}, label: 'Input 0x{value:02X}', "
                  f"write: 0x{value:02x}, read: 0x{read_back:02x} }}")
    print()
    print("See docs/profiles.md for where to put this.")
    return 0


def _write_for(feature, read_value: int) -> int | None:
    option = feature.option_by_read(read_value)
    return option.write if option else None


def _confirm_or_revert(seconds: int) -> bool:
    """Wait for confirmation, but never forever.

    If the user cannot see the prompt — because this write moved the display to
    an input they are not looking at — nobody is coming to answer. The timeout is
    the safety net, so it must not be defeatable by a hung read.
    """
    answer: list[str] = []

    def reader() -> None:
        try:
            answer.append(input(f"    keep this value? [y/N, {seconds}s] ").strip())
        except (EOFError, KeyboardInterrupt):
            answer.append("")

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout=seconds)
    if thread.is_alive():
        print("\n    no confirmation — reverting")
        return False
    return bool(answer) and answer[0].lower().startswith("y")


# --------------------------------------------------------------------- bench


def _bench(controller: MonitorController, rounds: int) -> int:
    options = controller.toggle_between or [
        o.id for o in controller.input_feature.options if o.guard is None
    ]
    if len(options) < 2:
        raise ValueError("need at least two unguarded inputs to benchmark")

    a, b = options[0], options[1]
    start_state = controller.get("input_source").value
    failures = 0
    durations: list[float] = []

    print(f"Switching {a} <-> {b}, {rounds} rounds")
    for index in range(1, rounds + 1):
        for target in (a, b):
            began = time.monotonic()
            try:
                controller.switch_input(target)
                elapsed = time.monotonic() - began
                durations.append(elapsed)
                print(f"  {index:>3}  -> {target:<10} {elapsed:5.2f}s")
            except (DDCError, GuardRejected) as exc:
                failures += 1
                print(f"  {index:>3}  -> {target:<10} FAILED: {exc}")

    if start_state and start_state in options:
        controller.switch_input(start_state)

    print()
    print(f"failures: {failures} / {rounds * 2}")
    if durations:
        print(f"per switch: min {min(durations):.2f}s  "
              f"avg {sum(durations) / len(durations):.2f}s  "
              f"max {max(durations):.2f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
