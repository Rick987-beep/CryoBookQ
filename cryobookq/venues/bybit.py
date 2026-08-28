"""Bybit public USDT options L5 burst collector."""

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

BYBIT_REST = "https://api.bybit.com"
BYBIT_WS = "wss://stream.bybit.com/v5/public/option"
_SUB_BATCH = 20


def _parse_bybit_sides(data: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = [(float(r[0]), float(r[1])) for r in (data.get("b") or []) if r]
    asks = [(float(r[0]), float(r[1])) for r in (data.get("a") or []) if r]
    bids.sort(key=lambda x: -x[0])
    asks.sort(key=lambda x: x[0])
    return bids, asks


class BybitLocalBook:
    """In-memory L2: snapshot replace, delta upsert/delete (size 0)."""

    __slots__ = ("bids", "asks")

    def __init__(self) -> None:
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

    def apply_snapshot(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        self.bids = {px: sz for px, sz in bids if sz > 0}
        self.asks = {px: sz for px, sz in asks if sz > 0}

    def apply_delta(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        for px, sz in bids:
            if sz == 0:
                self.bids.pop(px, None)
            else:
                self.bids[px] = sz
        for px, sz in asks:
            if sz == 0:
                self.asks.pop(px, None)
            else:
                self.asks[px] = sz

    def levels(self, depth: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        bids = sorted(self.bids.items(), key=lambda x: -x[0])[:depth]
        asks = sorted(self.asks.items(), key=lambda x: x[0])[:depth]
        return bids, asks


class BybitVenue:
    name = "bybit"

    def __init__(self, rest_url: str = BYBIT_REST, ws_url: str = BYBIT_WS) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url

    def list_instruments(self, underlying: str = "BTC") -> list[Instrument]:
        out: list[Instrument] = []
        cursor = ""
        for _ in range(30):
            params: dict[str, str | int] = {
                "category": "option",
                "baseCoin": underlying,
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor
            r = requests.get(
                f"{self.rest_url}/v5/market/instruments-info",
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            result = r.json().get("result") or {}
            for item in result.get("list") or []:
                if (item.get("status") or "") != "Trading":
                    continue
                if (item.get("settleCoin") or "USDT") != "USDT":
                    continue
                sym = item.get("symbol") or ""
                key = option_key_from_symbol(sym, underlying=underlying)
                if key is None:
                    continue
                out.append(Instrument(venue=self.name, venue_symbol=sym, key=key, raw=item))
            cursor = result.get("nextPageCursor") or ""
            if not cursor:
                break
        return out

    async def burst_books(
        self,
        symbols: list[str],
        depth: int = 5,
        deadline: datetime | None = None,
        duration_s: float | None = None,
    ) -> tuple[dict[str, BookL5], BurstStats]:
        if not symbols:
            return {}, BurstStats(self.name, 0, 0, 0.0, peak_rss_mb())

        deadline_ts = resolve_deadline_ts(deadline, duration_s)
        books: dict[str, BookL5] = {}
        keys = {s: option_key_from_symbol(s) for s in symbols}
        errors: list[str] = []
        notes: list[str] = []
        local: dict[str, BybitLocalBook] = {}
        timer = Timer()
        t_start = time.time()

        try:
            async with websockets.connect(
                self.ws_url,
                open_timeout=10,
                close_timeout=3,
                ping_interval=20,
                ping_timeout=60,
                max_size=8 * 1024 * 1024,
            ) as ws:
                for i in range(0, len(symbols), _SUB_BATCH):
                    batch = symbols[i : i + _SUB_BATCH]
                    args = [f"orderbook.25.{s}" for s in batch]
                    await ws.send(json.dumps({"op": "subscribe", "args": args}))
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
                        topic = msg.get("topic") or ""
                        if not topic.startswith("orderbook."):
                            continue
                        data = msg.get("data")
                        if not isinstance(data, dict):
                            continue
                        sym = data.get("s") or topic.rsplit(".", 1)[-1]
                        if not sym:
                            continue
                        bids, asks = _parse_bybit_sides(data)
                        msg_type = (msg.get("type") or "snapshot").lower()
                        seq = data.get("u")
                        state = local.get(sym)
                        if msg_type == "snapshot" or seq in (1, "1"):
                            state = BybitLocalBook()
                            state.apply_snapshot(bids, asks)
                            local[sym] = state
                        elif msg_type == "delta":
                            if state is None:
                                continue
                            state.apply_delta(bids, asks)
                        else:
                            continue
                        out_b, out_a = state.levels(depth)
                        ts_ms = int(msg.get("ts") or data.get("ts") or 0) or None
                        books[sym] = book_from_levels(
                            self.name, sym, keys.get(sym), out_b, out_a, depth, ts_exchange_ms=ts_ms
                        )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bybit burst failed")
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
