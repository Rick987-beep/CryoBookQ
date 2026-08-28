"""Measure WS catalogue growth (books / two-sided) at 10s marks.

Runs venues in parallel for ~60s of listen. Binance is WS-only (no REST/ticker)
so the curve is comparable. Coincall is skipped without API keys.

    .venv/bin/python tools/measure_catalogue_growth.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.config import get_settings
from cryobookq.venues._util import BurstStats, catalogue_series
from cryobookq.venues.binance import BinanceVenue
from cryobookq.venues.bybit import BybitVenue
from cryobookq.venues.coincall import CoincallVenue
from cryobookq.venues.deribit import DeribitVenue
from cryobookq.venues.okx import OkxVenue


TMP = ROOT / "tmp" / "live"
LOG_PATH = TMP / "catalogue_growth.log"
OUT_PATH = TMP / "catalogue_growth.json"
DURATION_S = 60.0


def _setup_logging() -> logging.Logger:
    TMP.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    root.handlers.clear()
    root.addHandler(sh)
    root.addHandler(fh)
    return logging.getLogger("measure_catalogue")


def _row(stats: BurstStats) -> dict[str, Any]:
    series = catalogue_series(stats.notes)
    two = None
    for phase, n, total in series:
        if phase == "ws_done":
            two = n  # overwritten below with real two_sided from logs; keep n as books
            break
    return {
        "venue": stats.venue,
        "n_instruments": stats.n_instruments,
        "n_with_update": stats.n_with_update,
        "coverage": round(stats.coverage, 4),
        "duration_s": round(stats.duration_s, 2),
        "series": [{"phase": p, "books": n, "n": tot, "pct": round(100.0 * n / tot, 1) if tot else 0.0} for p, n, tot in series],
        "notes": stats.notes,
        "errors": stats.subscribe_errors[:5],
        "two_sided_done": two,
    }


async def _burst(name: str, venue: Any, symbols: list[str]) -> tuple[str, BurstStats]:
    books, stats = await venue.burst_books(symbols, depth=5, duration_s=DURATION_S)
    two = sum(1 for b in books.values() if b.two_sided)
    stats.notes.append(f"two_sided_final={two}/{len(symbols)}")
    return name, stats


async def _run() -> int:
    log = _setup_logging()
    settings = get_settings()
    venues: dict[str, Any] = {
        "deribit": DeribitVenue(),
        "bybit": BybitVenue(),
        "okx": OkxVenue(),
        "binance": BinanceVenue(rest_budget_s=0.0),
    }
    if settings.has_coincall_creds:
        venues["coincall"] = CoincallVenue(settings)
    else:
        log.warning("skip coincall (no API keys)")

    log.info("listing instruments for %s", list(venues))
    symbols: dict[str, list[str]] = {}
    for name, venue in venues.items():
        inst = await asyncio.to_thread(venue.list_instruments, "BTC")
        symbols[name] = [i.venue_symbol for i in inst]
        log.info("%s listed n=%d", name, len(symbols[name]))

    log.info("WS listen %.0fs (parallel)", DURATION_S)
    t0 = time.perf_counter()
    gathered = await asyncio.gather(
        *[_burst(name, venues[name], symbols[name]) for name in venues],
        return_exceptions=True,
    )
    elapsed = time.perf_counter() - t0

    rows: dict[str, Any] = {}
    for item in gathered:
        if isinstance(item, BaseException):
            log.exception("venue failed: %s", item)
            continue
        name, stats = item
        rows[name] = _row(stats)
        rows[name]["two_sided_final"] = next(
            (n.split("=", 1)[1] for n in stats.notes if n.startswith("two_sided_final=")),
            None,
        )
        log.info(
            "%s coverage=%.1f%% books=%s/%s duration=%.1fs series=%s",
            name,
            100.0 * stats.coverage,
            stats.n_with_update,
            stats.n_instruments,
            stats.duration_s,
            catalogue_series(stats.notes),
        )

    payload = {"elapsed_s": round(elapsed, 1), "duration_s": DURATION_S, "venues": rows}
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    log.info("wrote %s elapsed=%.1fs", OUT_PATH, elapsed)
    log.info("log=%s", LOG_PATH)
    return 0 if rows else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
