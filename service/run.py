#!/usr/bin/env python3
"""Entry point: start the poller, the optional MQTT bridge, and the HTTP server."""

from __future__ import annotations

import logging
import signal
import sys
import threading

from waitress import serve

from monitorctl.api import create_app
from monitorctl.app import Poller, build_runtime
from monitorctl.config import Config
from monitorctl.ddc import DDCError

log = logging.getLogger("monitorctl")


def main() -> int:
    config = Config.load()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        runtime = build_runtime(config)
    except DDCError as exc:
        # Exit non-zero so systemd's Restart=always keeps trying. A monitor that
        # is merely switched off right now will answer on a later attempt.
        log.error("startup failed: %s", exc)
        return 1

    poller = Poller(runtime)
    poller.start()

    bridge = None
    if config.mqtt.enabled:
        try:
            from monitorctl.mqtt import MQTTBridge

            bridge = MQTTBridge(runtime)
            bridge.start()
        except Exception:
            # MQTT is an integration, not a dependency. Losing it must not take
            # the HTTP API and the web UI down with it.
            log.exception("MQTT bridge failed to start — continuing without it")
            bridge = None

    stopping = threading.Event()

    def shutdown(signum, _frame):
        if stopping.is_set():
            return
        stopping.set()
        log.info("signal %s received, shutting down", signum)
        poller.stop()
        if bridge:
            bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    app = create_app(runtime)
    log.info("listening on http://%s:%d", config.host, config.port)
    # threads=4: DDC access is serialised by a lock anyway, but SSE connections
    # occupy a thread each, so a couple of spare ones keep the UI responsive.
    serve(app, host=config.host, port=config.port, threads=4, channel_timeout=120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
