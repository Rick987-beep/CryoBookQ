"""Unit: hung venue must not block peers."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from cryobookq.config import Settings
from cryobookq.types import BookL5, Instrument, OptionKey
from cryobookq.venues._util import BurstStats


class _HangVenue:
    name = "bybit"

    def list_instruments(self, underlying: str) -> list[Instrument]:
        key = OptionKey("BTC", 1_800_000_000_000, 80_000.0, True)
        return [Instrument("bybit", "BTC-HANG", key)]

    async def burst_books(self, symbols, depth=5, deadline=None, duration_s=None):
        await asyncio.sleep(3600)
        return {}, BurstStats("bybit", 1, 0, 0.0, 0.0)


class _HubVenue:
    name = "deribit"

    def list_instruments(self, underlying: str) -> list[Instrument]:
        key = OptionKey("BTC", 1_800_000_000_000, 80_000.0, True)
        return [Instrument("deribit", "BTC-1JAN30-80000-C", key)]

    async def burst_books(self, symbols, depth=5, deadline=None, duration_s=None):
        key = OptionKey("BTC", 1_800_000_000_000, 80_000.0, True)
        book = BookL5.empty("deribit", symbols[0], key)
        book.bid_px[0] = 0.02
        book.ask_px[0] = 0.021
        book.bid_sz[0] = 1.0
        book.ask_sz[0] = 1.0
        return {symbols[0]: book}, BurstStats("deribit", 1, 1, 0.05, 1.0)


@pytest.mark.asyncio
async def test_hanging_venue_does_not_block_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cryobookq.capture.snapshot import run_snapshot

    def factory(name: str, settings=None):
        if name == "bybit":
            return _HangVenue()
        return _HubVenue()

    monkeypatch.setattr("cryobookq.capture.snapshot.make_venue", factory)
    monkeypatch.setattr("cryobookq.capture.snapshot.fetch_btc_index", lambda: 80_000.0)

    settings = Settings(data_dir=tmp_path, burst_timeout_s=0.4)
    t0 = time.perf_counter()
    result = await run_snapshot(
        ["deribit", "bybit"],
        settings=settings,
        duration_s=0.1,
        write=True,
        force_write=True,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"hang leaked, elapsed={elapsed:.2f}s"
    assert "bybit" in (result.quality.venue_errors if result.quality else {})
    assert any(r["venue"] == "deribit" for r in result.raw_rows)
