"""Live M0: Deribit full-chain book burst coverage."""

from __future__ import annotations

import pytest

from cryobookq.config import get_settings
from cryobookq.venues.deribit import DeribitVenue
from tests.live.conftest import require_network

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_m0_deribit_burst_coverage() -> None:
    require_network()
    settings = get_settings()
    venue = DeribitVenue()
    instruments = venue.list_instruments(settings.underlying)
    assert len(instruments) > 500
    symbols = [i.venue_symbol for i in instruments]
    books, stats = await venue.burst_books(symbols, depth=settings.depth, duration_s=15.0)
    assert stats.coverage >= 0.90, (
        f"Deribit coverage {stats.coverage:.2%} < 90%; "
        f"errors={stats.subscribe_errors[:3]} notes={stats.notes}"
    )
    assert len(books) == stats.n_with_update
    # At least one two-sided book near the money-ish (any two-sided)
    assert any(b.two_sided for b in books.values())
    sample = next(iter(books.values()))
    assert len(sample.bid_px) == 5
    assert sample.venue == "deribit"
