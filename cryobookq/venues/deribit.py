"""Deribit public REST + WS L5 book burst collector."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import requests
import websockets
import websockets.exceptions

from cryobookq.symbols import option_key_from_symbol
from cryobookq.types import BookL5, Instrument, OptionKey, pad_levels
from cryobookq.venues._util import BurstStats, Timer, peak_rss_mb

logger = logging.getLogger(__name__)

DERIBIT_REST = "https://www.deribit.com/api/v2"
DERIBIT_WS = "wss://www.deribit.com/ws/api/v2"
_SUBSCRIBE_BATCH = 100
# Interval book channels only accept depth ∈ {1, 10, 20}. We request 10 and
# truncate to the caller's L5 (depth=5) in pad_levels.
_WS_DEPTH_ALLOWED = (1, 10, 20)


def _ws_channel_depth(depth: int) -> int:
    for allowed in _WS_DEPTH_ALLOWED:
        if depth <= allowed:
            return allowed
    return 20


def _channel(symbol: str, depth: int) -> str:
    return f"book.{symbol}.none.{_ws_channel_depth(depth)}.100ms"


def _parse_book_sides(data: dict[str, Any], depth: int) -> tuple[list[float], list[float], list[float], list[float]]:
    """Parse Deribit book notification into L5 px/sz arrays.

    Snapshot levels are ``[price, amount]``. Change rows are
    ``[action, price, amount]`` — we only apply full snapshots for M0/M1
    (interval books re-send snapshots frequently enough).
    """
    bids_raw = data.get("bids") or []
    asks_raw = data.get("asks") or []
    # Prefer snapshot-shaped rows (len 2). If only change rows, rebuild from
    # change events into a simple map (best-effort).
    if bids_raw and len(bids_raw[0]) == 2:
        bid_levels = [(float(r[0]), float(r[1])) for r in bids_raw[:depth]]
        ask_levels = [(float(r[0]), float(r[1])) for r in asks_raw[:depth]]
    else:
        bid_map: dict[float, float] = {}
        ask_map: dict[float, float] = {}
        for row in bids_raw:
            if len(row) < 3:
                continue
            _action, px, sz = row[0], float(row[1]), float(row[2])
            if sz == 0:
                bid_map.pop(px, None)
            else:
                bid_map[px] = sz
        for row in asks_raw:
            if len(row) < 3:
                continue
            _action, px, sz = row[0], float(row[1]), float(row[2])
            if sz == 0:
                ask_map.pop(px, None)
            else:
                ask_map[px] = sz
        bid_levels = sorted(bid_map.items(), key=lambda x: -x[0])[:depth]
        ask_levels = sorted(ask_map.items(), key=lambda x: x[0])[:depth]

    bid_px, bid_sz = pad_levels(bid_levels, depth)
    ask_px, ask_sz = pad_levels(ask_levels, depth)
    return bid_px, bid_sz, ask_px, ask_sz


class DeribitVenue:
    """Public Deribit venue adapter (no auth)."""

    name = "deribit"

    def __init__(self, rest_url: str = DERIBIT_REST, ws_url: str = DERIBIT_WS) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url

    def list_instruments(self, underlying: str = "BTC") -> list[Instrument]:
        url = f"{self.rest_url}/public/get_instruments"
        resp = requests.get(
            url,
            params={"currency": underlying, "kind": "option", "expired": "false"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json().get("result") or []
        out: list[Instrument] = []
        for item in result:
            name = item.get("instrument_name") or ""
            key = option_key_from_symbol(name, underlying=underlying)
            if key is None:
                # Fall back to REST fields when name parse fails
                exp_ms = int(item.get("expiration_timestamp") or 0)
                strike = float(item.get("strike") or 0)
                is_call = (item.get("option_type") or "").lower() == "call"
                if not name or not exp_ms:
                    continue
                key = OptionKey(underlying, exp_ms, strike, is_call)
            out.append(Instrument(venue=self.name, venue_symbol=name, key=key, raw=item))
        return out

    async def burst_books(
        self,
        symbols: list[str],
        depth: int = 5,
        deadline: datetime | None = None,
        duration_s: float | None = None,
    ) -> tuple[dict[str, BookL5], BurstStats]:
        """Burst-subscribe L5 books until deadline or duration_s (default 15s)."""
        if not symbols:
            stats = BurstStats(
                venue=self.name,
                n_instruments=0,
                n_with_update=0,
                duration_s=0.0,
                peak_rss_mb=peak_rss_mb(),
            )
            return {}, stats

        if deadline is not None:
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            deadline_ts = deadline.timestamp()
        else:
            dur = 15.0 if duration_s is None else duration_s
            deadline_ts = time.time() + dur

        books: dict[str, BookL5] = {}
        keys = {s: option_key_from_symbol(s) for s in symbols}
        errors: list[str] = []
        notes: list[str] = []
        msg_id = 0
        timer = Timer()
        t_start = time.time()

        def next_id() -> int:
            nonlocal msg_id
            msg_id += 1
            return msg_id

        async def send(ws: Any, method: str, params: dict[str, Any] | None = None) -> None:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": next_id(),
                        "method": method,
                        "params": params or {},
                    }
                )
            )

        try:
            async with websockets.connect(
                self.ws_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=16 * 1024 * 1024,
            ) as ws:
                channels = [_channel(s, depth) for s in symbols]
                for i in range(0, len(channels), _SUBSCRIBE_BATCH):
                    batch = channels[i : i + _SUBSCRIBE_BATCH]
                    await send(ws, "public/subscribe", {"channels": batch})

                # Drain subscribe acks + book updates until deadline
                while time.time() < deadline_ts:
                    remaining = deadline_ts - time.time()
                    if remaining <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(1.0, remaining))
                    except TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed as exc:
                        errors.append(f"ws_closed:{exc}")
                        break

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if "error" in msg:
                        err = msg["error"]
                        errors.append(str(err)[:200])
                        continue

                    # Subscribe ack: empty result means channels rejected
                    if "result" in msg and msg.get("id") is not None:
                        result = msg.get("result")
                        if isinstance(result, list) and len(result) == 0:
                            errors.append("subscribe_ack_empty_result")
                        continue

                    if msg.get("method") != "subscription":
                        continue

                    params = msg.get("params") or {}
                    channel = params.get("channel") or ""
                    data = params.get("data") or {}
                    if not channel.startswith("book."):
                        continue
                    # book.BTC-28MAR26-80000-C.none.10.100ms
                    parts = channel.split(".")
                    if len(parts) < 2:
                        continue
                    symbol = parts[1]
                    if symbol not in keys:
                        continue
                    bid_px, bid_sz, ask_px, ask_sz = _parse_book_sides(data, depth)
                    books[symbol] = BookL5(
                        venue=self.name,
                        venue_symbol=symbol,
                        key=keys.get(symbol),
                        ts_exchange_ms=int(data["timestamp"]) if data.get("timestamp") else None,
                        bid_px=bid_px,
                        bid_sz=bid_sz,
                        ask_px=ask_px,
                        ask_sz=ask_sz,
                    )

                # Best-effort unsubscribe
                try:
                    for i in range(0, len(channels), _SUBSCRIBE_BATCH):
                        batch = channels[i : i + _SUBSCRIBE_BATCH]
                        await send(ws, "public/unsubscribe", {"channels": batch})
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"unsubscribe_failed:{exc}")

        except Exception as exc:  # noqa: BLE001
            errors.append(f"connect:{exc}")
            logger.exception("Deribit burst failed")

        duration = timer.elapsed()
        lag_ms = (time.time() - t_start) * 1000.0
        # Capture lag ≈ time from start to last update wall clock vs now;
        # report window length as proxy for M0.
        stats = BurstStats(
            venue=self.name,
            n_instruments=len(symbols),
            n_with_update=len(books),
            duration_s=duration,
            peak_rss_mb=peak_rss_mb(),
            subscribe_errors=errors[:20],
            notes=notes,
            capture_lag_ms=round(lag_ms, 1),
        )
        if stats.coverage < 0.9:
            notes.append(
                "coverage_below_90pct — may need dual WS connections for full chain"
            )
            stats.notes = notes
        return books, stats
