"""Venue factory registry — snapshot loops this, not if/else chains."""

from __future__ import annotations

from typing import Any, Callable

from cryobookq.config import Settings, get_settings
from cryobookq.venues.binance import BinanceVenue
from cryobookq.venues.bybit import BybitVenue
from cryobookq.venues.coincall import CoincallVenue
from cryobookq.venues.deribit import DeribitVenue
from cryobookq.venues.okx import OkxVenue

KNOWN = ("deribit", "coincall", "bybit", "okx", "binance")


def make_venue(name: str, settings: Settings | None = None) -> Any:
    """Construct a venue adapter by name."""
    key = name.strip().lower()
    if key == "deribit":
        return DeribitVenue()
    if key == "coincall":
        return CoincallVenue(settings or get_settings())
    if key == "bybit":
        return BybitVenue()
    if key == "okx":
        return OkxVenue()
    if key == "binance":
        s = settings or get_settings()
        return BinanceVenue(rest_budget_s=s.binance_rest_budget_s)
    raise ValueError(f"unknown venue {name!r}")


FACTORIES: dict[str, Callable[..., Any]] = {n: (lambda n=n: make_venue(n)) for n in KNOWN}
