"""Flask public dashboard — multi-venue scorecard at /bookq/."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template

from cryobookq.config import get_settings
from cryobookq.hub.context import build_hub_context
from cryobookq.hub.middleware import ScriptNameMiddleware

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_STATIC = Path(__file__).resolve().parent / "static"


def create_app(data_dir: Path | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_TEMPLATES),
        static_folder=str(_STATIC),
        static_url_path="/static",
    )
    settings = get_settings()
    root = Path(data_dir) if data_dir is not None else settings.data_dir

    if settings.hub_mount:
        app.wsgi_app = ScriptNameMiddleware(app.wsgi_app, settings.hub_mount)

    def _context(*, include_health: bool = True):
        if include_health:
            return build_hub_context(root, settings=settings)
        return build_hub_context(root, settings=settings, health={})

    @app.get("/health")
    def health():
        """Hub health + passthrough of daemon state when reachable."""
        ctx = _context(include_health=True)
        h = dict(ctx["health"])
        h["hub_data_dir"] = str(root)
        h["hub_snapshot_n"] = settings.hub_snapshot_n
        return jsonify(h)

    @app.get("/")
    def index():
        ctx = _context(include_health=False)
        ctx.pop("health", None)
        ctx.pop("daemon_status", None)
        return render_template("index.html", **ctx)

    @app.get("/api/status")
    def api_status():
        ctx = _context(include_health=True)
        return jsonify(
            {
                "daemon_status": ctx["daemon_status"],
                "has_data": ctx["has_data"],
                "meta": ctx.get("meta"),
                "leader": ctx.get("leader"),
                "ranked_venues": ctx.get("ranked_venues"),
            }
        )

    return app


def main() -> None:
    settings = get_settings()
    port = int(os.getenv("BOOKQ_HUB_PORT", str(settings.hub_port)))
    app = create_app()
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
