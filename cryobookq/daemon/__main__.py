"""CryoBookQ forever daemon / one-shot snapshot entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import UTC, datetime

from cryobookq.analytics import summarize_snapshot
from cryobookq.capture.scheduler import lead_open, next_boundary
from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import get_settings
from cryobookq.daemon.health import HEALTH

logger = logging.getLogger(__name__)


def _parse_venues(s: str) -> list[str]:
    return [v.strip() for v in s.split(",") if v.strip()]


async def run_once(venues: list[str], duration_s: float, print_summary: bool = True) -> int:
    settings = get_settings()
    logger.info("Snapshot --once venues=%s duration=%.1fs data_dir=%s", venues, duration_s, settings.data_dir)
    try:
        result = await run_snapshot(venues, settings=settings, duration_s=duration_s, write=True)
        HEALTH.record_success(result.ts_ms, result.stats)
    except Exception as exc:  # noqa: BLE001
        HEALTH.record_failure(str(exc))
        logger.exception("Snapshot failed")
        return 1

    summary = summarize_snapshot(
        __import__("pandas").DataFrame(result.score_rows)
    )
    payload = {
        "stats": result.stats,
        "summary": summary,
        "raw_path": result.raw_path,
        "scores_path": result.scores_path,
    }
    if print_summary:
        print(json.dumps(payload, indent=2, default=str))
    return 0


async def run_loop(venues: list[str], duration_s: float, lead_s: float = 12.0) -> None:
    settings = get_settings()
    interval = settings.snapshot_interval_min
    stop = asyncio.Event()

    def _stop(*_args: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop.set())

    logger.info("Daemon loop interval=%dmin venues=%s", interval, venues)
    while not stop.is_set():
        now = datetime.now(tz=UTC)
        boundary = next_boundary(now, interval)
        open_at = lead_open(boundary, lead_s)
        wait = (open_at - now).total_seconds()
        if wait > 0:
            logger.info("Sleeping %.1fs until lead-open %s (boundary %s)", wait, open_at.isoformat(), boundary.isoformat())
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
                break
            except TimeoutError:
                pass
        try:
            # Align duration so we roughly cover through the boundary
            rem = (boundary - datetime.now(tz=UTC)).total_seconds() + 2.0
            dur = max(duration_s, rem)
            result = await run_snapshot(venues, settings=settings, duration_s=dur, write=True)
            HEALTH.record_success(result.ts_ms, result.stats)
            logger.info(
                "Snapshot ok matched=%s/%s rate=%.2f",
                result.stats.get("n_matched"),
                result.stats.get("n_pairs"),
                result.stats.get("match_rate", 0),
            )
        except Exception as exc:  # noqa: BLE001
            HEALTH.record_failure(str(exc))
            HEALTH.record_gap()
            logger.exception("Snapshot failed; counting gap")
        # Avoid double-fire in the same boundary second
        await asyncio.sleep(1.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cryobookq.daemon", description="CryoBookQ snapshot daemon")
    parser.add_argument("--once", action="store_true", help="Single snapshot then exit")
    parser.add_argument("--venues", default="deribit,coincall", help="Comma-separated venues")
    parser.add_argument("--duration", type=float, default=15.0, help="Burst window seconds")
    parser.add_argument("--lead", type=float, default=12.0, help="Seconds before boundary to open burst")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    venues = _parse_venues(args.venues)
    if args.once:
        return asyncio.run(run_once(venues, args.duration))
    asyncio.run(run_loop(venues, args.duration, lead_s=args.lead))
    return 0


if __name__ == "__main__":
    sys.exit(main())
