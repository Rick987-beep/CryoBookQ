"""One-shot dual (or single) venue snapshot orchestration.

P0/P1 hardening:
  - Venue isolation via ``gather(..., return_exceptions=True)``.
  - Coverage quality gate + disk abort.
  - Part-file parquet writes.
  - Instrument cache (30‑min TTL, stale-on-failure).
  - Blocking REST (index, instruments) via ``asyncio.to_thread``.
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
from cryobookq.capture.instruments import INSTRUMENTS, InstrumentCache
from cryobookq.capture.quality import QualityVerdict, evaluate_quality
from cryobookq.config import Settings, get_settings
from cryobookq.pipeline.greeks import fetch_deribit_deltas
from cryobookq.pipeline.match import match_raw_rows
from cryobookq.pipeline.normalize import books_to_raw_rows
from cryobookq.pipeline.score import score_pairs
from cryobookq.pipeline.write import ParquetStore
from cryobookq.types import BookL5
from cryobookq.venues._util import BurstStats
from cryobookq.venues.registry import make_venue
from cryobookq.venues.spec import SPECS
from cryobookq.analytics.scorecard import build_scorecard

logger = logging.getLogger(__name__)


def fetch_btc_index() -> float:
    """Blocking Deribit index REST — call via ``asyncio.to_thread`` from async code."""
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
    scorecard: dict[str, Any] | None = None


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
    instrument_cache: InstrumentCache | None = None,
) -> SnapshotResult:
    """Burst selected venues, normalize, match, score, optionally write Parquet."""
    settings = settings or get_settings()
    venues = venues or ["deribit", "coincall"]
    depth = settings.depth
    cache = instrument_cache or INSTRUMENTS
    if cache.ttl_s != settings.instrument_cache_ttl_s:
        cache.ttl_s = settings.instrument_cache_ttl_s
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
        index_px = await asyncio.to_thread(fetch_btc_index)
    except Exception:  # noqa: BLE001
        logger.exception("index fetch failed")
        index_px = None

    ts_ms = int(time.time() * 1000)
    stats: dict[str, Any] = {"index_px": index_px, "disk_free_mb": free}
    inst_meta: dict[str, Any] = {}

    labels: list[str] = list(venues)
    n_inst: dict[str, int] = {}
    timeout_s = float(settings.burst_timeout_s)

    async def _burst_one(name: str) -> tuple[dict[str, BookL5], BurstStats]:
        venue = make_venue(name, settings)

        def _load() -> tuple[list, dict]:
            return cache.get(name, settings.underlying, instance=venue)

        inst, meta = await asyncio.to_thread(_load)
        inst_meta[name] = meta
        spec = SPECS.get(name)
        if index_px is None and spec is not None and spec.price_ccy == "BTC":
            raise RuntimeError(f"BTC index required to normalize {name}")
        syms = [i.venue_symbol for i in inst]
        n_inst[name] = len(syms)
        return await venue.burst_books(syms, depth=depth, duration_s=duration_s)

    async def _isolated(name: str) -> tuple[dict[str, BookL5], BurstStats] | BaseException:
        try:
            return await asyncio.wait_for(_burst_one(name), timeout=timeout_s)
        except TimeoutError as exc:
            logger.error("Venue %s timed out after %.1fs", name, timeout_s)
            return exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("Venue %s failed", name)
            return exc

    gathered = await asyncio.gather(*[_isolated(n) for n in labels], return_exceptions=True)

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
        if label in inst_meta:
            d["instruments"] = inst_meta[label]
        venue_stats[label] = d
        stats[label] = d
        stats[f"{label}_n_instruments"] = d["n_instruments"]

    floors = settings.coverage_floors()
    quality = evaluate_quality(venue_stats, requested=labels, floors=floors)
    stats["quality"] = quality.to_dict()
    stats["instruments"] = inst_meta

    # Attach Deribit BS deltas (canonical) so landmark scorecard can select by |Δ|.
    try:
        deltas = await asyncio.to_thread(
            fetch_deribit_deltas, settings.underlying, now_ms=ts_ms
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Delta enrichment failed: %s", exc)
        deltas = {}
    n_delta = 0
    for books in books_by_venue.values():
        for book in books.values():
            if book.key is not None and book.key in deltas:
                book.delta = deltas[book.key]
                n_delta += 1
    stats["deltas_enriched"] = n_delta
    stats["deltas_available"] = len(deltas)

    raw_rows: list[dict] = []
    norm_index = index_px if index_px is not None else 1.0
    for label, books in books_by_venue.items():
        st = venue_stats[label]
        spec = SPECS.get(label)
        if spec is not None and spec.price_ccy == "BTC" and index_px is None:
            logger.warning("Skipping %s rows: no BTC index", label)
            continue
        floor = floors.get(label, 0.8)
        met = (
            label not in quality.venue_errors
            and float(st.get("coverage") or 0.0) >= floor
        )
        if not books or (not met and not force_write):
            continue
        raw_rows.extend(
            books_to_raw_rows(
                books,
                ts_ms=ts_ms,
                index_px=norm_index,
                capture_lag_ms=st.get("capture_lag_ms"),
            )
        )

    pairs = match_raw_rows(raw_rows)
    score_rows = score_pairs(pairs, ts_ms=ts_ms) if pairs else []
    scorecard_obj = build_scorecard(pairs, ts_ms=ts_ms) if pairs else None
    scorecard = scorecard_obj.to_dict() if scorecard_obj else None
    matched = sum(1 for p in pairs if p.match_status == "matched")
    n_hub = sum(1 for p in pairs if p.has_hub)
    stats["n_raw"] = len(raw_rows)
    stats["n_pairs"] = len(pairs)
    stats["n_matched"] = matched
    stats["n_hub"] = n_hub
    stats["match_rate"] = matched / len(pairs) if pairs else 0.0
    stats["ts_iso"] = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()
    if scorecard_obj is not None:
        stats["scorecard_overall"] = dict(scorecard_obj.overall)

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
        scorecard=scorecard,
    )
