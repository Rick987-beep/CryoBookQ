"""View-model for the CryoBookQ status hub."""

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

from cryobookq.analytics.report.labels import VENUE_COLORS, venue_name
from cryobookq.analytics.scorecard import (
    PREFERRED_VENUES,
    ScorecardResult,
    aggregate_scorecards,
    build_scorecards_from_raw,
)
from cryobookq.config import Settings, get_settings

logger = logging.getLogger(__name__)

_SCORECARD_CACHE: dict[str, tuple[float, ScorecardResult | None]] = {}
_CACHE_TTL_S = 90.0
_HUB_MAX_SNAPSHOT_FILES = 8
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


def _recent_raw_paths(data_dir: Path, *, max_files: int = _HUB_MAX_SNAPSHOT_FILES) -> list[Path]:
    root = Path(data_dir) / "raw_books"
    if not root.is_dir():
        return []
    files = sorted(root.glob("date=*/part-*.parquet"))
    return files[-max_files:]


def _load_scorecard(data_dir: Path) -> ScorecardResult | None:
    """Build scorecard from recent snapshots only (hub must stay fast)."""
    key = str(Path(data_dir).resolve())
    now = time.time()
    cached = _SCORECARD_CACHE.get(key)
    if cached and now - cached[0] < _CACHE_TTL_S:
        return cached[1]

    def _build() -> ScorecardResult | None:
        paths = _recent_raw_paths(data_dir)
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


def _fmt_ts_ms(ts_ms: int | None) -> str:
    if ts_ms is None:
        return "—"
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_pct(rate: float | None) -> str:
    if rate is None:
        return "—"
    return f"{100.0 * float(rate):.1f}%"


def _fmt_num(x: float | None, *, digits: int = 2) -> str:
    if x is None:
        return "—"
    return f"{float(x):.{digits}f}"


def _venue_cell_mean(card: ScorecardResult, section: str, venue: str) -> float | None:
    block = getattr(card, section, None) or {}
    scores: list[float] = []
    if not isinstance(block, dict):
        return None
    for cell in block.values():
        if not isinstance(cell, dict):
            continue
        vs = (cell.get("venues") or {}).get(venue)
        if isinstance(vs, dict) and vs.get("score") is not None:
            scores.append(float(vs["score"]))
    if not scores:
        return None
    return sum(scores) / len(scores)


def _wing_total(card: ScorecardResult, venue: str) -> float | None:
    wings = card.wings or {}
    if not isinstance(wings, dict):
        return None
    total = (wings.get("total") or {}).get("venues") or {}
    vs = total.get(venue)
    if isinstance(vs, dict) and vs.get("score") is not None:
        return float(vs["score"])
    return _venue_cell_mean(card, "wings", venue)


def _status_class(status: str) -> str:
    return {
        "ok": "ok",
        "degraded": "warn",
        "incomplete": "warn",
        "disk_warn": "bad",
        "unreachable": "bad",
    }.get(status, "warn")


def _capture_flags(st: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    interest = (
        "rest_429",
        "rest_weight",
        "rest_time_stop",
        "ticker_fill",
        "sampler=slow",
        "ws_conns",
        "ws_closed",
        "429",
    )
    if st.get("error"):
        flags.append(str(st["error"]))
    for n in st.get("notes") or []:
        s = str(n)
        if any(k in s for k in interest):
            flags.append(s)
    for e in (st.get("subscribe_errors") or [])[:3]:
        if str(e) not in flags:
            flags.append(str(e))
    return flags[:6]


def build_hub_context(
    data_dir: Path | None = None,
    *,
    settings: Settings | None = None,
    health: dict[str, Any] | None = None,
    scorecard: ScorecardResult | None = None,
) -> dict[str, Any]:
    """Assemble template context for the status page."""
    settings = settings or get_settings()
    root = Path(data_dir) if data_dir is not None else settings.data_dir
    health = health if health is not None else fetch_daemon_health(port=settings.health_port)
    card = scorecard if scorecard is not None else _load_scorecard(root)

    last_stats = health.get("last_stats") or {}
    quality = last_stats.get("quality") or {}
    coverages = quality.get("coverages") or {}
    venue_errors = quality.get("venue_errors") or {}

    venues = list(PREFERRED_VENUES)
    if card is not None:
        for v in card.venues:
            if v not in venues:
                venues.append(v)

    presence_pv = ((card.presence or {}).get("per_venue") or {}) if card else {}
    catalogue_pv = ((card.catalogue or {}).get("per_venue") or {}) if card else {}
    overall = dict(card.overall) if card else dict(last_stats.get("scorecard_overall") or {})

    venue_rows: list[dict[str, Any]] = []
    for v in venues:
        st = last_stats.get(v) if isinstance(last_stats.get(v), dict) else {}
        pv = presence_pv.get(v) or {}
        cv = catalogue_pv.get(v) or {}
        cap_cov = coverages.get(v)
        if cap_cov is None and st:
            cap_cov = st.get("coverage")
        flags = _capture_flags(st) if st else []
        venue_rows.append(
            {
                "id": v,
                "name": venue_name(v),
                "color": VENUE_COLORS.get(v, "#5c6b7a"),
                "overall": overall.get(v),
                "grid": _venue_cell_mean(card, "grid", v) if card else None,
                "wings": _wing_total(card, v) if card else None,
                "presence_rate": pv.get("two_sided_rate"),
                "presence_score": pv.get("score"),
                "n_instruments": cv.get("n_instruments") or st.get("n_instruments"),
                "capture_coverage": cap_cov,
                "duration_s": st.get("duration_s"),
                "flags": flags,
                "error": venue_errors.get(v),
                "hub": v == "deribit",
            }
        )

    venue_rows.sort(key=lambda r: (-(r["overall"] or -1), r["name"]))

    n_snaps = int((card.meta or {}).get("n_snapshots") or 0) if card else 0
    scorecard_note = None
    if card is None:
        scorecard_note = "No scored raw books in data store yet."
    elif n_snaps == 1:
        scorecard_note = f"Scores from 1 snapshot ({_fmt_ts_ms(card.ts_ms)})."
    elif n_snaps > 1:
        scorecard_note = (
            f"Scores aggregated over {n_snaps} recent snapshots "
            f"(last {_HUB_MAX_SNAPSHOT_FILES} parquet files in store)."
        )

    return {
        "title": "CryoBookQ",
        "subtitle": "Multi-exchange BTC option book quality",
        "interval_min": settings.snapshot_interval_min,
        "health": health,
        "status": health.get("status", "unknown"),
        "status_class": _status_class(str(health.get("status", "unknown"))),
        "last_ts": _fmt_ts_ms(health.get("last_ts_ms")),
        "uptime_h": _fmt_num((health.get("uptime_s") or 0) / 3600.0, digits=1),
        "disk_gb": _fmt_num((health.get("disk_free_mb") or 0) / 1024.0, digits=1),
        "clock_ms": _fmt_num((health.get("clock") or {}).get("offset_s", 0) * 1000.0, digits=0),
        "venue_rows": venue_rows,
        "scorecard_note": scorecard_note,
        "n_snapshots_scored": n_snaps,
        "match_rate": _fmt_pct(last_stats.get("match_rate")),
        "n_raw": last_stats.get("n_raw"),
        "quality_ok": quality.get("ok"),
        "quality_reasons": quality.get("reasons") or [],
        "last_error": health.get("last_error"),
        "generated": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
