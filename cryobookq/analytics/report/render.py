"""Render Comparison Scorecard HTML from templates + context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cryobookq.analytics.report.context import build_report_context, scorecard_from_dict
from cryobookq.analytics.report.engine import render_template
from cryobookq.analytics.scorecard import ScorecardResult


def render_scorecard_html(
    card: ScorecardResult | dict[str, Any],
    *,
    title: str = "Comparison Scorecard",
    subtitle: str | None = None,
    reading: str | None = None,
) -> str:
    """Return a full HTML document (inline CSS, no external assets).

    ``reading`` is kept as a kwarg alias for the Executive Summary override
    (historical CLI / callers).
    """
    if isinstance(card, dict):
        card = scorecard_from_dict(card)
    ctx = build_report_context(
        card,
        title=title,
        subtitle=subtitle,
        executive_summary=reading,
    )
    return render_template("scorecard.html", ctx)


def write_scorecard_html(
    card: ScorecardResult | dict[str, Any],
    path: Path | str,
    **kwargs: Any,
) -> Path:
    """Render and write HTML; return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_scorecard_html(card, **kwargs), encoding="utf-8")
    return path
