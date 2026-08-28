#!/usr/bin/env python3
"""Hardened interval soak: N snapshots on a fixed cadence with slot commit.

Example (1 minute, every 15s → 4 snaps, all public venues)::

    .venv/bin/python tools/soak_interval.py --total 60 --interval 15 --duration 12 --relaxed-floors
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.analytics import summarize_snapshot, who_wins
from cryobookq.analytics.scorecard import build_scorecard_from_store, format_scorecard
from cryobookq.capture.clock import CLOCK
from cryobookq.capture.scheduler import IntervalSlotTracker
from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import get_settings
from cryobookq.daemon.health import HEALTH, start_health_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("soak_interval")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--total", type=float, default=60.0, help="Total wall seconds")
    parser.add_argument("--interval", type=float, default=15.0, help="Seconds between slot opens")
    parser.add_argument("--duration", type=float, default=10.0, help="Burst seconds per snap")
    parser.add_argument("--data-dir", type=Path, default=Path("tmp/soak_interval"))
    parser.add_argument("--venues", default="", help="Comma list; default all public + coincall if creds")
    parser.add_argument("--html-out", type=Path, default=None)
    parser.add_argument("--relaxed-floors", action="store_true", help="Lower non-hub floors for short bursts")
    parser.add_argument("--health-port", type=int, default=0, help="0 = pick ephemeral")
    args = parser.parse_args()

    base = get_settings()
    venues = [v.strip() for v in args.venues.split(",") if v.strip()]
    if not venues:
        venues = ["deribit", "bybit", "okx", "binance"]
        if base.has_coincall_creds:
            venues.insert(1, "coincall")
    if "coincall" in venues and not base.has_coincall_creds:
        logger.error("Need COINCALL creds for coincall")
        return 1

    if args.data_dir.exists():
        shutil.rmtree(args.data_dir)
    args.data_dir.mkdir(parents=True)

    extra: dict = {
        "data_dir": args.data_dir,
        "burst_timeout_s": max(base.burst_timeout_s, args.duration + 28),
    }
    if args.relaxed_floors:
        extra["coverage_floor_bybit"] = 0.30
        extra["coverage_floor_okx"] = 0.30
        extra["coverage_floor_binance"] = 0.30
        extra["coverage_floor_coincall"] = min(base.coverage_floor_coincall, 0.50)
    settings = replace(base, **extra)
    HEALTH.data_dir = str(settings.data_dir)
    HEALTH.disk_free_warn_mb = settings.disk_free_warn_mb

    try:
        await asyncio.to_thread(CLOCK.sync)
        HEALTH.clock = CLOCK.to_dict()
        logger.info("Clock synced offset=%+.3fs", CLOCK.offset_s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Clock sync skipped: %s", exc)

    import socket

    port = args.health_port
    if port <= 0:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
    start_health_server(HEALTH, port=port)
    logger.info("Health at http://127.0.0.1:%d/health", port)

    n_slots = int(args.total // args.interval)
    epoch = time.monotonic()
    tracker = IntervalSlotTracker(interval_s=args.interval, epoch_monotonic=epoch)
    per = []

    for _ in range(n_slots):
        now_m = time.monotonic()
        fire_at, idx = tracker.next_slot(now_m)
        wait = fire_at - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        tracker.commit(idx)  # spend slot before attempt
        logger.info("=== slot %d/%d committed — bursting %.1fs ===", idx + 1, n_slots, args.duration)
        try:
            result = await run_snapshot(
                venues,
                settings=settings,
                duration_s=args.duration,
                write=True,
            )
            q = result.quality
            if q and q.ok and result.wrote:
                HEALTH.record_success(result.ts_ms, result.stats, wrote=True)
            else:
                reason = "; ".join(q.reasons) if q else "unknown"
                HEALTH.record_incomplete(
                    result.ts_ms, result.stats, wrote=result.wrote, reason=reason, gap=not (q and q.ok)
                )
            row = {
                "slot": idx + 1,
                "elapsed_s": round(time.monotonic() - epoch, 2),
                "ts_iso": result.stats.get("ts_iso"),
                "wrote": result.wrote,
                "quality_ok": q.ok if q else None,
                "reasons": list(q.reasons) if q else [],
                "match_rate": result.stats.get("match_rate"),
                "n_matched": result.stats.get("n_matched"),
                "deribit_coverage": (result.stats.get("deribit") or {}).get("coverage"),
                "coincall_coverage": (result.stats.get("coincall") or {}).get("coverage"),
                "bybit_coverage": (result.stats.get("bybit") or {}).get("coverage"),
                "okx_coverage": (result.stats.get("okx") or {}).get("coverage"),
                "binance_coverage": (result.stats.get("binance") or {}).get("coverage"),
                "raw_path": result.raw_path,
                "scores_path": result.scores_path,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("slot %d failed", idx)
            HEALTH.record_failure(str(exc))
            HEALTH.record_gap()
            row = {"slot": idx + 1, "error": str(exc), "elapsed_s": round(time.monotonic() - epoch, 2)}
        per.append(row)
        logger.info("%s", json.dumps(row))

    from cryobookq.pipeline.write import ParquetStore

    store = ParquetStore(args.data_dir)
    df = store.load_pair_scores()
    summary = summarize_snapshot(df) if len(df) else {"n_rows": 0}

    period_card = None
    period_report = None
    try:
        period_card = build_scorecard_from_store(args.data_dir)
        period_report = format_scorecard(period_card)
        print(period_report)
        print()
        (args.data_dir / "scorecard_period.json").write_text(
            json.dumps(period_card.to_dict(), indent=2, default=str)
        )
        from cryobookq.analytics.html_report import write_scorecard_html

        html_dest = args.html_out or (args.data_dir / "scorecard.html")
        html_path = write_scorecard_html(period_card, html_dest)
        logger.info("Wrote HTML scorecard %s", html_path)
    except ValueError as exc:
        logger.warning("Period scorecard skipped: %s", exc)

    out = {
        "config": {
            "total_s": args.total,
            "interval_s": args.interval,
            "burst_s": args.duration,
            "n_slots": n_slots,
            "wall_s": round(time.monotonic() - epoch, 2),
            "data_dir": str(args.data_dir),
            "health_port": port,
        },
        "health": HEALTH.as_dict(),
        "per_slot": per,
        "aggregate": summary,
        "scorecard_period": {
            "overall": period_card.overall if period_card else None,
            "meta": period_card.meta if period_card else None,
            "n_snapshots": (period_card.meta.get("n_snapshots") if period_card else 0),
        },
        "queries": {
            "composite": who_wins(df, metric="winner_composite").attrs.get("win_rate", {})
            if len(df)
            else {},
            "by_dte": summary.get("by_dte_composite", {}),
        },
        "n_score_rows": int(len(df)),
        "n_part_files": len(list(args.data_dir.glob("pair_scores/date=*/part-*.parquet"))),
    }
    out_path = args.data_dir / "summary.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))
    logger.info("Wrote %s", out_path)
    wrote_ok = all(p.get("wrote") for p in per if "error" not in p)
    scorecard_ok = period_card is not None and int(period_card.meta.get("n_snapshots") or 0) >= 1
    return 0 if wrote_ok and scorecard_ok and per else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
