"""One-shot dual (or single) venue snapshot orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

from cryobookq.config import Settings, get_settings
from cryobookq.pipeline.match import match_raw_rows
from cryobookq.pipeline.normalize import books_to_raw_rows
from cryobookq.pipeline.score import score_pairs
from cryobookq.pipeline.write import ParquetStore
from cryobookq.venues.coincall import CoincallVenue
from cryobookq.venues.deribit import DeribitVenue

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
    index_px: float
    venues: list[str]
    raw_rows: list[dict] = field(default_factory=list)
    score_rows: list[dict] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    raw_path: str | None = None
    scores_path: str | None = None


async def run_snapshot(
    venues: list[str] | None = None,
    *,
    settings: Settings | None = None,
    duration_s: float = 15.0,
    write: bool = True,
) -> SnapshotResult:
    """Burst selected venues, normalize, match, score, optionally write Parquet."""
    settings = settings or get_settings()
    venues = venues or ["deribit", "coincall"]
    depth = settings.depth
    store = ParquetStore(settings.data_dir, depth=depth, cadence_min=settings.snapshot_interval_min)

    index_px = fetch_btc_index()
    ts_ms = int(time.time() * 1000)
    stats: dict[str, Any] = {"index_px": index_px}

    tasks = []
    labels: list[str] = []
    if "deribit" in venues:
        d = DeribitVenue()
        d_inst = d.list_instruments(settings.underlying)
        d_syms = [i.venue_symbol for i in d_inst]
        labels.append("deribit")
        tasks.append(d.burst_books(d_syms, depth=depth, duration_s=duration_s))
        stats["deribit_n_instruments"] = len(d_syms)
    if "coincall" in venues:
        c = CoincallVenue(settings)
        c_inst = c.list_instruments(settings.underlying)
        c_syms = [i.venue_symbol for i in c_inst]
        labels.append("coincall")
        tasks.append(c.burst_books(c_syms, depth=depth, duration_s=duration_s))
        stats["coincall_n_instruments"] = len(c_syms)

    results = await asyncio.gather(*tasks)
    raw_rows: list[dict] = []
    for label, (books, burst_stats) in zip(labels, results, strict=True):
        stats[label] = burst_stats.to_dict()
        raw_rows.extend(
            books_to_raw_rows(
                books,
                ts_ms=ts_ms,
                index_px=index_px,
                capture_lag_ms=burst_stats.capture_lag_ms,
            )
        )

    pairs = match_raw_rows(raw_rows)
    score_rows = score_pairs(pairs, ts_ms=ts_ms)
    matched = sum(1 for p in pairs if p.match_status == "matched")
    stats["n_raw"] = len(raw_rows)
    stats["n_pairs"] = len(pairs)
    stats["n_matched"] = matched
    stats["match_rate"] = matched / len(pairs) if pairs else 0.0
    stats["ts_iso"] = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()

    raw_path = scores_path = None
    if write and raw_rows:
        raw_path = str(store.write_raw_books(raw_rows, ts_ms, append=True))
    if write and score_rows:
        scores_path = str(store.write_pair_scores(score_rows, ts_ms, append=True))

    return SnapshotResult(
        ts_ms=ts_ms,
        index_px=index_px,
        venues=labels,
        raw_rows=raw_rows,
        score_rows=score_rows,
        stats=stats,
        raw_path=raw_path,
        scores_path=scores_path,
    )
