#!/usr/bin/env python3
"""Live end-to-end: dual snapshot → score → print summary (SPEC acceptance queries)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.analytics import summarize_snapshot, who_wins
from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("live_score")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=18.0)
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    if args.data_dir:
        from cryobookq.config import Settings

        settings = Settings(
            underlying=settings.underlying,
            depth=settings.depth,
            snapshot_interval_min=settings.snapshot_interval_min,
            data_dir=args.data_dir,
            hub_port=settings.hub_port,
            coincall_api_key=settings.coincall_api_key,
            coincall_api_secret=settings.coincall_api_secret,
            coincall_env=settings.coincall_env,
        )

    if not settings.has_coincall_creds:
        logger.error("Need COINCALL_API_KEY/SECRET in .env")
        return 1

    result = await run_snapshot(
        ["deribit", "coincall"],
        settings=settings,
        duration_s=args.duration,
        write=True,
    )
    df = pd.DataFrame(result.score_rows)
    summary = summarize_snapshot(df)

    # SPEC acceptance-style queries
    queries = {
        "who_wins_composite_all": who_wins(df, metric="winner_composite").attrs.get("win_rate", {}),
        "who_wins_spread_US": who_wins(df, metric="winner_spread", session="US").attrs.get("win_rate", {}),
        "who_wins_cost_buy_US": who_wins(df, metric="winner_cost_buy", session="US").attrs.get("win_rate", {}),
        "two_sided_0_2_dte": {
            "deribit": float(
                df[(df["dte_bucket"] == "0-2") & (df["match_status"] == "matched")]["deribit_two_sided"].mean()
            )
            if len(df[df["dte_bucket"] == "0-2"])
            else None,
            "coincall": float(
                df[(df["dte_bucket"] == "0-2") & (df["match_status"] == "matched")]["coincall_two_sided"].mean()
            )
            if len(df[df["dte_bucket"] == "0-2"])
            else None,
        },
    }

    out = {
        "stats": result.stats,
        "summary": summary,
        "queries": queries,
        "raw_path": result.raw_path,
        "scores_path": result.scores_path,
    }
    print(json.dumps(out, indent=2, default=str))
    ok = result.stats.get("match_rate", 0) >= 0.85 and summary.get("n_matched", 0) > 500
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
