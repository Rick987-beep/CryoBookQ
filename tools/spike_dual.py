#!/usr/bin/env python3
"""M0 dual spike: Deribit + Coincall at the same wall-clock window.

Usage:
  .venv/bin/python tools/spike_dual.py --duration 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.config import get_settings
from cryobookq.venues.coincall import CoincallVenue
from cryobookq.venues.deribit import DeribitVenue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("spike_dual")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--outdir", type=Path, default=Path("tmp"))
    args = parser.parse_args()

    settings = get_settings()
    deribit = DeribitVenue()
    coincall = CoincallVenue(settings)

    d_inst = deribit.list_instruments(settings.underlying)
    c_inst = coincall.list_instruments(settings.underlying)
    d_syms = [i.venue_symbol for i in d_inst]
    c_syms = [i.venue_symbol for i in c_inst]
    logger.info("instruments deribit=%d coincall=%d; dual burst %.1fs", len(d_syms), len(c_syms), args.duration)

    t0 = time.time()
    (d_books, d_stats), (c_books, c_stats) = await asyncio.gather(
        deribit.burst_books(d_syms, depth=args.depth, duration_s=args.duration),
        coincall.burst_books(c_syms, depth=args.depth, duration_s=args.duration),
    )
    wall = time.time() - t0
    logger.info(
        "done wall=%.1fs deribit=%.1f%% coincall=%.1f%%",
        wall,
        100 * d_stats.coverage,
        100 * c_stats.coverage,
    )

    args.outdir.mkdir(parents=True, exist_ok=True)
    summary = {
        "wall_s": wall,
        "started_unix": t0,
        "deribit": d_stats.to_dict(),
        "coincall": c_stats.to_dict(),
    }
    (args.outdir / "dual_spike_summary.json").write_text(json.dumps(summary, indent=2))
    (args.outdir / "deribit_spike.json").write_text(
        json.dumps({"stats": d_stats.to_dict(), "books": {k: v.to_dict() for k, v in d_books.items()}}, indent=2)
    )
    (args.outdir / "coincall_spike.json").write_text(
        json.dumps({"stats": c_stats.to_dict(), "books": {k: v.to_dict() for k, v in c_books.items()}}, indent=2)
    )
    logger.info("Wrote dumps under %s", args.outdir)
    ok = d_stats.coverage >= 0.9 and c_stats.coverage >= 0.8
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
