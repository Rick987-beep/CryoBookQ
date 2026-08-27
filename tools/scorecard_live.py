#!/usr/bin/env python3
"""Live acceptance: dual snapshot → landmark scorecard report.

Example::

    .venv/bin/python tools/scorecard_live.py --duration 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.analytics.scorecard import format_scorecard
from cryobookq.analytics.scorecard import ScorecardResult
from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("scorecard_live")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--data-dir", type=Path, default=Path("tmp/scorecard_live"))
    parser.add_argument("--json-out", type=Path, default=None, help="Write full scorecard JSON")
    args = parser.parse_args()

    base = get_settings()
    if not base.has_coincall_creds:
        logger.error("Need COINCALL_API_KEY/SECRET in .env")
        return 1

    settings = replace(base, data_dir=args.data_dir)
    args.data_dir.mkdir(parents=True, exist_ok=True)

    result = await run_snapshot(
        ["deribit", "coincall"],
        settings=settings,
        duration_s=args.duration,
        write=True,
    )
    if not result.scorecard:
        logger.error("No scorecard produced (empty pairs?)")
        return 2

    card = ScorecardResult(
        ts_ms=result.scorecard["ts_ms"],
        venues=result.scorecard["venues"],
        grid=result.scorecard["grid"],
        wings=result.scorecard["wings"],
        presence=result.scorecard["presence"],
        overall=result.scorecard["overall"],
        landmarks=result.scorecard["landmarks"],
        meta=result.scorecard["meta"],
    )
    report = format_scorecard(card)
    print(report)
    print()
    print(
        json.dumps(
            {
                "wrote": result.wrote,
                "quality_ok": result.quality.ok if result.quality else None,
                "match_rate": result.stats.get("match_rate"),
                "deltas_enriched": result.stats.get("deltas_enriched"),
                "overall": result.scorecard["overall"],
                "raw_path": result.raw_path,
                "scores_path": result.scores_path,
            },
            indent=2,
        )
    )

    out = args.json_out or (args.data_dir / "scorecard.json")
    out.write_text(json.dumps(result.scorecard, indent=2, default=str))
    logger.info("Wrote %s", out)

    # Acceptance: deltas present, both venues scored, at least one grid cell used
    ok = (
        (result.stats.get("deltas_enriched") or 0) > 100
        and len(card.overall) >= 2
        and any(c["n_targets_used"] > 0 for c in card.grid.values())
        and result.wrote
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
