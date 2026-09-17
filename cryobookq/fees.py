"""Standard-tier BTC options trading fees (retail / VIP 0).

Pinned schedules for the hub glance strip. Not a live fee API — update
``STANDARD_TIER`` when an exchange publishes a new retail table.

Fee per fill (1 BTC of option size, USD):

    min(taker_rate × index, premium_cap × option_premium)

Rates are of the **underlying index**, capped as a fraction of **option premium**,
which is how Deribit, Coincall, and Bybit document the charge.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fraction of underlying index charged as taker (0.0003 = 3 bps).
# premium_cap is a fraction of the option premium (0.125 = 12.5%).


@dataclass(frozen=True)
class StandardOptionsFee:
    venue: str
    taker_rate: float
    premium_cap: float
    as_of: str
    source: str


# Retail / standard tier only. Maker rates and VIP ladders are out of scope.
STANDARD_TIER: dict[str, StandardOptionsFee] = {
    "deribit": StandardOptionsFee(
        venue="deribit",
        taker_rate=0.0003,
        premium_cap=0.125,
        as_of="2026-08-01",
        source="https://support.deribit.com/hc/en-us/articles/25944746248989-Fees",
    ),
    "coincall": StandardOptionsFee(
        venue="coincall",
        taker_rate=0.0003,
        premium_cap=0.125,
        as_of="2026-09",
        source="https://support.coincall.com/hc/en-us/articles/16530143725849-Trading-Fees",
    ),
    "bybit": StandardOptionsFee(
        venue="bybit",
        taker_rate=0.0003,
        premium_cap=0.07,
        as_of="2026-08-19",
        source="https://www.bybit.com/en/help-center/article/Bybit-Option-Fees-Explained/",
    ),
    "okx": StandardOptionsFee(
        venue="okx",
        taker_rate=0.0003,
        premium_cap=0.125,
        as_of="2026-09",
        source="OKX regular-tier options taker 0.03% of underlying; 12.5% premium cap (Deribit-style).",
    ),
    "binance": StandardOptionsFee(
        venue="binance",
        taker_rate=0.0003,
        premium_cap=0.10,
        as_of="2026-09",
        source="Binance USDT-M options retail: 0.03% of underlying, 10% of premium cap.",
    ),
}


def taker_fee_usd(
    venue: str,
    *,
    index_usd: float,
    premium_usd: float,
    size_btc: float = 1.0,
) -> float | None:
    """USD taker fee for one fill. ``None`` if venue unknown or inputs invalid."""
    sched = STANDARD_TIER.get(venue)
    if sched is None:
        return None
    if index_usd <= 0 or premium_usd < 0 or size_btc <= 0:
        return None
    uncapped = sched.taker_rate * index_usd * size_btc
    capped = sched.premium_cap * premium_usd * size_btc
    return min(uncapped, capped)
