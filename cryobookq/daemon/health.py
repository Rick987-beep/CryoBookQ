"""In-process health state + localhost HTTP endpoint for ops.

Exposes ``GET /health`` on ``BOOKQ_HEALTH_PORT`` (default 8091) in a daemon
thread so the asyncio capture loop is never blocked — same pattern as
CryoTrader tickrecorder.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from cryobookq.capture.disk import disk_free_mb

logger = logging.getLogger(__name__)


@dataclass
class HealthState:
    started_at: float = field(default_factory=time.time)
    last_ts_ms: int | None = None
    last_ok: bool = False
    last_incomplete: bool = False
    last_error: str | None = None
    gaps_today: int = 0
    incomplete_today: int = 0
    snapshots_today: int = 0
    writes_today: int = 0
    last_stats: dict[str, Any] = field(default_factory=dict)
    data_dir: str | None = None
    disk_free_warn_mb: int = 5000
    clock: dict[str, Any] = field(default_factory=dict)
    _day_utc: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self, ts_ms: int, stats: dict[str, Any], *, wrote: bool) -> None:
        with self._lock:
            self._maybe_roll_day_locked()
            self.last_ts_ms = ts_ms
            self.last_ok = True
            self.last_incomplete = False
            self.last_error = None
            self.snapshots_today += 1
            if wrote:
                self.writes_today += 1
            self.last_stats = stats

    def record_incomplete(self, ts_ms: int, stats: dict[str, Any], *, wrote: bool, reason: str) -> None:
        with self._lock:
            self._maybe_roll_day_locked()
            self.last_ts_ms = ts_ms
            self.last_ok = False
            self.last_incomplete = True
            self.last_error = reason
            self.incomplete_today += 1
            self.gaps_today += 1
            self.snapshots_today += 1
            if wrote:
                self.writes_today += 1
            self.last_stats = stats

    def record_failure(self, error: str) -> None:
        with self._lock:
            self._maybe_roll_day_locked()
            self.last_ok = False
            self.last_incomplete = False
            self.last_error = error

    def record_gap(self) -> None:
        with self._lock:
            self._maybe_roll_day_locked()
            self.gaps_today += 1

    def _maybe_roll_day_locked(self) -> None:
        """Reset today counters at UTC midnight (caller holds ``_lock``)."""
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        if self._day_utc is None:
            self._day_utc = today
            return
        if today != self._day_utc:
            logger.info(
                "UTC day roll %s → %s; resetting today counters "
                "(was snapshots=%d gaps=%d incomplete=%d writes=%d)",
                self._day_utc,
                today,
                self.snapshots_today,
                self.gaps_today,
                self.incomplete_today,
                self.writes_today,
            )
            self._day_utc = today
            self.gaps_today = 0
            self.incomplete_today = 0
            self.snapshots_today = 0
            self.writes_today = 0

    def reset_day_counters_if_needed(self) -> None:
        with self._lock:
            self._maybe_roll_day_locked()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            self._maybe_roll_day_locked()
            free = disk_free_mb(self.data_dir) if self.data_dir else -1
            status = "ok"
            if not self.last_ok:
                status = "incomplete" if self.last_incomplete else "degraded"
            if free != -1 and free < self.disk_free_warn_mb:
                status = "disk_warn" if status == "ok" else status
            return {
                "status": status,
                "started_at": self.started_at,
                "last_ts_ms": self.last_ts_ms,
                "last_ok": self.last_ok,
                "last_incomplete": self.last_incomplete,
                "last_error": self.last_error,
                "gaps_today": self.gaps_today,
                "incomplete_today": self.incomplete_today,
                "snapshots_today": self.snapshots_today,
                "writes_today": self.writes_today,
                "day_utc": self._day_utc,
                "last_stats": dict(self.last_stats),
                "uptime_s": round(time.time() - self.started_at, 1),
                "data_dir": self.data_dir,
                "disk_free_mb": free,
                "clock": dict(self.clock),
            }


HEALTH = HealthState()


class _HealthHandler(BaseHTTPRequestHandler):
    health: HealthState = HEALTH

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/health":
            self.send_response(404)
            self.end_headers()
            return
        try:
            body = json.dumps(self.health.as_dict()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:  # noqa: BLE001
            self.send_response(500)
            self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        return  # silence access log spam


def start_health_server(
    health: HealthState | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8091,
) -> HTTPServer:
    """Start ``GET /health`` in a daemon thread; return the server."""

    class Handler(_HealthHandler):
        pass

    Handler.health = health or HEALTH
    server = HTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="bookq-health")
    thread.start()
    logger.info("Health endpoint on http://%s:%d/health", host, port)
    return server
