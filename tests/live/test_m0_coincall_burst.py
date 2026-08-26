"""Live M0: Coincall full-chain orderBook burst coverage."""

from __future__ import annotations

import pytest

from cryobookq.config import get_settings
from cryobookq.venues.coincall import CoincallVenue
from tests.live.conftest import require_coincall_creds, require_network

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_m0_coincall_burst_coverage() -> None:
    require_network()
    require_coincall_creds()
    settings = get_settings()
    venue = CoincallVenue(settings)
    instruments = venue.list_instruments(settings.underlying)
    assert len(instruments) > 400
    symbols = [i.venue_symbol for i in instruments]
    books, stats = await venue.burst_books(symbols, depth=settings.depth, duration_s=15.0)
    assert stats.coverage >= 0.80, (
        f"Coincall coverage {stats.coverage:.2%} < 80%; "
        f"errors={stats.subscribe_errors[:5]} notes={stats.notes}"
    )
    assert any(len(b.bid_px) == 5 for b in books.values())
    # Truncation: no more than 5 levels stored
    for b in list(books.values())[:20]:
        assert len(b.ask_px) == 5
