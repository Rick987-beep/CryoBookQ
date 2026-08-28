"""Formatting helpers for scorecard report context."""

from __future__ import annotations

import html
import math
from datetime import UTC, datetime


class SafeHTML(str):
    """Mark a string as already escaped / trusted HTML for the template engine."""


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def fmt_pct(x: float | None, digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:.{digits}f}%"


def fmt_num(x: float | None, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:.{digits}f}"


def fmt_depth_k(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x / 1000.0:.0f}k"


def ts_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
