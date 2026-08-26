"""Shared helpers for venue spikes / bursts."""

from __future__ import annotations

import resource
import sys
import time
from dataclasses import dataclass, field
from typing import Any


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
