"""Binance European options (eapi) L5 burst — fstream WS + REST fill."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

import requests
import websockets

from cryobookq.symbols import option_key_from_symbol
from cryobookq.types import BookL5, Instrument
from cryobookq.venues._util import BurstStats, Timer, book_from_levels, peak_rss_mb, resolve_deadline_ts

logger = logging.getLogger(__name__)

BINANCE_REST = "https://eapi.binance.com"
BINANCE_WS = "wss://fstream.binance.com/eoptions/ws"
_SUB_BATCH = 50
_REST_CONCURRENCY = 20


def _parse_binance_sides(data: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = [(float(r[0]), float(r[1])) for r in (data.get("b") or data.get("bids") or []) if r]
    asks = [(float(r[0]), float(r[1])) for r in (data.get("a") or data.get("asks") or []) if r]
    return bids, asks


def _rest_depth(symbol: str, rest_url: str) -> dict[str, Any] | None:
    r = requests.get(
        f"{rest_url}/eapi/v1/depth",
        params={"symbol": symbol, "limit": 10},
        timeout=10,
    )
    if r.status_code != 200:
        return None
    return r.json()


class BinanceVenue:
    name = "binance"

    def __init__(self, rest_url: str = BINANCE_REST, ws_url: str = BINANCE_WS) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url

    def list_instruments(self, underlying: str = "BTC") -> list[Instrument]:
        r = requests.get(f"{self.rest_url}/eapi/v1/exchangeInfo", timeout=30)
        r.raise_for_status()
        info = r.json()
        want = f"{underlying}USDT"
        out: list[Instrument] = []
        for item in info.get("optionSymbols") or info.get("symbols") or []:
            if item.get("underlying") != want:
                continue
            if (item.get("status") or "TRADING") != "TRADING":
                continue
            sym = item.get("symbol") or ""
            key = option_key_from_symbol(sym, underlying=underlying)
            if key is None:
                continue
            out.append(Instrument(venue=self.name, venue_symbol=sym, key=key, raw=item))
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
        notes: list[str] = ["ws=fstream"]
        timer = Timer()
        t_start = time.time()

        def _store(sym: str, data: dict[str, Any], ts_ms: int | None = None) -> None:
            bids, asks = _parse_binance_sides(data)
            books[sym] = book_from_levels(
                self.name, sym, keys.get(sym), bids, asks, depth, ts_exchange_ms=ts_ms
            )

        try:
            async with websockets.connect(
                self.ws_url,
                open_timeout=10,
                close_timeout=3,
                ping_interval=20,
                max_size=8 * 1024 * 1024,
            ) as ws:
                for i in range(0, len(symbols), _SUB_BATCH):
                    batch = symbols[i : i + _SUB_BATCH]
                    params = [f"{s.lower()}@depth10@100ms" for s in batch]
                    await ws.send(json.dumps({"method": "SUBSCRIBE", "params": params, "id": i + 1}))
                notes.append(f"subscribed={len(symbols)}")
                while time.time() < deadline_ts:
                    remaining = deadline_ts - time.time()
                    if remaining <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 2.0))
                    except TimeoutError:
                        continue
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("e") != "depthUpdate":
                        continue
                    sym = msg.get("s")
                    if not sym:
                        continue
                    _store(sym, msg, int(msg["E"]) if msg.get("E") else None)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Binance WS burst failed")
            errors.append(f"{type(exc).__name__}:{exc}")
            notes.append("ws_failed")

        missing = [s for s in symbols if s not in books]
        if missing:
            notes.append(f"rest_fill={len(missing)}")
            sem = asyncio.Semaphore(_REST_CONCURRENCY)

            async def _fill(sym: str) -> None:
                async with sem:
                    data = await asyncio.to_thread(_rest_depth, sym, self.rest_url)
                if data:
                    _store(sym, data)

            await asyncio.gather(*[_fill(s) for s in missing], return_exceptions=True)

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
