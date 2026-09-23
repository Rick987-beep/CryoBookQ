"""Live: full Bullish BTC option chain list and L2 burst. Public data only."""

from __future__ import annotations

import time

import pytest

from cryobookq.venues.bullish import BullishVenue
from tests.live.conftest import require_network

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_bullish_full_chain_burst() -> None:
    require_network()
    venue = BullishVenue()
    inst = venue.list_instruments("BTC")
    assert len(inst) >= 1000
    assert all(i.key is not None and i.key.underlying == "BTC" for i in inst)
    assert all(i.venue_symbol.count("-") == 4 for i in inst)
    assert venue.list_instruments("ETH") == []

    symbols = [i.venue_symbol for i in inst]
    books, stats = await venue.burst_books(symbols, depth=5, duration_s=30.0)
    assert stats.coverage >= 0.90, (
        f"coverage {stats.coverage:.2%} n={stats.n_with_update}/{stats.n_instruments} "
        f"errors={stats.subscribe_errors[:3]} notes={stats.notes}"
    )
    assert stats.duration_s <= 40.0
    two = [b for b in books.values() if b.two_sided]
    assert two, "expected at least one two-sided Bullish book"
    sample = two[0]
    assert sample.venue == "bullish"
    assert sample.size_to_btc == pytest.approx(1.0)
    for px in (*sample.bid_px, *sample.ask_px):
        if px > 0:
            assert abs(px / 10 - round(px / 10)) < 1e-6
    assert sample.ts_exchange_ms is not None
    assert abs(sample.ts_exchange_ms - time.time() * 1000) < 5 * 60 * 1000
