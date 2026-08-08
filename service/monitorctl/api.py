"""HTTP API and static file serving.

Every endpoint that writes waits for the monitor to confirm before answering.
That makes a switch take around 1.7 seconds, which is slow for an HTTP call but
honest: the alternative is acknowledging a write that may never have landed.
Clients should allow at least 10 seconds.
"""

from __future__ import annotations

import logging
import os

from flask import Flask, Response, jsonify, request, send_from_directory

from .app import Runtime
from .controller import FeatureNotFound, GuardRejected, ReadOnlyFeature
from .ddc import DDCError, VerifyError
from .events import sse_stream
from .features import SELECT

log = logging.getLogger(__name__)

WEB_ROOT = os.path.join(os.path.dirname(__file__), "web")


def create_app(runtime: Runtime) -> Flask:
    app = Flask(__name__, static_folder=None)
    controller = runtime.controller

    # ---------------------------------------------------------------- errors

    @app.errorhandler(FeatureNotFound)
    def _unknown_feature(exc):
        return jsonify(error="unknown_feature", message=str(exc).strip("'")), 404

    @app.errorhandler(ReadOnlyFeature)
    def _read_only(exc):
        return jsonify(error="read_only", message=str(exc)), 405

    @app.errorhandler(GuardRejected)
    def _guard(exc):
        # 409: the request is well-formed, but the world is not in a state where
        # honouring it would be safe.
        return jsonify(error="guard_rejected", message=str(exc)), 409

    @app.errorhandler(VerifyError)
    def _verify(exc):
        return jsonify(error="verify_failed", message=str(exc)), 502

    @app.errorhandler(DDCError)
    def _ddc(exc):
        return jsonify(error="ddc_error", message=str(exc)), 502

    @app.errorhandler(ValueError)
    def _value(exc):
        return jsonify(error="invalid_value", message=str(exc)), 400

    # ------------------------------------------------------------------ meta

    @app.get("/healthz")
    def healthz():
        return jsonify(
            status="ok",
            version=_version(),
            bus=runtime.ddc.bus,
            profile=runtime.profile_name,
            features=len(controller.features),
            subscribers=runtime.events.subscriber_count,
        )

    @app.get("/api/display")
    def display():
        info = runtime.display
        return jsonify(
            manufacturer=info.mfg,
            model=info.model,
            product_code=info.product_code,
            vcp_version=info.vcp_version,
            connector=info.connector,
            bus=runtime.ddc.bus,
            profile=runtime.profile_name,
            local_video=runtime.ddc.local_video_active(),
        )

    @app.get("/api/features")
    def features():
        """The registry. The frontend builds its entire UI from this."""
        return jsonify(
            features=[
                {
                    "name": f.name,
                    "label": f.label or f.name,
                    "vcp": f"0x{f.vcp:02X}",
                    "type": f.type,
                    "category": f.category,
                    "readonly": f.readonly,
                    "unit": f.unit,
                    "min": f.min,
                    "max": f.max,
                    "options": [
                        {"id": o.id, "label": o.label, "guard": o.guard}
                        for o in f.options
                    ]
                    if f.type == SELECT
                    else None,
                }
                for f in sorted(controller.features, key=lambda f: f.vcp)
            ],
            toggle_between=controller.toggle_between,
        )

    # ----------------------------------------------------------------- state

    @app.get("/api/state")
    def state():
        if request.args.get("refresh") == "1":
            controller.refresh()
        return jsonify(state=controller.state())

    @app.get("/api/feature/<name>")
    def get_feature(name: str):
        return jsonify(controller.get(name).to_dict())

    @app.post("/api/feature/<name>")
    def set_feature(name: str):
        payload = request.get_json(silent=True) or {}
        if "value" not in payload:
            return jsonify(error="invalid_value", message="body needs a 'value'"), 400
        return jsonify(controller.set(name, payload["value"]).to_dict())

    # ----------------------------------------------------------------- input

    @app.get("/api/input")
    def get_input():
        return jsonify(controller.get("input_source").to_dict())

    @app.post("/api/input/<target>")
    def set_input(target: str):
        return jsonify(controller.switch_input(target).to_dict())

    @app.post("/api/toggle")
    def toggle():
        return jsonify(controller.toggle().to_dict())

    # ---------------------------------------------------------------- events

    @app.get("/api/events")
    def events():
        response = Response(
            sse_stream(runtime.events), mimetype="text/event-stream"
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"  # defeat proxy buffering
        return response

    # ------------------------------------------------------------------- web

    @app.get("/")
    def index():
        if not os.path.exists(os.path.join(WEB_ROOT, "index.html")):
            return (
                "<h1>monitorctl</h1><p>The API is running, but no web UI is "
                "installed. See the project README.</p>",
                200,
                {"Content-Type": "text/html"},
            )
        return send_from_directory(WEB_ROOT, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        full = os.path.join(WEB_ROOT, filename)
        if os.path.isfile(full):
            return send_from_directory(WEB_ROOT, filename)
        # Unknown path: hand it to the single-page app rather than 404ing, so
        # deep links keep working.
        if os.path.exists(os.path.join(WEB_ROOT, "index.html")):
            return send_from_directory(WEB_ROOT, "index.html")
        return jsonify(error="not_found"), 404

    return app


def _version() -> str:
    from . import __version__

    return __version__
