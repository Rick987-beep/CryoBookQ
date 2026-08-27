"""CryoBookQ forever daemon / one-shot snapshot entrypoint.

P0 loop semantics (tickrecorder-inspired):
  1. Compute next UTC boundary strictly after last *committed* slot.
  2. Sleep until lead-open.
  3. **Commit the boundary before attempting capture** — never re-open it.
  4. Run snapshot (venues isolated; quality gate; part-file parquet).
  5. Update health; on failure/incomplete count a gap and wait for the *next* slot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import UTC, datetime

import pandas as pd

from cryobookq.analytics import summarize_snapshot
from cryobookq.capture.disk import DiskFullError
from cryobookq.capture.scheduler import BoundaryTracker
from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import get_settings
from cryobookq.daemon.health import HEALTH, start_health_server

logger = logging.getLogger(__name__)


def _parse_venues(s: str) -> list[str]:
    return [v.strip() for v in s.split(",") if v.strip()]


def _record_result(result) -> None:  # SnapshotResult
    q = result.quality
    if q is not None and q.ok and result.wrote:
        HEALTH.record_success(result.ts_ms, result.stats, wrote=True)
        return
    reason = "; ".join(q.reasons) if q and q.reasons else "incomplete_or_no_write"
    if q is not None and (q.incomplete or not result.wrote):
        HEALTH.record_incomplete(
            result.ts_ms,
            result.stats,
            wrote=result.wrote,
            reason=reason,
        )
    else:
        HEALTH.record_failure(reason)
        HEALTH.record_gap()


async def run_once(venues: list[str], duration_s: float, print_summary: bool = True) -> int:
    settings = get_settings()
    HEALTH.data_dir = str(settings.data_dir)
    HEALTH.disk_free_warn_mb = settings.disk_free_warn_mb
    logger.info("Snapshot --once venues=%s duration=%.1fs data_dir=%s", venues, duration_s, settings.data_dir)
    try:
        result = await run_snapshot(venues, settings=settings, duration_s=duration_s, write=True)
        _record_result(result)
    except DiskFullError as exc:
        HEALTH.record_failure(str(exc))
        HEALTH.record_gap()
        logger.error("%s", exc)
        return 2
    except Exception as exc:  # noqa: BLE001
        HEALTH.record_failure(str(exc))
        HEALTH.record_gap()
        logger.exception("Snapshot failed")
        return 1

    summary = summarize_snapshot(pd.DataFrame(result.score_rows)) if result.score_rows else {"n": 0}
    payload = {
        "stats": result.stats,
        "summary": summary,
        "quality": result.quality.to_dict() if result.quality else None,
        "wrote": result.wrote,
        "raw_path": result.raw_path,
        "scores_path": result.scores_path,
    }
    if print_summary:
        print(json.dumps(payload, indent=2, default=str))
    return 0 if (result.quality and result.quality.ok and result.wrote) else 2


async def run_loop(venues: list[str], duration_s: float, lead_s: float = 12.0) -> None:
    settings = get_settings()
    HEALTH.data_dir = str(settings.data_dir)
    HEALTH.disk_free_warn_mb = settings.disk_free_warn_mb
    start_health_server(HEALTH, port=settings.health_port)

    tracker = BoundaryTracker(interval_min=settings.snapshot_interval_min)
    stop = asyncio.Event()

    def _stop(*_args: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop.set())

    logger.info(
        "Daemon loop interval=%dmin venues=%s health=:%d",
        settings.snapshot_interval_min,
        venues,
        settings.health_port,
    )

    while not stop.is_set():
        now = datetime.now(tz=UTC)
        open_at, boundary = tracker.next_slot(now, lead_s=lead_s)
        wait = (open_at - datetime.now(tz=UTC)).total_seconds()
        if wait > 0:
            logger.info(
                "Sleeping %.1fs until lead-open %s (boundary %s)",
                wait,
                open_at.isoformat(),
                boundary.isoformat(),
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
                break
            except TimeoutError:
                pass

        # Commit *before* the attempt — slot is spent even if capture fails.
        tracker.commit(boundary)
        logger.info("Committed boundary %s — starting capture", boundary.isoformat())

        try:
            rem = (boundary - datetime.now(tz=UTC)).total_seconds() + 2.0
            dur = max(duration_s, rem)
            result = await run_snapshot(venues, settings=settings, duration_s=dur, write=True)
            _record_result(result)
            logger.info(
                "Snapshot done wrote=%s quality_ok=%s matched=%s/%s reasons=%s",
                result.wrote,
                result.quality.ok if result.quality else None,
                result.stats.get("n_matched"),
                result.stats.get("n_pairs"),
                list(result.quality.reasons) if result.quality else [],
            )
        except DiskFullError as exc:
            HEALTH.record_failure(str(exc))
            HEALTH.record_gap()
            logger.error("Disk abort: %s — waiting for next boundary", exc)
        except Exception as exc:  # noqa: BLE001
            HEALTH.record_failure(str(exc))
            HEALTH.record_gap()
            logger.exception("Snapshot failed; slot already committed — next boundary only")

        # Small yield so we never spin if clock/boundary math is weird.
        await asyncio.sleep(0.5)


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
