#!/usr/bin/env python3
"""M0 spike: Deribit full-chain L5 book burst (~15s).

Usage:
  .venv/bin/python tools/spike_deribit_books.py
  .venv/bin/python tools/spike_deribit_books.py --duration 20 --out tmp/deribit_spike.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.config import get_settings
from cryobookq.venues.deribit import DeribitVenue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("spike_deribit")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("tmp/deribit_spike.json"))
    parser.add_argument("--limit", type=int, default=0, help="Cap instruments (0=all)")
    args = parser.parse_args()

    settings = get_settings()
    venue = DeribitVenue()
    instruments = venue.list_instruments(settings.underlying)
    symbols = [i.venue_symbol for i in instruments]
    if args.limit > 0:
        symbols = symbols[: args.limit]
    logger.info("Listed %d %s options; bursting %d for %.1fs", len(instruments), settings.underlying, len(symbols), args.duration)

    books, stats = await venue.burst_books(symbols, depth=args.depth, duration_s=args.duration)
    logger.info(
        "coverage=%.1f%% (%d/%d) peak_rss=%.0fMB errors=%d",
        100 * stats.coverage,
        stats.n_with_update,
        stats.n_instruments,
        stats.peak_rss_mb,
        len(stats.subscribe_errors),
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stats": stats.to_dict(),
        "books": {k: v.to_dict() for k, v in books.items()},
    }
    args.out.write_text(json.dumps(payload, indent=2))
    logger.info("Wrote %s", args.out)
    return 0 if stats.coverage >= 0.9 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
