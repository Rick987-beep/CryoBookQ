"""One-shot dual (or single) venue snapshot orchestration.

P0 hardening:
  - ``asyncio.gather(..., return_exceptions=True)`` so one venue failure
    does not discard the other.
  - Coverage quality gate before writing Parquet.
  - Disk abort threshold before write.
  - Part-file writes (see :class:`ParquetStore`).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

from cryobookq.capture.disk import DiskFullError, disk_free_mb
from cryobookq.capture.quality import QualityVerdict, evaluate_quality
from cryobookq.config import Settings, get_settings
from cryobookq.pipeline.match import match_raw_rows
from cryobookq.pipeline.normalize import books_to_raw_rows
from cryobookq.pipeline.score import score_pairs
from cryobookq.pipeline.write import ParquetStore
from cryobookq.types import BookL5
from cryobookq.venues.coincall import CoincallVenue
from cryobookq.venues.deribit import DeribitVenue
from cryobookq.venues._util import BurstStats

logger = logging.getLogger(__name__)


def fetch_btc_index() -> float:
    r = requests.get(
        "https://www.deribit.com/api/v2/public/get_index_price",
        params={"index_name": "btc_usd"},
        timeout=15,
    )
    r.raise_for_status()
    return float(r.json()["result"]["index_price"])


@dataclass
class SnapshotResult:
    ts_ms: int
    index_px: float | None
    venues: list[str]
    raw_rows: list[dict] = field(default_factory=list)
    score_rows: list[dict] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    raw_path: str | None = None
    scores_path: str | None = None
    quality: QualityVerdict | None = None
    wrote: bool = False


def _error_stats(venue: str, exc: BaseException, n_instruments: int = 0) -> BurstStats:
    return BurstStats(
        venue=venue,
        n_instruments=n_instruments,
        n_with_update=0,
        duration_s=0.0,
        peak_rss_mb=0.0,
        subscribe_errors=[f"{type(exc).__name__}:{exc}"],
        notes=["venue_exception"],
        capture_lag_ms=None,
    )


async def run_snapshot(
    venues: list[str] | None = None,
    *,
    settings: Settings | None = None,
    duration_s: float = 15.0,
    write: bool = True,
    force_write: bool = False,
) -> SnapshotResult:
    """Burst selected venues, normalize, match, score, optionally write Parquet.

    Parameters
    ----------
    force_write:
        If True, write even when the quality gate fails (debug only).
        Production daemons leave this False.
    """
    settings = settings or get_settings()
    venues = venues or ["deribit", "coincall"]
    depth = settings.depth
    store = ParquetStore(settings.data_dir, depth=depth, cadence_min=settings.snapshot_interval_min)

    free = disk_free_mb(settings.data_dir)
    if free != -1 and free < settings.disk_free_abort_mb:
        raise DiskFullError(
            f"disk free {free} MB < abort threshold {settings.disk_free_abort_mb} MB"
        )
    if free != -1 and free < settings.disk_free_warn_mb:
        logger.warning("Low disk: %d MB free (warn <%d)", free, settings.disk_free_warn_mb)

    index_px: float | None
    try:
        index_px = fetch_btc_index()
    except Exception as exc:  # noqa: BLE001
        logger.exception("index fetch failed")
        index_px = None
        if "deribit" in venues:
            # Cannot normalize Deribit BTC prices without index.
            raise RuntimeError(f"BTC index required for deribit normalize: {exc}") from exc

    ts_ms = int(time.time() * 1000)
    stats: dict[str, Any] = {"index_px": index_px, "disk_free_mb": free}

    # Build burst coroutines; instrument list failures become venue errors.
    labels: list[str] = []
    tasks: list[Any] = []
    n_inst: dict[str, int] = {}

    async def _burst_deribit() -> tuple[dict[str, BookL5], BurstStats]:
        d = DeribitVenue()
        inst = await asyncio.to_thread(d.list_instruments, settings.underlying)
        syms = [i.venue_symbol for i in inst]
        n_inst["deribit"] = len(syms)
        return await d.burst_books(syms, depth=depth, duration_s=duration_s)

    async def _burst_coincall() -> tuple[dict[str, BookL5], BurstStats]:
        c = CoincallVenue(settings)
        inst = await asyncio.to_thread(c.list_instruments, settings.underlying)
        syms = [i.venue_symbol for i in inst]
        n_inst["coincall"] = len(syms)
        return await c.burst_books(syms, depth=depth, duration_s=duration_s)

    if "deribit" in venues:
        labels.append("deribit")
        tasks.append(_burst_deribit())
    if "coincall" in venues:
        labels.append("coincall")
        tasks.append(_burst_coincall())

    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    venue_stats: dict[str, dict[str, Any]] = {}
    books_by_venue: dict[str, dict[str, BookL5]] = {}

    for label, result in zip(labels, gathered, strict=True):
        if isinstance(result, BaseException):
            logger.exception("Venue %s failed", label, exc_info=result)
            bs = _error_stats(label, result, n_inst.get(label, 0))
            d = bs.to_dict()
            d["error"] = f"{type(result).__name__}:{result}"
            d["coverage"] = 0.0
            venue_stats[label] = d
            stats[label] = d
            continue

        books, burst_stats = result
        books_by_venue[label] = books
        d = burst_stats.to_dict()
        d["n_instruments"] = n_inst.get(label, burst_stats.n_instruments)
        venue_stats[label] = d
        stats[label] = d
        stats[f"{label}_n_instruments"] = d["n_instruments"]

    floors = {
        "deribit": settings.coverage_floor_deribit,
        "coincall": settings.coverage_floor_coincall,
    }
    quality = evaluate_quality(venue_stats, requested=labels, floors=floors)
    stats["quality"] = quality.to_dict()

    # Normalize only venues that produced books and (for deribit) have index.
    raw_rows: list[dict] = []
    assert index_px is not None or "deribit" not in books_by_venue
    for label, books in books_by_venue.items():
        st = venue_stats[label]
        # Skip normalizing a venue that failed its own floor when peer exists?
        # Keep rows for any venue that returned books — analytics can filter.
        # Gate only controls whether we *persist*.
        if not books:
            continue
        if index_px is None:
            continue
        raw_rows.extend(
            books_to_raw_rows(
                books,
                ts_ms=ts_ms,
                index_px=index_px,
                capture_lag_ms=st.get("capture_lag_ms"),
            )
        )

    pairs = match_raw_rows(raw_rows)
    score_rows = score_pairs(pairs, ts_ms=ts_ms) if pairs else []
    matched = sum(1 for p in pairs if p.match_status == "matched")
    stats["n_raw"] = len(raw_rows)
    stats["n_pairs"] = len(pairs)
    stats["n_matched"] = matched
    stats["match_rate"] = matched / len(pairs) if pairs else 0.0
    stats["ts_iso"] = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()

    # Persist when at least one requested venue met its coverage floor
    # (partial success is valuable). Never write if none met the floor.
    floors_met = [
        v
        for v in labels
        if v not in quality.venue_errors
        and quality.coverages.get(v, 0.0) >= floors.get(v, 0.8)
    ]
    can_write = bool(raw_rows) and (force_write or bool(floors_met))

    raw_path = scores_path = None
    wrote = False
    if write and can_write:
        extra = {
            "quality_ok": str(quality.ok).lower(),
            "incomplete": str(quality.incomplete).lower(),
        }
        raw_path = str(store.write_raw_books(raw_rows, ts_ms, extra=extra))
        if score_rows:
            scores_path = str(store.write_pair_scores(score_rows, ts_ms, extra=extra))
        wrote = True
    elif write and not can_write:
        logger.warning(
            "Skipping parquet write (quality gate): %s",
            "; ".join(quality.reasons) or "unknown",
        )

    stats["wrote"] = wrote
    return SnapshotResult(
        ts_ms=ts_ms,
        index_px=index_px,
        venues=labels,
        raw_rows=raw_rows,
        score_rows=score_rows,
        stats=stats,
        raw_path=raw_path,
        scores_path=scores_path,
        quality=quality,
        wrote=wrote,
    )
