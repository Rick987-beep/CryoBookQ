"""Display labels for venues, tenors, and deltas."""

from __future__ import annotations

VENUE_LABELS = {
    "deribit": "Deribit",
    "coincall": "Coincall",
}

TENOR_LABELS = {
    "short": "Short-dated",
    "mid": "Mid-dated (weeklies)",
    "far": "Far-dated",
}

TENOR_BLURBS = {
    "short": "Targets ~1–2 days to expiry (nearest listed).",
    "mid": "Average of landmarks near 7 / 14 / 21 DTE.",
    "far": "Average of landmarks near 60 / 90 / 120 DTE.",
}

DELTA_LABELS = {
    "50d": "50Δ (ATM)",
    "25d": "25Δ",
    "7p5d": "7.5Δ",
    "2p5d": "2.5Δ (wings)",
}


def venue_name(v: str) -> str:
    return VENUE_LABELS.get(v, v.replace("_", " ").title())
