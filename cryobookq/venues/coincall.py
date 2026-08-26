"""Coincall options REST + signed WS L5 book burst collector."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import requests
import websockets
import websockets.exceptions

from cryobookq.config import Settings, get_settings
from cryobookq.symbols import option_key_from_symbol
from cryobookq.types import BookL5, Instrument, OptionKey, pad_levels
from cryobookq.venues._util import BurstStats, Timer, peak_rss_mb

logger = logging.getLogger(__name__)

COINCALL_URLS = {
    "testnet": {
        "base_url": "https://betaapi.coincall.com",
        "ws_options": "wss://betaws.coincall.com/options",
    },
    "production": {
        "base_url": "https://api.coincall.com",
        "ws_options": "wss://ws.coincall.com/options",
    },
}

_BATCH = 100  # Coincall max symbols per orderBook subscribe


def _sign_ws(api_key: str, api_secret: str, ts: int) -> str:
    """HMAC-SHA256 uppercase hex per Coincall options WS docs."""
    prehash = f"GET/users/self/verify?apiKey={api_key}&ts={ts}"
    return hmac.new(
        api_secret.encode("utf-8"),
        prehash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()


def build_signed_ws_url(ws_base: str, api_key: str, api_secret: str) -> str:
    """Build Coincall options WS URL.

    Do **not** URL-encode the API key: Coincall expects the raw base64 key in
    the query string (encoding produces HTTP 403).
    """
    ts = int(time.time() * 1000)
    sign = _sign_ws(api_key, api_secret, ts)
    return (
        f"{ws_base}?code=10&uuid={api_key}&ts={ts}&sign={sign}&apiKey={api_key}"
    )


def _extract_symbol(item: dict[str, Any]) -> str | None:
    for k in ("symbolName", "symbol", "instrumentName", "optionName", "name"):
        v = item.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _parse_coincall_book(data: dict[str, Any], depth: int) -> tuple[list[float], ...]:
    asks = data.get("asks") or []
    bids = data.get("bids") or []

    def levels(side: list[Any]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for row in side[:depth]:
            if isinstance(row, dict):
                out.append((float(row.get("pr") or 0), float(row.get("sz") or 0)))
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                out.append((float(row[0]), float(row[1])))
        return out

    bid_px, bid_sz = pad_levels(levels(bids), depth)
    ask_px, ask_sz = pad_levels(levels(asks), depth)
    return bid_px, bid_sz, ask_px, ask_sz


class CoincallVenue:
    """Coincall options venue — public REST instruments; signed WS for books."""

    name = "coincall"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        env = self.settings.coincall_env
        urls = COINCALL_URLS.get(env) or COINCALL_URLS["production"]
        self.base_url = urls["base_url"]
        self.ws_url = urls["ws_options"]

    def list_instruments(self, underlying: str = "BTC") -> list[Instrument]:
        url = f"{self.base_url}/open/option/getInstruments/{underlying}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") not in (0, "0", None) and not body.get("data"):
            raise RuntimeError(f"Coincall getInstruments failed: {body.get('msg') or body}")
        raw_list = body.get("data") or []
        if isinstance(raw_list, dict):
            # Some responses nest under optionList / instruments
            raw_list = (
                raw_list.get("optionList")
                or raw_list.get("instruments")
                or raw_list.get("list")
                or []
            )
        out: list[Instrument] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            if item.get("isActive") is False:
                continue
            symbol = _extract_symbol(item)
            if not symbol:
                continue
            key = option_key_from_symbol(symbol, underlying=underlying)
            if key is None:
                # Try REST expiry fields
                exp = (
                    item.get("expirationTimestamp")
                    or item.get("expireTime")
                    or item.get("expiration")
                    or item.get("end")
                )
                strike = item.get("strike") or item.get("strikePrice")
                opt = item.get("optionType") or item.get("type")
                if exp is None or strike is None:
                    continue
                is_call = True
                if opt is not None:
                    is_call = str(opt).upper() in ("C", "CALL", "1", "1.0")
                elif symbol.endswith("-P"):
                    is_call = False
                elif symbol.endswith("-C"):
                    is_call = True
                key = OptionKey(underlying, int(exp), float(strike), is_call)
            out.append(Instrument(venue=self.name, venue_symbol=symbol, key=key, raw=item))
        return out

    async def burst_books(
        self,
        symbols: list[str],
        depth: int = 5,
        deadline: datetime | None = None,
        duration_s: float | None = None,
        *,
        require_auth: bool = True,
    ) -> tuple[dict[str, BookL5], BurstStats]:
        if not symbols:
            return {}, BurstStats(
                venue=self.name,
                n_instruments=0,
                n_with_update=0,
                duration_s=0.0,
                peak_rss_mb=peak_rss_mb(),
            )

        if deadline is None:
            dur = 15.0 if duration_s is None else duration_s
            deadline_ts = time.time() + dur
        else:
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            deadline_ts = deadline.timestamp()

        notes: list[str] = []
        errors: list[str] = []
        books: dict[str, BookL5] = {}
        keys = {s: option_key_from_symbol(s) for s in symbols}
        timer = Timer()
        t_start = time.time()

        api_key = self.settings.coincall_api_key
        api_secret = self.settings.coincall_api_secret
        if require_auth and not (api_key and api_secret):
            errors.append("missing_COINCALL_API_KEY_or_SECRET")
            return books, BurstStats(
                venue=self.name,
                n_instruments=len(symbols),
                n_with_update=0,
                duration_s=timer.elapsed(),
                peak_rss_mb=peak_rss_mb(),
                subscribe_errors=errors,
                notes=["set COINCALL_API_KEY/SECRET in .env"],
            )

        if api_key and api_secret:
            url = build_signed_ws_url(self.ws_url, api_key, api_secret)
            notes.append("ws_auth=signed")
        else:
            url = self.ws_url
            notes.append("ws_auth=none")

        try:
            async with websockets.connect(
                url,
                ping_interval=None,  # Coincall uses app-level heartbeat
                close_timeout=5,
                max_size=16 * 1024 * 1024,
            ) as ws:
                # Subscribe in batches of 100
                for i in range(0, len(symbols), _BATCH):
                    batch = symbols[i : i + _BATCH]
                    msg = {
                        "action": "subscribe",
                        "dataType": "orderBook",
                        "payload": {"symbol": batch},
                    }
                    await ws.send(json.dumps(msg))

                last_hb = time.time()
                while time.time() < deadline_ts:
                    remaining = deadline_ts - time.time()
                    if remaining <= 0:
                        break
                    # Heartbeat every 3s
                    if time.time() - last_hb >= 3.0:
                        try:
                            await ws.send(json.dumps({"action": "heartbeat"}))
                        except Exception as exc:  # noqa: BLE001
                            errors.append(f"heartbeat:{exc}")
                            break
                        last_hb = time.time()
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

                    if msg.get("result") == "failed":
                        errors.append(str(msg)[:200])
                        continue

                    data = msg.get("d") if isinstance(msg.get("d"), dict) else None
                    if data is None and isinstance(msg.get("data"), dict):
                        data = msg["data"]
                    if data is None and msg.get("dataType") == "orderBook":
                        payload = msg.get("payload")
                        data = payload if isinstance(payload, dict) else None

                    if not isinstance(data, dict):
                        continue
                    symbol = data.get("s") or data.get("symbol")
                    if not symbol:
                        continue
                    symbol = str(symbol)
                    if symbol not in keys:
                        continue
                    bid_px, bid_sz, ask_px, ask_sz = _parse_coincall_book(data, depth)
                    ts = data.get("ts")
                    books[symbol] = BookL5(
                        venue=self.name,
                        venue_symbol=symbol,
                        key=keys.get(symbol),
                        ts_exchange_ms=int(ts) if ts is not None else None,
                        bid_px=bid_px,
                        bid_sz=bid_sz,
                        ask_px=ask_px,
                        ask_sz=ask_sz,
                    )

                # Unsubscribe batches
                try:
                    for i in range(0, len(symbols), _BATCH):
                        batch = symbols[i : i + _BATCH]
                        await ws.send(
                            json.dumps(
                                {
                                    "action": "unSubscribe",
                                    "dataType": "orderBook",
                                    "payload": {"symbol": batch},
                                }
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"unsubscribe_failed:{exc}")

        except Exception as exc:  # noqa: BLE001
            errors.append(f"connect:{exc}")
            logger.exception("Coincall burst failed")

        stats = BurstStats(
            venue=self.name,
            n_instruments=len(symbols),
            n_with_update=len(books),
            duration_s=timer.elapsed(),
            peak_rss_mb=peak_rss_mb(),
            subscribe_errors=errors[:20],
            notes=notes,
            capture_lag_ms=round((time.time() - t_start) * 1000.0, 1),
        )
        if stats.coverage < 0.8:
            notes.append("coverage_below_80pct — check auth, batch limits, or rate limits")
            stats.notes = notes
        return books, stats
