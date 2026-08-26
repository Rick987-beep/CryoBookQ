"""In-process health state for daemon / hub."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HealthState:
    started_at: float = field(default_factory=time.time)
    last_ts_ms: int | None = None
    last_ok: bool = False
    last_error: str | None = None
    gaps_today: int = 0
    snapshots_today: int = 0
    last_stats: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self, ts_ms: int, stats: dict[str, Any]) -> None:
        with self._lock:
            self.last_ts_ms = ts_ms
            self.last_ok = True
            self.last_error = None
            self.snapshots_today += 1
            self.last_stats = stats

    def record_failure(self, error: str) -> None:
        with self._lock:
            self.last_ok = False
            self.last_error = error

    def record_gap(self) -> None:
        with self._lock:
            self.gaps_today += 1

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "started_at": self.started_at,
                "last_ts_ms": self.last_ts_ms,
                "last_ok": self.last_ok,
                "last_error": self.last_error,
                "gaps_today": self.gaps_today,
                "snapshots_today": self.snapshots_today,
                "last_stats": dict(self.last_stats),
                "uptime_s": round(time.time() - self.started_at, 1),
            }


HEALTH = HealthState()
