"""Flask status hub — multi-venue scores, capture quality, daemon health."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template

from cryobookq.config import get_settings
from cryobookq.hub.context import build_hub_context, fetch_daemon_health

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def create_app(data_dir: Path | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(_TEMPLATES))
    settings = get_settings()
    root = Path(data_dir) if data_dir is not None else settings.data_dir

    def _context():
        return build_hub_context(root, settings=settings)

    @app.get("/health")
    def health():
        """Hub health + passthrough of daemon state when reachable."""
        ctx = _context()
        h = dict(ctx["health"])
        h["hub_data_dir"] = str(root)
        return jsonify(h)

    @app.get("/")
    def index():
        return render_template("index.html", **_context())

    @app.get("/api/status")
    def api_status():
        ctx = _context()
        return jsonify(
            {
                "health": ctx["health"],
                "venues": ctx["venue_rows"],
                "scorecard_note": ctx["scorecard_note"],
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
