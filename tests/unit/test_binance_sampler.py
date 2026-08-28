"""Unit: Binance slow-sampler helpers (chunk, pacer, weight, ticker)."""

from __future__ import annotations

import time

import pytest

from cryobookq.venues.binance import (
    MAX_STREAMS_PER_CONN,
    SUBSCRIBE_PER_SEC,
    SubscribePacer,
    TICKER_EPSILON_SZ,
    chunk_symbols,
    ticker_tob_sides,
    used_weight_from_headers,
)


def test_chunk_symbols_respects_stream_cap() -> None:
    symbols = [f"BTC-{i}" for i in range(658)]
    chunks = chunk_symbols(symbols, MAX_STREAMS_PER_CONN)
    assert len(chunks) == 4
    assert all(len(c) <= MAX_STREAMS_PER_CONN for c in chunks)
    assert sum(len(c) for c in chunks) == 658
    assert chunk_symbols([], 200) == []


def test_used_weight_from_headers() -> None:
    assert used_weight_from_headers({"X-MBX-USED-WEIGHT-1M": "312"}) == 312
    assert used_weight_from_headers({"x-mbx-used-weight-1m": "8"}) == 8
    assert used_weight_from_headers({"content-type": "json"}) is None
    assert used_weight_from_headers(None) is None
    assert used_weight_from_headers({"X-MBX-USED-WEIGHT-1M": "nope"}) is None


def test_ticker_tob_sides_epsilon_size() -> None:
    bids, asks = ticker_tob_sides({"bidPrice": "120.5", "askPrice": "121.0"})
    assert bids == [(120.5, TICKER_EPSILON_SZ)]
    assert asks == [(121.0, TICKER_EPSILON_SZ)]
    empty_b, empty_a = ticker_tob_sides({"bidPrice": "0", "askPrice": ""})
    assert empty_b == []
    assert empty_a == []


@pytest.mark.asyncio
async def test_subscribe_pacer_rate() -> None:
    sent: list[str] = []

    class _Ws:
        async def send(self, payload: str) -> None:
            sent.append(payload)

    pacer = SubscribePacer(per_sec=SUBSCRIBE_PER_SEC)
    ws = _Ws()
    t0 = time.perf_counter()
    await pacer.send(ws, "a")
    await pacer.send(ws, "b")
    await pacer.send(ws, "c")
    elapsed = time.perf_counter() - t0
    assert sent == ["a", "b", "c"]
    # 5 msg/s → 0.2s between frames; 3 sends need ≥ 0.4s after the first.
    assert elapsed >= 0.38
