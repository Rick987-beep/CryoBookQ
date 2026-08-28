"""View-model for the CryoBookQ public dashboard."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from cryobookq.analytics.scorecard import (
    ScorecardResult,
    aggregate_scorecards,
    build_scorecards_from_raw,
)
from cryobookq.config import Settings, get_settings
from cryobookq.hub.view import build_dashboard_view

logger = logging.getLogger(__name__)

_SCORECARD_CACHE: dict[str, tuple[float, ScorecardResult | None]] = {}
_CACHE_TTL_S = 90.0
_SCORECARD_TIMEOUT_S = 15.0


def fetch_daemon_health(*, host: str = "127.0.0.1", port: int = 8091, timeout: float = 2.0) -> dict[str, Any]:
    """Load live daemon health (hub runs in a separate process from capture)."""
    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("daemon health unavailable at %s: %s", url, exc)
        return {"status": "unreachable", "error": str(exc)}


def _recent_raw_paths(data_dir: Path, *, max_files: int) -> list[Path]:
    root = Path(data_dir) / "raw_books"
    if not root.is_dir():
        return []
    files = sorted(root.glob("date=*/part-*.parquet"))
    return files[-max_files:]


def _load_scorecard(data_dir: Path, *, max_files: int) -> ScorecardResult | None:
    """Build scorecard from recent snapshots only (hub must stay fast)."""
    key = f"{Path(data_dir).resolve()}:{max_files}"
    now = time.time()
    cached = _SCORECARD_CACHE.get(key)
    if cached and now - cached[0] < _CACHE_TTL_S:
        return cached[1]

    def _build() -> ScorecardResult | None:
        paths = _recent_raw_paths(data_dir, max_files=max_files)
        if not paths:
            return None
        df = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
        if df.empty:
            return None
        cards = build_scorecards_from_raw(df)
        if not cards:
            return None
        if len(cards) == 1:
            return cards[0]
        return aggregate_scorecards(cards)

    card: ScorecardResult | None
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            card = pool.submit(_build).result(timeout=_SCORECARD_TIMEOUT_S)
    except FutTimeout:
        logger.warning("scorecard build timed out for %s", data_dir)
        card = None
    except Exception as exc:
        logger.info("scorecard build failed: %s", exc)
        card = None

    _SCORECARD_CACHE[key] = (now, card)
    return card


def build_hub_context(
    data_dir: Path | None = None,
    *,
    settings: Settings | None = None,
    health: dict[str, Any] | None = None,
    scorecard: ScorecardResult | None = None,
) -> dict[str, Any]:
    """Assemble template context for the public dashboard."""
    settings = settings or get_settings()
    root = Path(data_dir) if data_dir is not None else settings.data_dir
    max_files = settings.hub_snapshot_n

    if scorecard is None:
        scorecard = _load_scorecard(root, max_files=max_files)

    generated = datetime.now(tz=UTC)
    ctx = build_dashboard_view(
        scorecard,
        interval_min=settings.snapshot_interval_min,
        n_snapshot_files=max_files,
        generated=generated,
    )

    # Operational fields for /health and /api/status (not shown on the public page).
    if health is None:
        health = fetch_daemon_health(port=settings.health_port)
    ctx["health"] = health
    ctx["daemon_status"] = health.get("status", "unknown")
    return ctx
