"""Minimal Flask + htmx hub for last snapshot scores / health."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template_string

from cryobookq.analytics import load_scores, summarize_snapshot, who_wins
from cryobookq.config import get_settings
from cryobookq.daemon.health import HEALTH

PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>CryoBookQ</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; background: #0f1419; color: #e7ecf1; }
    h1 { font-weight: 600; letter-spacing: 0.02em; }
    .muted { color: #8b9aab; }
    table { border-collapse: collapse; margin: 1rem 0; }
    th, td { border-bottom: 1px solid #2a3441; padding: 0.4rem 0.8rem; text-align: left; }
    a { color: #7db7ff; }
    .ok { color: #6dcaa4; } .bad { color: #e07a7a; }
  </style>
</head>
<body>
  <h1>CryoBookQ</h1>
  <p class="muted">Deribit vs Coincall option book quality</p>
  <p>Health: <span class="{{ 'ok' if health.last_ok else 'bad' }}">{{ 'ok' if health.last_ok else 'degraded' }}</span>
     · snapshots {{ health.snapshots_today }} · writes {{ health.writes_today }}
     · gaps {{ health.gaps_today }} · incomplete {{ health.incomplete_today }}
     · <a href="/health">/health</a></p>
  {% if summary.n_matched %}
  <h2>Last loaded scores</h2>
  <p>matched {{ summary.n_matched }} / {{ summary.n_rows }}
     (rate {{ '%.1f'|format(100*summary.match_rate) }}%)</p>
  <h3>Composite winners</h3>
  <table>
    <tr><th>Venue</th><th>Wins</th><th>Rate</th></tr>
    {% for k,v in summary.winner_composite.items() %}
    <tr><td>{{ k }}</td><td>{{ v }}</td>
        <td>{{ '%.1f'|format(100*summary.winner_composite_rate.get(k,0)) }}%</td></tr>
    {% endfor %}
  </table>
  <h3>By DTE (composite win rate)</h3>
  <table>
    <tr><th>DTE</th><th>Deribit</th><th>Coincall</th></tr>
    {% for bucket, rates in summary.by_dte_composite.items() %}
    <tr>
      <td>{{ bucket }}</td>
      <td>{{ '%.1f'|format(100*rates.get('deribit',0)) }}%</td>
      <td>{{ '%.1f'|format(100*rates.get('coincall',0)) }}%</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p class="muted">No pair_scores yet — run <code>python -m cryobookq.daemon --once</code>.</p>
  {% endif %}
</body>
</html>
"""


def create_app(data_dir: Path | None = None) -> Flask:
    app = Flask(__name__)
    settings = get_settings()
    root = Path(data_dir) if data_dir is not None else settings.data_dir

    @app.get("/health")
    def health():
        h = HEALTH.as_dict()
        h["data_dir"] = str(root)
        return jsonify(h)

    @app.get("/")
    def index():
        df = load_scores(data_dir=root)
        if not df.empty and "ts" in df.columns:
            latest = df[df["ts"] == df["ts"].max()]
        else:
            latest = df
        summary = summarize_snapshot(latest)
        return render_template_string(PAGE, health=HEALTH, summary=summary)

    @app.get("/api/summary")
    def api_summary():
        df = load_scores(data_dir=root)
        if not df.empty and "ts" in df.columns:
            df = df[df["ts"] == df["ts"].max()]
        return jsonify(summarize_snapshot(df))

    @app.get("/api/who_wins")
    def api_who_wins():
        from flask import request

        df = load_scores(data_dir=root)
        session = request.args.get("session")
        dte = request.args.get("dte_bucket")
        counts = who_wins(df, session=session, dte_bucket=dte)
        return jsonify({"counts": counts.to_dict(), "win_rate": counts.attrs.get("win_rate", {})})

    return app


def main() -> None:
    settings = get_settings()
    port = int(os.getenv("BOOKQ_HUB_PORT", str(settings.hub_port)))
    app = create_app()
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
