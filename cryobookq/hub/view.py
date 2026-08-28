"""Transform ``ScorecardResult`` into the public dashboard view model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cryobookq.analytics.report.labels import VENUE_COLORS, venue_name
from cryobookq.analytics.report.narrative import component_means
from cryobookq.analytics.scorecard import (
    HUB_VENUE,
    TENOR_TARGETS,
    WING_LABEL,
    ScorecardResult,
)
from cryobookq.hub import copy_loader

# Grid rows for the 3×3 liquidity table (tenor × delta).
_GRID_ROWS: list[tuple[str, str, str, str]] = [
    ("short", "50d", "Short · 50Δ", "~1–2 DTE · ATM call+put avg"),
    ("short", "25d", "Short · 25Δ", "~1–2 DTE · 25Δ call+put avg"),
    ("short", "7p5d", "Short · 7.5Δ", "~1–2 DTE · 7.5Δ wing call+put avg"),
    ("mid", "50d", "Mid · 50Δ", "Mean 7 / 14 / 21 DTE · 50Δ avg"),
    ("mid", "25d", "Mid · 25Δ", "Mean 7 / 14 / 21 DTE · 25Δ avg"),
    ("mid", "7p5d", "Mid · 7.5Δ", "Mean 7 / 14 / 21 DTE · 7.5Δ avg"),
    ("far", "50d", "Far · 50Δ", "Mean 60 / 90 / 120 DTE · 50Δ avg"),
    ("far", "25d", "Far · 25Δ", "Mean 60 / 90 / 120 DTE · 25Δ avg"),
    ("far", "7p5d", "Far · 7.5Δ", "Mean 60 / 90 / 120 DTE · 7.5Δ avg"),
]

_WING_TENOR_LABELS = {
    "short": "Short (~1–2 DTE)",
    "mid": "Mid (7/14/21 DTE avg)",
    "far": "Far (60/90/120 DTE avg)",
}


def _fmt_ts_ms(ts_ms: int | None) -> str:
    if ts_ms is None:
        return "—"
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%H:%M UTC")


def _fmt_ts_full(ts_ms: int | None) -> str:
    if ts_ms is None:
        return "—"
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def score_tone(value: float | None) -> str:
    """CSS tone class for 0–10 scores."""
    if value is None:
        return "muted"
    v = float(value)
    if v >= 7:
        return "ok"
    if v >= 5:
        return "info"
    if v >= 3:
        return "warn"
    return "bad"


def rank_tone(rank: int) -> str:
    if rank == 1:
        return "ok"
    if rank <= 3:
        return "info"
    if rank == 4:
        return "warn"
    return "neutral"


def grid_row_tone(max_score: float) -> str:
    if max_score >= 8:
        return "ok"
    if max_score >= 6:
        return "info"
    if max_score >= 4:
        return "warn"
    if max_score >= 2:
        return "neutral"
    return "bad"


def _cell_score(cell: dict[str, Any] | None, venue: str) -> float | None:
    if not cell:
        return None
    venues = cell.get("venues") or {}
    vs = venues.get(venue)
    if not isinstance(vs, dict):
        return None
    sc = vs.get("score")
    return float(sc) if sc is not None else None


def _scorecard_window(card: ScorecardResult) -> str:
    if card.meta.get("aggregated"):
        first = card.meta.get("ts_ms_first")
        last = card.meta.get("ts_ms_last")
        if first is not None and last is not None:
            return f"{_fmt_ts_ms(int(first))} – {_fmt_ts_ms(int(last))}"
    return _fmt_ts_ms(card.ts_ms)


def _scorecard_generated(card: ScorecardResult | None, *, now: datetime | None = None) -> str:
    if card is not None and card.meta.get("aggregated"):
        last = card.meta.get("ts_ms_last")
        if last is not None:
            return _fmt_ts_full(int(last))
    return (now or datetime.now(tz=UTC)).strftime("%Y-%m-%d %H:%M UTC")


def build_dashboard_view(
    card: ScorecardResult | None,
    *,
    interval_min: int,
    n_snapshot_files: int,
    generated: datetime | None = None,
) -> dict[str, Any]:
    """Build template context for the public dashboard."""
    now = generated or datetime.now(tz=UTC)
    footer = copy_loader.footer()
    base: dict[str, Any] = {
        "title": copy_loader.page_title(),
        "intro": copy_loader.intro_text(),
        "copy": {
            "venues": copy_loader.section("venues", n_snapshots=n_snapshot_files),
            "grid": copy_loader.section("grid"),
            "grid_tenors": copy_loader.section("grid_tenors"),
            "wings": copy_loader.section("wings"),
            "wings_total": copy_loader.section("wings_total"),
            "presence": copy_loader.section("presence"),
            "catalogue": copy_loader.section("catalogue"),
        },
        "footer": footer,
        "interval_min": interval_min,
        "has_data": card is not None,
        "empty_message": copy_loader.empty_message(),
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"),
    }

    if card is None:
        base.update(
            {
                "meta": {
                    "n_snapshots": 0,
                    "window": "—",
                    "scorecard_generated": base["generated"],
                },
                "leader": None,
                "ranked_venues": [],
                "column_venues": [],
                "grid_rows": [],
                "wing_rows": [],
                "presence_rows": [],
                "catalogue_rows": [],
            }
        )
        return base

    means = component_means(card)
    venues = list(card.venues)
    ranked_ids = sorted(venues, key=lambda v: (-float(card.overall.get(v) or -1.0), venue_name(v)))

    ranked_venues: list[dict[str, Any]] = []
    for rank, vid in enumerate(ranked_ids, start=1):
        pv = (card.presence.get("per_venue") or {}).get(vid) or {}
        cv = (card.catalogue.get("per_venue") or {}).get(vid) or {}
        m = means[vid]
        rate = pv.get("two_sided_rate")
        ranked_venues.append(
            {
                "id": vid,
                "name": venue_name(vid),
                "color": VENUE_COLORS.get(vid, "#5c6b7a"),
                "rank": rank,
                "rank_tone": rank_tone(rank),
                "overall": card.overall.get(vid),
                "overall_fmt": f"{float(card.overall.get(vid) or 0):.2f}",
                "grid": m["grid"],
                "grid_fmt": f"{m['grid']:.1f}",
                "wings": m["wings"],
                "wings_fmt": f"{m['wings']:.1f}",
                "presence_rate": rate,
                "presence_pct": f"{100.0 * float(rate):.0f}%" if rate is not None else "—",
                "presence_tone": score_tone(float(rate or 0) * 10),
                "grid_tone": score_tone(m["grid"]),
                "wings_tone": score_tone(m["wings"]),
                "n_instruments": cv.get("n_instruments"),
                "hub": vid == HUB_VENUE,
            }
        )

    column_venues = [{"id": v["id"], "name": v["name"]} for v in ranked_venues]

    grid_rows: list[dict[str, Any]] = []
    for tenor, delta, label, dte in _GRID_ROWS:
        key = f"{tenor}:{delta}"
        cell = card.grid.get(key)
        scores: list[float] = []
        cells: list[dict[str, Any]] = []
        for vid in ranked_ids:
            sc = _cell_score(cell if isinstance(cell, dict) else None, vid)
            if sc is not None:
                scores.append(sc)
            cells.append(
                {
                    "venue": vid,
                    "score": sc,
                    "fmt": f"{sc:.1f}" if sc is not None else "—",
                }
            )
        max_sc = max(scores) if scores else 0.0
        grid_rows.append(
            {
                "label": label,
                "dte": dte,
                "cells": cells,
                "row_tone": grid_row_tone(max_sc),
            }
        )

    wing_rows: list[dict[str, Any]] = []
    wing_totals: dict[str, list[float]] = {v: [] for v in ranked_ids}
    for tenor in TENOR_TARGETS:
        key = f"{tenor}:{WING_LABEL}"
        cell = card.wings.get(key)
        cells = []
        for vid in ranked_ids:
            sc = _cell_score(cell if isinstance(cell, dict) else None, vid)
            if sc is not None:
                wing_totals[vid].append(sc)
            cells.append({"fmt": f"{sc:.1f}" if sc is not None else "—"})
        wing_rows.append({"label": _WING_TENOR_LABELS.get(tenor, tenor), "cells": cells})

    total_cells = []
    for vid in ranked_ids:
        vals = wing_totals[vid]
        avg = sum(vals) / len(vals) if vals else None
        total_cells.append({"fmt": f"{avg:.1f}" if avg is not None else "—"})
    wing_rows.append({"label": "Total (equal weight)", "cells": total_cells, "is_total": True})

    presence_rows: list[dict[str, Any]] = []
    for v in ranked_venues:
        vid = v["id"]
        pv = (card.presence.get("per_venue") or {}).get(vid) or {}
        n = pv.get("n")
        n_two = pv.get("n_two_sided")
        rate = pv.get("two_sided_rate")
        presence_rows.append(
            {
                "name": v["name"],
                "two_sided": (
                    f"{100.0 * float(rate):.1f}% ({n_two}/{n})"
                    if rate is not None and n is not None and n_two is not None
                    else "—"
                ),
                "score_fmt": f"{float(pv.get('score') or 0):.2f}",
            }
        )

    catalogue_rows: list[dict[str, Any]] = []
    for v in ranked_venues:
        vid = v["id"]
        cv = (card.catalogue.get("per_venue") or {}).get(vid) or {}
        catalogue_rows.append(
            {
                "name": v["name"],
                "score_fmt": f"{float(cv.get('score') or 0):.2f}",
                "n_instruments": cv.get("n_instruments"),
                "n_hub_two": cv.get("n_hub_two_sided"),
                "n_extras": cv.get("n_extras"),
            }
        )

    n_snaps = int(card.meta.get("n_snapshots") or 1)
    leader = ranked_venues[0] if ranked_venues else None

    base.update(
        {
            "meta": {
                "n_snapshots": n_snaps,
                "window": _scorecard_window(card),
                "scorecard_generated": _scorecard_generated(card, now=now),
            },
            "leader": leader,
            "ranked_venues": ranked_venues,
            "column_venues": column_venues,
            "grid_rows": grid_rows,
            "wing_rows": wing_rows,
            "presence_rows": presence_rows,
            "catalogue_rows": catalogue_rows,
        }
    )
    return base
