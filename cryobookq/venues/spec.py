"""Per-venue unit conversion spec (price currency + size → BTC).

Adapters emit native books. ``normalize_book`` is the only conversion site;
it reads a ``VenueSpec`` (or ``BookL5.size_to_btc`` when set).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cryobookq.types import Instrument

PriceCcy = Literal["BTC", "USD"]


@dataclass(frozen=True, slots=True)
class VenueSpec:
    """How to turn a venue-native book into USD prices + BTC sizes."""

    name: str
    price_ccy: PriceCcy
    size_to_btc: float


SPECS: dict[str, VenueSpec] = {
    "deribit": VenueSpec("deribit", "BTC", 1.0),
    "coincall": VenueSpec("coincall", "USD", 1.0),
    "bybit": VenueSpec("bybit", "USD", 1.0),
    "binance": VenueSpec("binance", "USD", 1.0),
    "okx": VenueSpec("okx", "BTC", 0.01),
}


def spec_for(venue: str) -> VenueSpec:
    """Return the default spec for *venue*; unknown names raise ``KeyError``."""
    return SPECS[venue]


def spec_from_instrument(inst: Instrument) -> VenueSpec:
    """Default spec, with OKX ``ctVal × ctMult`` from ``Instrument.raw`` when present."""
    base = SPECS.get(inst.venue) or VenueSpec(inst.venue, "USD", 1.0)
    if inst.venue != "okx":
        return base
    raw = inst.raw or {}
    try:
        ct_val = float(raw.get("ctVal") or 1.0)
        ct_mult = float(raw.get("ctMult") or 0.01)
    except (TypeError, ValueError):
        return base
    size_to_btc = ct_val * ct_mult
    if size_to_btc <= 0:
        return base
    return VenueSpec(name="okx", price_ccy="BTC", size_to_btc=size_to_btc)
