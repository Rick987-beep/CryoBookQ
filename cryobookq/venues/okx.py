"""OKX public BTC-USD inverse options L5 burst collector."""

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
from cryobookq.venues._util import (
    BurstStats,
    CatalogueTracker,
    Timer,
    book_from_levels,
    peak_rss_mb,
    resolve_deadline_ts,
    track_catalogue,
)
from cryobookq.venues.spec import spec_from_instrument

logger = logging.getLogger(__name__)

OKX_REST = "https://www.okx.com"
OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
_SUB_BATCH = 50


def _parse_okx_sides(data: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = [(float(r[0]), float(r[1])) for r in (data.get("bids") or []) if r]
    asks = [(float(r[0]), float(r[1])) for r in (data.get("asks") or []) if r]
    return bids, asks


class OkxVenue:
    name = "okx"

    def __init__(self, rest_url: str = OKX_REST, ws_url: str = OKX_WS) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url
        self._size_to_btc: dict[str, float] = {}

    def list_instruments(self, underlying: str = "BTC") -> list[Instrument]:
        family = f"{underlying}-USD"
        r = requests.get(
            f"{self.rest_url}/api/v5/public/instruments",
            params={"instType": "OPTION", "instFamily": family},
            timeout=30,
        )
        r.raise_for_status()
        out: list[Instrument] = []
        self._size_to_btc = {}
        for item in r.json().get("data") or []:
            if item.get("state") not in (None, "", "live"):
                continue
            sym = item.get("instId") or ""
            if "USD_UM" in sym:
                continue
            key = option_key_from_symbol(sym, underlying=underlying)
            if key is None:
                continue
            inst = Instrument(venue=self.name, venue_symbol=sym, key=key, raw=item)
            self._size_to_btc[sym] = spec_from_instrument(inst).size_to_btc
            out.append(inst)
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
        timer = Timer()
        t_start = time.time()

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
                    args = [{"channel": "books5", "instId": s} for s in batch]
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
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        arg = msg.get("arg") or {}
                        if arg.get("channel") != "books5":
                            continue
                        payload = msg.get("data") or []
                        if not payload:
                            continue
                        data = payload[0]
                        sym = arg.get("instId") or data.get("instId")
                        if not sym:
                            continue
                        bids, asks = _parse_okx_sides(data)
                        ts_raw = data.get("ts")
                        ts_ms = int(ts_raw) if ts_raw else None
                        books[sym] = book_from_levels(
                            self.name,
                            sym,
                            keys.get(sym),
                            bids,
                            asks,
                            depth,
                            size_to_btc=self._size_to_btc.get(sym, 0.01),
                            ts_exchange_ms=ts_ms,
                        )
        except Exception as exc:  # noqa: BLE001
            logger.exception("OKX burst failed")
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
