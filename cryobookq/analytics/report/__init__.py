"""Modular Comparison Scorecard HTML report.

Layout: ``templates/`` + ``snippets/`` + ``styles.css`` + ``copy.toml``.
Public API mirrors the former ``html_report`` module.
"""

from __future__ import annotations

from cryobookq.analytics.report.context import scorecard_from_dict
from cryobookq.analytics.report.narrative import build_executive_summary
from cryobookq.analytics.report.render import render_scorecard_html, write_scorecard_html

__all__ = [
    "build_executive_summary",
    "render_scorecard_html",
    "scorecard_from_dict",
    "write_scorecard_html",
]
