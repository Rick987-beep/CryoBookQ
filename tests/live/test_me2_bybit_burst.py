"""Live ME2: Bybit 100-symbol option book burst."""

from __future__ import annotations

import pytest

from cryobookq.capture.snapshot import fetch_btc_index
from cryobookq.pipeline.normalize import normalize_book
from cryobookq.venues.bybit import BybitVenue
from tests.live.conftest import require_network

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_me2_bybit_burst() -> None:
    require_network()
    venue = BybitVenue()
    inst = venue.list_instruments("BTC")
    assert len(inst) > 400
    assert all(i.key is not None and i.key.underlying == "BTC" for i in inst)
    symbols = [i.venue_symbol for i in inst[:100]]
    books, stats = await venue.burst_books(symbols, depth=5, duration_s=12.0)
    assert stats.coverage >= 0.50, f"Bybit coverage {stats.coverage:.2%} errors={stats.subscribe_errors[:3]}"
    assert any(b.two_sided for b in books.values())
    sample = next(iter(books.values()))
    assert len(sample.bid_px) == 5
    assert sample.venue == "bybit"
    index = fetch_btc_index()
    two = next(b for b in books.values() if b.two_sided)
    row = normalize_book(two, index_px=index)
    assert row["price_unit"] == "USD"
    if two.bid_px[0] > 0:
        assert row["bid_px_1"] > 10
