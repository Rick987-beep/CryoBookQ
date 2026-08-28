"""Binance European options (eapi) L5 sampler.

WS: ≤200 streams per connection, SUBSCRIBE paced at 5 msg/s.
REST depth: paced, honor X-MBX-USED-WEIGHT-1M (live cap 400/min, depth weight 2).
Ticker: last-resort TOB for names still silent (presence/spread, not real L5 size).
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

from cryobookq.symbols import option_key_from_symbol
from cryobookq.types import BookL5, Instrument
from cryobookq.venues._util import BurstStats, Timer, book_from_levels, peak_rss_mb, resolve_deadline_ts

logger = logging.getLogger(__name__)

BINANCE_REST = "https://eapi.binance.com"
BINANCE_WS = "wss://fstream.binance.com/eoptions/ws"

MAX_STREAMS_PER_CONN = 200
SUB_BATCH = 50
SUBSCRIBE_PER_SEC = 5.0
REST_WEIGHT_LIMIT = 400
REST_WEIGHT_STOP = 340  # leave room for ticker (40) and jitter
DEPTH_WEIGHT_HINT = 2
REST_INTERVAL_S = 0.4  # ~2.5 req/s
TICKER_EPSILON_SZ = 1e-6  # TOB-only fill so two-sided/spread work; depth ≈ 0


def chunk_symbols(symbols: list[str], size: int = MAX_STREAMS_PER_CONN) -> list[list[str]]:
    if size <= 0:
        return [list(symbols)]
    return [symbols[i : i + size] for i in range(0, len(symbols), size)]


def used_weight_from_headers(headers: Any) -> int | None:
    if headers is None:
        return None
    get = headers.get if hasattr(headers, "get") else lambda *_a, **_k: None
    for key in headers:
        if str(key).lower() == "x-mbx-used-weight-1m":
            try:
                return int(get(key))
            except (TypeError, ValueError):
                return None
    return None


def ticker_tob_sides(item: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Best bid/ask from /eapi/v1/ticker. Sizes are epsilon (not real L5)."""
    try:
        bid = float(item.get("bidPrice") or 0)
    except (TypeError, ValueError):
        bid = 0.0
    try:
        ask = float(item.get("askPrice") or 0)
    except (TypeError, ValueError):
        ask = 0.0
    bids = [(bid, TICKER_EPSILON_SZ)] if bid > 0 else []
    asks = [(ask, TICKER_EPSILON_SZ)] if ask > 0 else []
    return bids, asks


class SubscribePacer:
    """Global cap on WS SUBSCRIBE frames (Binance ~5 incoming messages/s)."""

    def __init__(self, per_sec: float = SUBSCRIBE_PER_SEC) -> None:
        self._interval = 1.0 / max(per_sec, 0.1)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def send(self, ws: Any, payload: str) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            await ws.send(payload)
            self._last = time.monotonic()


def _parse_binance_sides(data: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids = [(float(r[0]), float(r[1])) for r in (data.get("b") or data.get("bids") or []) if r]
    asks = [(float(r[0]), float(r[1])) for r in (data.get("a") or data.get("asks") or []) if r]
    return bids, asks


def _rest_depth(symbol: str, rest_url: str) -> tuple[dict[str, Any] | None, int | None, int]:
    """Return (body, used_weight_1m, http_status). Status 0 = transport error."""
    try:
        r = requests.get(
            f"{rest_url}/eapi/v1/depth",
            params={"symbol": symbol, "limit": 10},
            timeout=8,
        )
    except requests.RequestException:
        return None, None, 0
    weight = used_weight_from_headers(r.headers)
    if r.status_code == 429:
        return None, weight, 429
    if r.status_code != 200:
        return None, weight, r.status_code
    return r.json(), weight, 200


class BinanceVenue:
    name = "binance"

    def __init__(
        self,
        rest_url: str = BINANCE_REST,
        ws_url: str = BINANCE_WS,
        rest_budget_s: float = 30.0,
    ) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url
        self.rest_budget_s = float(rest_budget_s)

    def list_instruments(self, underlying: str = "BTC") -> list[Instrument]:
        r = None
        for attempt in range(3):
            r = requests.get(f"{self.rest_url}/eapi/v1/exchangeInfo", timeout=30)
            if r.status_code != 429:
                break
            time.sleep(0.8 * (attempt + 1))
        assert r is not None
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
        notes: list[str] = ["ws=fstream", "sampler=slow"]
        rest_status: dict[int, int] = {}
        timer = Timer()
        t_start = time.time()
        pacer = SubscribePacer()

        def _store(sym: str, bids: list, asks: list, ts_ms: int | None = None) -> None:
            books[sym] = book_from_levels(
                self.name, sym, keys.get(sym), bids, asks, depth, ts_exchange_ms=ts_ms
            )

        def _log_catalogue(phase: str) -> None:
            n = len(books)
            two = sum(1 for b in books.values() if b.two_sided)
            logger.info(
                "binance catalogue phase=%s t=%.1fs books=%d/%d coverage=%.1f%% two_sided=%d",
                phase,
                time.time() - t_start,
                n,
                len(symbols),
                100.0 * n / len(symbols) if symbols else 0.0,
                two,
            )
            notes.append(f"cat_{phase}={n}/{len(symbols)}")

        async def _ws_chunk(chunk: list[str]) -> None:
            try:
                async with websockets.connect(
                    self.ws_url,
                    open_timeout=10,
                    close_timeout=3,
                    ping_interval=20,
                    max_size=8 * 1024 * 1024,
                ) as ws:
                    for i in range(0, len(chunk), SUB_BATCH):
                        batch = chunk[i : i + SUB_BATCH]
                        params = [f"{s.lower()}@depth10@100ms" for s in batch]
                        payload = json.dumps({"method": "SUBSCRIBE", "params": params, "id": i + 1})
                        await pacer.send(ws, payload)
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
                        bids, asks = _parse_binance_sides(msg)
                        _store(sym, bids, asks, int(msg["E"]) if msg.get("E") else None)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Binance WS chunk failed n=%d", len(chunk))
                errors.append(f"{type(exc).__name__}:{exc}")

        async def _progress() -> None:
            n = 0
            while time.time() < deadline_ts:
                await asyncio.sleep(10.0)
                n += 1
                _log_catalogue(f"ws_{n * 10}s")

        chunks = chunk_symbols(symbols, MAX_STREAMS_PER_CONN)
        notes.append(f"ws_conns={len(chunks)}")
        notes.append(f"subscribed={len(symbols)}")
        _log_catalogue("ws_start")
        progress = asyncio.create_task(_progress())
        try:
            await asyncio.gather(*[_ws_chunk(c) for c in chunks], return_exceptions=True)
        finally:
            progress.cancel()
        _log_catalogue("ws_done")

        missing = [s for s in symbols if s not in books]
        used_weight = 0
        rest_ok = 0
        rest_429 = 0
        if missing:
            notes.append(f"rest_need={len(missing)}")
            rest_deadline = time.time() + max(self.rest_budget_s, 0.0)
            rest_pacer_last = 0.0
            for i, sym in enumerate(missing):
                if time.time() >= rest_deadline:
                    notes.append("rest_time_stop")
                    break
                if used_weight >= REST_WEIGHT_STOP:
                    notes.append(f"rest_weight_stop={used_weight}")
                    break
                if rest_429 >= 5:
                    notes.append("rest_429_stop")
                    break
                now = time.monotonic()
                wait = REST_INTERVAL_S - (now - rest_pacer_last)
                if wait > 0:
                    await asyncio.sleep(wait)
                rest_pacer_last = time.monotonic()
                body, weight, status = await asyncio.to_thread(_rest_depth, sym, self.rest_url)
                rest_status[status] = rest_status.get(status, 0) + 1
                if weight is not None:
                    used_weight = weight
                else:
                    used_weight += DEPTH_WEIGHT_HINT
                if status == 429:
                    rest_429 += 1
                    await asyncio.sleep(1.0)
                    continue
                if body:
                    bids, asks = _parse_binance_sides(body)
                    _store(sym, bids, asks)
                    rest_ok += 1
                if i > 0 and i % 25 == 0:
                    _log_catalogue(f"rest_{i}")
            notes.append(f"rest_ok={rest_ok}")
            notes.append(f"rest_429={rest_429}")
            notes.append(f"rest_weight={used_weight}")
            notes.append("rest_http=" + ",".join(f"{k}:{v}" for k, v in sorted(rest_status.items())))
            logger.info(
                "binance REST done ok=%d need=%d 429=%d weight=%d http=%s",
                rest_ok,
                len(missing),
                rest_429,
                used_weight,
                rest_status,
            )
        _log_catalogue("rest_done")

        still = [s for s in symbols if s not in books]
        if still and self.rest_budget_s > 0 and used_weight + 40 <= REST_WEIGHT_LIMIT:
            try:
                tr = await asyncio.to_thread(
                    requests.get, f"{self.rest_url}/eapi/v1/ticker", timeout=30
                )
                tw = used_weight_from_headers(tr.headers)
                if tw is not None:
                    used_weight = tw
                n_tick = 0
                if tr.status_code == 200:
                    want = set(still)
                    for item in tr.json() or []:
                        sym = item.get("symbol")
                        if sym not in want or sym in books:
                            continue
                        bids, asks = ticker_tob_sides(item)
                        if not bids and not asks:
                            continue
                        _store(str(sym), bids, asks)
                        n_tick += 1
                    notes.append(f"ticker_fill={n_tick}")
                else:
                    notes.append(f"ticker_http={tr.status_code}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Binance ticker fill skipped: %s", exc)
                notes.append(f"ticker_error={type(exc).__name__}")
        elif still and self.rest_budget_s <= 0:
            notes.append("ticker_skipped_ws_only")
        elif still:
            notes.append("ticker_skipped_weight")
        _log_catalogue("done")

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
