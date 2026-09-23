"""Bullish public BTC-USDC options L5 burst collector.

Books come from the unauthenticated multi-orderbook socket. Each
``snapshot`` is the full book (an empty snapshot clears it). A rare
``update`` sets absolute sizes and deletes a level only when its size is 0.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

import requests
import websockets
import websockets.exceptions

from cryobookq.symbols import option_key_from_symbol
from cryobookq.types import BookL5, Instrument
from cryobookq.venues._util import (
    BurstStats,
    CatalogueTracker,
    Timer,
    book_from_levels,
    peak_rss_mb,
    resolve_deadline_ts,
    track_catalogue,
)

logger = logging.getLogger(__name__)

BULLISH_REST = "https://api.exchange.bullish.com/trading-api"
BULLISH_WS = "wss://api.exchange.bullish.com/trading-api/v1/market-data/orderbook"
_SUB_PACE = 200


def flat_levels(raw: Any) -> list[tuple[float, float]]:
    """Flat ``[price, qty, ...]`` strings or numbers → ``(px, sz)`` pairs."""
    if not isinstance(raw, list):
        return []
    out: list[tuple[float, float]] = []
    for i in range(0, len(raw) - 1, 2):
        try:
            px = float(raw[i])
            sz = float(raw[i + 1])
        except (TypeError, ValueError):
            continue
        out.append((px, sz))
    return out


def exchange_ts_ms(data: dict[str, Any]) -> int | None:
    """Prefer publish time. Empty books keep a weeks-old engine timestamp."""
    for key in ("publishedAtTimestamp", "timestamp"):
        raw = data.get(key)
        if raw is None or raw == "":
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


class BullishLocalBook:
    """In-memory book. Snapshots replace; updates upsert absolute size."""

    __slots__ = ("bids", "asks")

    def __init__(self) -> None:
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

    def replace(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        self.bids = {px: sz for px, sz in bids if sz > 0}
        self.asks = {px: sz for px, sz in asks if sz > 0}

    def upsert(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        _upsert_side(self.bids, bids)
        _upsert_side(self.asks, asks)

    def levels(self, depth: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        bids = sorted(self.bids.items(), key=lambda x: -x[0])[:depth]
        asks = sorted(self.asks.items(), key=lambda x: x[0])[:depth]
        return bids, asks


def _upsert_side(book: dict[float, float], levels: list[tuple[float, float]]) -> None:
    for px, sz in levels:
        if sz <= 0:
            book.pop(px, None)
        else:
            book[px] = sz


def apply_l2_message(
    local: dict[str, BullishLocalBook],
    msg: dict[str, Any],
) -> tuple[str | None, int | None]:
    """Apply one socket frame.

    Returns ``(symbol, ts_ms)`` when a snapshot or update was applied, else
    ``(None, None)``. An update before the first snapshot is ignored.
    Subscribe acknowledgements are ignored here.
    """
    kind = msg.get("type")
    if kind not in ("snapshot", "update"):
        return None, None
    data = msg.get("data")
    if not isinstance(data, dict):
        return None, None
    sym = data.get("symbol")
    if not isinstance(sym, str) or not sym:
        return None, None
    state = local.get(sym)
    if kind == "update" and state is None:
        return None, None
    bids = flat_levels(data.get("bids"))
    asks = flat_levels(data.get("asks"))
    if kind == "snapshot":
        state = BullishLocalBook()
        state.replace(bids, asks)
        local[sym] = state
    else:
        assert state is not None
        state.upsert(bids, asks)
    return sym, exchange_ts_ms(data)


def subscribe_error(msg: dict[str, Any]) -> str | None:
    """Human-readable nack, or None for a success ack / non-ack frame."""
    if "result" not in msg:
        err = msg.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("errorCodeName") or err)
        return None
    result = msg.get("result") or {}
    if not isinstance(result, dict):
        return None
    code = str(result.get("responseCode") or "")
    if code == "200":
        return None
    if not code and "errorCode" not in result and "errorCodeName" not in result:
        return None
    name = result.get("errorCodeName") or result.get("message") or result.get("errorCode")
    return str(name or result)


def instruments_from_rows(rows: Any, underlying: str, venue: str = "bullish") -> list[Instrument]:
    """Keep enabled BTC (or *underlying*) options. Ignore rows the symbol parser rejects.

    ``GET /v1/markets`` ignores ``optionType`` and ``underlyingBaseSymbol``, so the
    filter lives here.
    """
    want = underlying.strip().upper()
    if not isinstance(rows, list):
        return []
    out: list[Instrument] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("marketEnabled") is False:
            continue
        if (item.get("marketType") or "OPTION") != "OPTION":
            continue
        base = (item.get("underlyingBaseSymbol") or item.get("baseSymbol") or "").upper()
        if base != want:
            continue
        sym = item.get("symbol") or ""
        key = option_key_from_symbol(str(sym), underlying=want)
        if key is None:
            continue
        out.append(Instrument(venue=venue, venue_symbol=str(sym), key=key, raw=item))
    return out


class BullishVenue:
    """Public BTC-USDC options. No API key."""

    name = "bullish"

    def __init__(self, rest_url: str = BULLISH_REST, ws_url: str = BULLISH_WS) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url

    def list_instruments(self, underlying: str = "BTC") -> list[Instrument]:
        """Enabled OPTION markets whose symbol parses as *underlying*."""
        want = underlying.strip().upper()
        r = requests.get(
            f"{self.rest_url}/v1/markets",
            params={"marketType": "OPTION"},
            timeout=30,
        )
        r.raise_for_status()
        return instruments_from_rows(r.json(), want, self.name)

    async def burst_books(
        self,
        symbols: list[str],
        depth: int = 5,
        deadline: datetime | None = None,
        duration_s: float | None = None,
    ) -> tuple[dict[str, BookL5], BurstStats]:
        """Subscribe ``l2Orderbook`` until *deadline* and keep the last L5 per symbol."""
        if not symbols:
            return {}, BurstStats(self.name, 0, 0, 0.0, peak_rss_mb())

        deadline_ts = resolve_deadline_ts(deadline, duration_s)
        books: dict[str, BookL5] = {}
        keys = {s: option_key_from_symbol(s) for s in symbols}
        wanted = set(symbols)
        errors: list[str] = []
        notes: list[str] = []
        local: dict[str, BullishLocalBook] = {}
        timer = Timer()
        t_start = time.time()

        try:
            async with websockets.connect(
                self.ws_url,
                open_timeout=10,
                close_timeout=3,
                ping_interval=20,
                ping_timeout=60,
                max_size=16 * 1024 * 1024,
            ) as ws:
                for i, sym in enumerate(symbols):
                    await ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "type": "command",
                                "method": "subscribe",
                                "params": {"topic": "l2Orderbook", "symbol": sym},
                                "id": str(i),
                            }
                        )
                    )
                    if i % _SUB_PACE == _SUB_PACE - 1:
                        await asyncio.sleep(0.01)
                notes.append(f"subscribed={len(symbols)}")
                cat = CatalogueTracker(self.name, len(symbols), books, notes, t_start)
                async with track_catalogue(cat, deadline_ts):
                    while time.time() < deadline_ts:
                        remaining = deadline_ts - time.time()
                        if remaining <= 0:
                            break
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
                        except TimeoutError:
                            continue
                        except websockets.exceptions.ConnectionClosed as exc:
                            notes.append(f"ws_closed:{exc}")
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(msg, dict):
                            continue
                        err = subscribe_error(msg)
                        if err:
                            if len(errors) < 8:
                                errors.append(err)
                            continue
                        sym, ts_ms = apply_l2_message(local, msg)
                        if sym is None or sym not in wanted:
                            continue
                        state = local[sym]
                        out_b, out_a = state.levels(depth)
                        books[sym] = book_from_levels(
                            self.name,
                            sym,
                            keys.get(sym),
                            out_b,
                            out_a,
                            depth,
                            size_to_btc=1.0,
                            ts_exchange_ms=ts_ms,
                        )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bullish burst failed")
            errors.append(f"{type(exc).__name__}:{exc}")

        lag = (time.time() - t_start) * 1000
        stats = BurstStats(
            venue=self.name,
            n_instruments=len(symbols),
            n_with_update=len(books),
            duration_s=timer.elapsed(),
            peak_rss_mb=peak_rss_mb(),
            subscribe_errors=errors,
            notes=notes,
            capture_lag_ms=lag,
        )
        return books, stats
