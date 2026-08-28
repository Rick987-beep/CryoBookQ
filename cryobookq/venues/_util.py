"""Shared helpers for venue spikes / bursts."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import resource
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cryobookq.types import BookL5, OptionKey, pad_levels

logger = logging.getLogger(__name__)


def peak_rss_mb() -> float:
    """Peak resident set size in MiB (portable macOS/Linux)."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024  # Linux: KB


@dataclass
class BurstStats:
    venue: str
    n_instruments: int
    n_with_update: int
    duration_s: float
    peak_rss_mb: float
    subscribe_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    capture_lag_ms: float | None = None

    @property
    def coverage(self) -> float:
        if self.n_instruments <= 0:
            return 0.0
        return self.n_with_update / self.n_instruments

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "n_instruments": self.n_instruments,
            "n_with_update": self.n_with_update,
            "coverage": round(self.coverage, 4),
            "duration_s": round(self.duration_s, 3),
            "peak_rss_mb": round(self.peak_rss_mb, 1),
            "capture_lag_ms": self.capture_lag_ms,
            "subscribe_errors": self.subscribe_errors,
            "notes": self.notes,
        }


class Timer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0


def resolve_deadline_ts(
    deadline: datetime | None,
    duration_s: float | None,
    *,
    default_s: float = 15.0,
) -> float:
    """Unix timestamp to stop collecting. Prefer absolute *deadline*."""
    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return deadline.timestamp()
    collect_s = default_s if duration_s is None else float(duration_s)
    return time.time() + collect_s


def book_from_levels(
    venue: str,
    symbol: str,
    key: OptionKey | None,
    bid_levels: list[tuple[float, float]],
    ask_levels: list[tuple[float, float]],
    depth: int,
    *,
    size_to_btc: float | None = None,
    ts_exchange_ms: int | None = None,
) -> BookL5:
    bid_px, bid_sz = pad_levels(bid_levels[:depth], depth)
    ask_px, ask_sz = pad_levels(ask_levels[:depth], depth)
    return BookL5(
        venue=venue,
        venue_symbol=symbol,
        key=key,
        ts_exchange_ms=ts_exchange_ms,
        bid_px=bid_px,
        bid_sz=bid_sz,
        ask_px=ask_px,
        ask_sz=ask_sz,
        size_to_btc=size_to_btc,
    )


class CatalogueTracker:
    """Log books / two-sided coverage on a fixed interval during a burst."""

    def __init__(
        self,
        venue: str,
        n_symbols: int,
        books: dict[str, BookL5],
        notes: list[str],
        t_start: float | None = None,
    ) -> None:
        self.venue = venue
        self.n_symbols = n_symbols
        self.books = books
        self.notes = notes
        self.t_start = time.time() if t_start is None else t_start

    def log(self, phase: str) -> None:
        n = len(self.books)
        two = sum(1 for b in self.books.values() if b.two_sided)
        cov = 100.0 * n / self.n_symbols if self.n_symbols else 0.0
        logger.info(
            "%s catalogue phase=%s t=%.1fs books=%d/%d coverage=%.1f%% two_sided=%d",
            self.venue,
            phase,
            time.time() - self.t_start,
            n,
            self.n_symbols,
            cov,
            two,
        )
        self.notes.append(f"cat_{phase}={n}/{self.n_symbols}")

    async def progress(self, deadline_ts: float, interval_s: float = 10.0) -> None:
        n = 0
        while time.time() < deadline_ts:
            await asyncio.sleep(interval_s)
            if time.time() >= deadline_ts:
                break
            n += 1
            self.log(f"ws_{n * int(interval_s)}s")


@asynccontextmanager
async def track_catalogue(
    tracker: CatalogueTracker,
    deadline_ts: float,
    interval_s: float = 10.0,
) -> AsyncIterator[CatalogueTracker]:
    tracker.log("ws_start")
    task = asyncio.create_task(tracker.progress(deadline_ts, interval_s=interval_s))
    try:
        yield tracker
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        tracker.log("ws_done")


def catalogue_series(notes: list[str]) -> list[tuple[str, int, int]]:
    """Parse ``cat_ws_10s=324/658`` notes into (phase, books, n_symbols)."""
    out: list[tuple[str, int, int]] = []
    for note in notes:
        if not note.startswith("cat_") or "=" not in note:
            continue
        left, right = note.split("=", 1)
        if "/" not in right:
            continue
        a, b = right.split("/", 1)
        try:
            out.append((left.removeprefix("cat_"), int(a), int(b)))
        except ValueError:
            continue
    return out
