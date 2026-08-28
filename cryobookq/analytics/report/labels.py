"""Display labels for venues, tenors, and deltas."""

from __future__ import annotations

VENUE_LABELS = {
    "deribit": "Deribit",
    "coincall": "Coincall",
    "bybit": "Bybit",
    "okx": "OKX",
    "binance": "Binance",
}

# Left-border accents on overall cards (CSS `data-venue`).
VENUE_COLORS = {
    "deribit": "#1f6feb",
    "coincall": "#c9a227",
    "bybit": "#f7a600",
    "okx": "#000000",
    "binance": "#f0b90b",
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
