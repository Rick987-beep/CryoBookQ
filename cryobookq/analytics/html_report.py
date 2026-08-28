"""Compatibility shim — implementation lives in ``cryobookq.analytics.report``."""

from __future__ import annotations

from cryobookq.analytics.report import (
    build_executive_summary,
    render_scorecard_html,
    scorecard_from_dict,
    write_scorecard_html,
)

# Back-compat alias used in early drafts / external notes.
build_executive_reading = build_executive_summary

__all__ = [
    "build_executive_reading",
    "build_executive_summary",
    "render_scorecard_html",
    "scorecard_from_dict",
    "write_scorecard_html",
]
