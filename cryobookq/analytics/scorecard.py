"""Landmark option-book scorecard (multi-venue 0–10 index).

Subjects
--------
* **3×3 grid** — tenors short / mid / far × |Δ| targets 50δ / 25δ / 7.5δ
* **Wings** — same tenors at |Δ| ≈ 2.5δ
* **Presence** — two-sided rate among matched options with |Δ| ≥ 0.05

Tenor targets (nearest listed expiry, then average):
* short: 1d, 2d
* mid: 7d, 14d, 21d (weeklies)
* far: 60d, 90d, 120d

Per landmark contract (nearest call + put to target |Δ|, then averaged):
* relative TOB spread %
* $10k premium lift: VWAP and (VWAP−mid)/mid %
* L5 depth in USD premium notional

Missing / one-sided landmark → metric null and component score **0**.
Scores use **absolute** refs so a third venue does not reshuffle peers.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from cryobookq.pipeline.match import MatchedContract, match_raw_rows
from cryobookq.pipeline.score import dte_for, venue_metrics

logger = logging.getLogger(__name__)

# ── landmarks ─────────────────────────────────────────────────────────────

TENOR_TARGETS: dict[str, list[float]] = {
    "short": [1.0, 2.0],
    "mid": [7.0, 14.0, 21.0],
    "far": [60.0, 90.0, 120.0],
}

# Max |listed_dte − target| to accept an expiry for that target.
TENOR_MAX_GAP: dict[str, float] = {
    "short": 1.5,
    "mid": 4.0,
    "far": 15.0,
}

DELTA_TARGETS: dict[str, float] = {
    "50d": 0.50,
    "25d": 0.25,
    "7p5d": 0.075,
}
WING_DELTA = 0.025
WING_LABEL = "2p5d"
MAX_DELTA_GAP = 0.10  # reject landmark if closest |Δ| farther than this

NOTIONAL_USD = 10_000.0
PRESENCE_MIN_ABS_DELTA = 0.05

# Absolute refs for 0–10 maps (documented; tune from production).
SPREAD_REF_PCT: dict[str, float] = {
    "50d": 8.0,
    "25d": 15.0,
    "7p5d": 40.0,
    "2p5d": 80.0,
}
SIZE_REF_PCT: dict[str, float] = {
    "50d": 4.0,
    "25d": 8.0,
    "7p5d": 20.0,
    "2p5d": 40.0,
}
DEPTH_REF_USD: dict[str, float] = {
    "50d": 80_000.0,
    "25d": 40_000.0,
    "7p5d": 15_000.0,
    "2p5d": 5_000.0,
}

OVERALL_WEIGHTS = {
    "grid": 0.60,
    "wings": 0.20,
    "presence": 0.20,
}

# Within each landmark cell: spread dominates (small-ticket quote quality);
# $10k lift is the primary size check; depth is a light inventory signal.
CELL_WEIGHTS = {
    "spread": 0.65,
    "size": 0.25,
    "depth": 0.10,
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_lower_better(value: float | None, ref: float) -> float:
    """Map metric to 0–10 (lower better). None → 0."""
    if value is None or ref <= 0 or math.isnan(value):
        return 0.0
    return 10.0 * _clamp01(1.0 - value / ref)


def score_higher_better(value: float | None, ref: float) -> float:
    if value is None or ref <= 0 or math.isnan(value):
        return 0.0
    return 10.0 * _clamp01(value / ref)


def _levels(row: dict[str, Any], side: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for i in range(1, 6):
        px = float(row.get(f"{side}_px_{i}") or 0)
        sz = float(row.get(f"{side}_sz_{i}") or 0)
        if px > 0 and sz > 0:
            out.append((px, sz))
    return out


def relative_spread_pct(row: dict[str, Any] | None) -> float | None:
    m = venue_metrics(row)
    if not m["two_sided"] or not m["mid_usd"] or m["spread_usd"] is None:
        return None
    mid = m["mid_usd"]
    if mid <= 0:
        return None
    return float(m["spread_usd"] / mid * 100.0)


def depth_usd(row: dict[str, Any] | None) -> float | None:
    """Sum of L5 bid+ask premium notional in USD (px × sz)."""
    if row is None:
        return None
    total = 0.0
    for side in ("bid", "ask"):
        for px, sz in _levels(row, side):
            total += px * sz
    return total


def lift_notional(
    row: dict[str, Any] | None,
    *,
    notional_usd: float = NOTIONAL_USD,
) -> dict[str, Any]:
    """Walk asks until ``notional_usd`` premium spent.

    Returns VWAP, effective (VWAP−mid)/mid %, fillable flag.
    """
    empty = {
        "fillable": False,
        "vwap": None,
        "effective_pct": None,
        "filled_usd": 0.0,
        "filled_btc": 0.0,
    }
    if row is None:
        return empty
    m = venue_metrics(row)
    mid = m["mid_usd"]
    asks = _levels(row, "ask")
    if not asks or mid is None or mid <= 0:
        return empty

    remaining = notional_usd
    filled_usd = 0.0
    filled_btc = 0.0
    for px, sz in asks:
        level_usd = px * sz
        take_usd = min(remaining, level_usd)
        take_btc = take_usd / px
        filled_usd += take_usd
        filled_btc += take_btc
        remaining -= take_usd
        if remaining <= 1e-6:
            break

    if remaining > 1.0:  # allow $1 rounding
        return {
            "fillable": False,
            "vwap": None,
            "effective_pct": None,
            "filled_usd": filled_usd,
            "filled_btc": filled_btc,
        }
    vwap = filled_usd / filled_btc if filled_btc > 0 else None
    eff = (vwap - mid) / mid * 100.0 if vwap is not None else None
    return {
        "fillable": True,
        "vwap": vwap,
        "effective_pct": eff,
        "filled_usd": filled_usd,
        "filled_btc": filled_btc,
    }


def _mean(xs: list[float | None]) -> float | None:
    vals = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _mean_scores(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


@dataclass
class LandmarkPick:
    tenor: str
    target_dte: float
    expiry_utc_ms: int
    listed_dte: float
    delta_label: str
    target_delta: float
    is_call: bool
    pair: MatchedContract
    abs_delta: float


def _pair_abs_delta(pair: MatchedContract) -> float | None:
    for row in pair.books.values():
        if row is None:
            continue
        d = row.get("delta")
        if d is not None:
            try:
                return abs(float(d))
            except (TypeError, ValueError):
                continue
    return None


def _hub_pairs(pairs: list[MatchedContract]) -> list[MatchedContract]:
    return [p for p in pairs if p.has_hub]


def _expiries(pairs: list[MatchedContract], ts_ms: int) -> dict[int, float]:
    """expiry_utc_ms → dte (hub / Deribit-listed only)."""
    out: dict[int, float] = {}
    for p in pairs:
        if not p.has_hub:
            continue
        exp = p.key.expiry_utc_ms
        out[exp] = dte_for(exp, ts_ms)
    return out


def nearest_expiry(
    expiries: dict[int, float],
    target_dte: float,
    *,
    max_gap: float,
) -> tuple[int, float] | None:
    if not expiries:
        return None
    best_exp, best_dte = min(expiries.items(), key=lambda kv: abs(kv[1] - target_dte))
    if abs(best_dte - target_dte) > max_gap:
        return None
    return best_exp, best_dte


def nearest_pair(
    pairs: list[MatchedContract],
    *,
    expiry_utc_ms: int,
    target_abs_delta: float,
    is_call: bool,
    max_delta_gap: float = MAX_DELTA_GAP,
) -> LandmarkPick | None:
    candidates: list[tuple[float, MatchedContract, float]] = []
    for p in pairs:
        if not p.has_hub:
            continue
        if p.key.expiry_utc_ms != expiry_utc_ms or p.key.is_call != is_call:
            continue
        ad = _pair_abs_delta(p)
        if ad is None:
            continue
        candidates.append((abs(ad - target_abs_delta), p, ad))
    if not candidates:
        return None
    gap, pair, ad = min(candidates, key=lambda t: t[0])
    if gap > max_delta_gap:
        return None
    return LandmarkPick(
        tenor="",
        target_dte=0.0,
        expiry_utc_ms=expiry_utc_ms,
        listed_dte=0.0,
        delta_label="",
        target_delta=target_abs_delta,
        is_call=is_call,
        pair=pair,
        abs_delta=ad,
    )


def contract_metrics(row: dict[str, Any] | None, *, delta_label: str) -> dict[str, Any]:
    spread = relative_spread_pct(row)
    lift = lift_notional(row)
    depth = depth_usd(row)
    two = bool(venue_metrics(row)["two_sided"])
    spread_s = score_lower_better(spread, SPREAD_REF_PCT[delta_label]) if two else 0.0
    size_s = (
        score_lower_better(lift["effective_pct"], SIZE_REF_PCT[delta_label])
        if lift["fillable"] and two
        else 0.0
    )
    depth_s = score_higher_better(depth, DEPTH_REF_USD[delta_label]) if two else 0.0
    w = CELL_WEIGHTS
    cell = w["spread"] * spread_s + w["size"] * size_s + w["depth"] * depth_s
    return {
        "two_sided": two,
        "spread_pct": spread,
        "lift_fillable": lift["fillable"],
        "lift_vwap": lift["vwap"],
        "lift_effective_pct": lift["effective_pct"],
        "depth_usd": depth,
        "score_spread": spread_s,
        "score_size": size_s,
        "score_depth": depth_s,
        "score": cell,
    }


def _row_for_venue(pair: MatchedContract | None, venue: str) -> dict[str, Any] | None:
    if pair is None:
        return None
    row = pair.books.get(venue)
    return row


def _avg_call_put(
    venues: list[str],
    call_pair: MatchedContract | None,
    put_pair: MatchedContract | None,
    *,
    delta_label: str,
) -> dict[str, Any]:
    """Average call+put metrics per venue; score 0 when side missing/one-sided."""
    per_venue: dict[str, dict[str, Any]] = {}
    for v in venues:
        cm = contract_metrics(_row_for_venue(call_pair, v), delta_label=delta_label)
        pm = contract_metrics(_row_for_venue(put_pair, v), delta_label=delta_label)
        per_venue[v] = {
            "call": cm,
            "put": pm,
            "spread_pct": _mean([cm["spread_pct"], pm["spread_pct"]]),
            "lift_effective_pct": _mean([cm["lift_effective_pct"], pm["lift_effective_pct"]]),
            "depth_usd": _mean([cm["depth_usd"], pm["depth_usd"]]),
            "score": _mean_scores([cm["score"], pm["score"]]),
            "n_sides": int(cm["two_sided"]) + int(pm["two_sided"]),
        }
    return per_venue


def _venues_from_pairs(pairs: list[MatchedContract]) -> list[str]:
    found: set[str] = set()
    for p in pairs:
        for name, row in p.books.items():
            if row is not None:
                found.add(str(name))
    preferred = ["deribit", "coincall", "bybit", "okx", "binance"]
    out = [v for v in preferred if v in found]
    out.extend(sorted(found - set(out)))
    return out or ["deribit", "coincall"]


@dataclass
class ScorecardResult:
    ts_ms: int
    venues: list[str]
    grid: dict[str, Any] = field(default_factory=dict)
    wings: dict[str, Any] = field(default_factory=dict)
    presence: dict[str, Any] = field(default_factory=dict)
    overall: dict[str, float] = field(default_factory=dict)
    landmarks: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts_ms": self.ts_ms,
            "venues": self.venues,
            "grid": self.grid,
            "wings": self.wings,
            "presence": self.presence,
            "overall": self.overall,
            "landmarks": self.landmarks,
            "meta": self.meta,
        }


def presence_scores(pairs: list[MatchedContract], venues: list[str]) -> dict[str, Any]:
    hub = _hub_pairs(pairs)
    eligible = []
    for p in hub:
        ad = _pair_abs_delta(p)
        if ad is not None and ad >= PRESENCE_MIN_ABS_DELTA:
            eligible.append(p)
    base = eligible or hub
    out: dict[str, Any] = {"n_eligible": len(base), "per_venue": {}}
    for v in venues:
        n_two = 0
        n = 0
        for p in base:
            row = _row_for_venue(p, v)
            if row is None:
                continue
            n += 1
            if venue_metrics(row)["two_sided"]:
                n_two += 1
        rate = (n_two / n) if n else 0.0
        out["per_venue"][v] = {
            "n": n,
            "n_two_sided": n_two,
            "two_sided_rate": rate,
            "score": 10.0 * rate,
        }
    return out


def _cell_for_tenor_delta(
    pairs: list[MatchedContract],
    expiries: dict[int, float],
    venues: list[str],
    *,
    tenor: str,
    delta_label: str,
    target_delta: float,
    landmarks_out: list[dict[str, Any]],
) -> dict[str, Any]:
    """Average across tenor targets, each target = avg(call, put)."""
    max_gap = TENOR_MAX_GAP[tenor]
    target_dtes = TENOR_TARGETS[tenor]
    per_target_venue: dict[str, list[dict[str, Any]]] = {v: [] for v in venues}
    used = 0

    for td in target_dtes:
        hit = nearest_expiry(expiries, td, max_gap=max_gap)
        if hit is None:
            continue
        exp_ms, listed_dte = hit
        call_pick = nearest_pair(pairs, expiry_utc_ms=exp_ms, target_abs_delta=target_delta, is_call=True)
        put_pick = nearest_pair(pairs, expiry_utc_ms=exp_ms, target_abs_delta=target_delta, is_call=False)
        if call_pick is None and put_pick is None:
            continue
        used += 1
        call_pair = call_pick.pair if call_pick else None
        put_pair = put_pick.pair if put_pick else None
        metrics = _avg_call_put(venues, call_pair, put_pair, delta_label=delta_label)
        for v in venues:
            per_target_venue[v].append(metrics[v])
        landmarks_out.append(
            {
                "tenor": tenor,
                "target_dte": td,
                "listed_dte": listed_dte,
                "expiry_utc_ms": exp_ms,
                "delta_label": delta_label,
                "target_delta": target_delta,
                "call": {
                    "strike": call_pair.key.strike if call_pair else None,
                    "abs_delta": call_pick.abs_delta if call_pick else None,
                    "symbol_deribit": (call_pair.deribit or {}).get("venue_symbol") if call_pair else None,
                    "symbol_coincall": (call_pair.coincall or {}).get("venue_symbol") if call_pair else None,
                },
                "put": {
                    "strike": put_pair.key.strike if put_pair else None,
                    "abs_delta": put_pick.abs_delta if put_pick else None,
                    "symbol_deribit": (put_pair.deribit or {}).get("venue_symbol") if put_pair else None,
                    "symbol_coincall": (put_pair.coincall or {}).get("venue_symbol") if put_pair else None,
                },
                "venues": {
                    v: {
                        "spread_pct": metrics[v]["spread_pct"],
                        "lift_effective_pct": metrics[v]["lift_effective_pct"],
                        "depth_usd": metrics[v]["depth_usd"],
                        "score": metrics[v]["score"],
                    }
                    for v in venues
                },
            }
        )

    cell: dict[str, Any] = {"tenor": tenor, "delta": delta_label, "n_targets_used": used, "venues": {}}
    for v in venues:
        rows = per_target_venue[v]
        if not rows:
            cell["venues"][v] = {
                "spread_pct": None,
                "lift_effective_pct": None,
                "depth_usd": None,
                "score": 0.0,
            }
            continue
        cell["venues"][v] = {
            "spread_pct": _mean([r["spread_pct"] for r in rows]),
            "lift_effective_pct": _mean([r["lift_effective_pct"] for r in rows]),
            "depth_usd": _mean([r["depth_usd"] for r in rows]),
            "score": _mean_scores([float(r["score"]) for r in rows]),
        }
    return cell


def build_scorecard(pairs: list[MatchedContract], *, ts_ms: int) -> ScorecardResult:
    venues = _venues_from_pairs(pairs)
    matched = _hub_pairs(pairs)
    expiries = _expiries(matched, ts_ms)
    landmarks: list[dict[str, Any]] = []

    grid_cells: dict[str, dict[str, Any]] = {}
    grid_scores: dict[str, list[float]] = {v: [] for v in venues}

    for tenor in TENOR_TARGETS:
        for d_label, d_target in DELTA_TARGETS.items():
            key = f"{tenor}:{d_label}"
            cell = _cell_for_tenor_delta(
                matched,
                expiries,
                venues,
                tenor=tenor,
                delta_label=d_label,
                target_delta=d_target,
                landmarks_out=landmarks,
            )
            grid_cells[key] = cell
            for v in venues:
                grid_scores[v].append(float(cell["venues"][v]["score"]))

    wing_cells: dict[str, Any] = {}
    wing_scores: dict[str, list[float]] = {v: [] for v in venues}
    for tenor in TENOR_TARGETS:
        key = f"{tenor}:{WING_LABEL}"
        cell = _cell_for_tenor_delta(
            matched,
            expiries,
            venues,
            tenor=tenor,
            delta_label=WING_LABEL,
            target_delta=WING_DELTA,
            landmarks_out=landmarks,
        )
        wing_cells[key] = cell
        for v in venues:
            wing_scores[v].append(float(cell["venues"][v]["score"]))

    presence = presence_scores(matched, venues)

    overall: dict[str, float] = {}
    for v in venues:
        g = _mean_scores(grid_scores[v])
        w = _mean_scores(wing_scores[v])
        p = float(presence["per_venue"][v]["score"])
        overall[v] = (
            OVERALL_WEIGHTS["grid"] * g
            + OVERALL_WEIGHTS["wings"] * w
            + OVERALL_WEIGHTS["presence"] * p
        )

    n_with_delta = sum(1 for p in matched if _pair_abs_delta(p) is not None)
    return ScorecardResult(
        ts_ms=ts_ms,
        venues=venues,
        grid=grid_cells,
        wings=wing_cells,
        presence=presence,
        overall=overall,
        landmarks=landmarks,
        meta={
            "n_matched": len(matched),
            "n_with_delta": n_with_delta,
            "n_expiries": len(expiries),
            "n_snapshots": 1,
            "notional_usd": NOTIONAL_USD,
            "weights": dict(OVERALL_WEIGHTS),
            "cell_weights": dict(CELL_WEIGHTS),
            "tenor_targets": {k: list(v) for k, v in TENOR_TARGETS.items()},
            "delta_targets": dict(DELTA_TARGETS),
            "wing_delta": WING_DELTA,
        },
    )


def hour_in_utc_window(hour: int, start: int, end: int) -> bool:
    """Return True if ``hour`` is in ``[start, end)`` UTC (supports wrap, e.g. 22→6)."""
    if not (0 <= start <= 24 and 0 <= end <= 24):
        raise ValueError(f"hours must be in 0..24, got {start=}, {end=}")
    if start == end:
        return True  # full day
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def filter_raw_books(
    df: pd.DataFrame,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    utc_hour_start: int | None = None,
    utc_hour_end: int | None = None,
) -> pd.DataFrame:
    """Filter raw_books rows by absolute ts range and/or UTC clock hours.

    ``utc_hour_start`` / ``utc_hour_end`` use ``[start, end)`` (end exclusive).
    Example: 12→18 keeps snapshots whose UTC hour is 12,13,14,15,16,17.
    """
    if df.empty:
        return df
    if "ts" not in df.columns:
        raise KeyError("raw_books frame needs a 'ts' column")
    out = df
    if start_ms is not None:
        out = out[out["ts"] >= start_ms]
    if end_ms is not None:
        out = out[out["ts"] < end_ms]
    if utc_hour_start is not None or utc_hour_end is not None:
        if utc_hour_start is None or utc_hour_end is None:
            raise ValueError("utc_hour_start and utc_hour_end must both be set")
        hours = out["ts"].map(
            lambda t: datetime.fromtimestamp(int(t) / 1000, tz=UTC).hour
        )
        mask = hours.map(lambda h: hour_in_utc_window(int(h), utc_hour_start, utc_hour_end))
        out = out[mask]
    return out.reset_index(drop=True)


def _avg_venue_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "spread_pct": None,
            "lift_effective_pct": None,
            "depth_usd": None,
            "score": 0.0,
        }
    return {
        "spread_pct": _mean([r.get("spread_pct") for r in rows]),
        "lift_effective_pct": _mean([r.get("lift_effective_pct") for r in rows]),
        "depth_usd": _mean([r.get("depth_usd") for r in rows]),
        "score": _mean_scores([float(r.get("score") or 0.0) for r in rows]),
    }


def aggregate_scorecards(cards: list[ScorecardResult]) -> ScorecardResult:
    """Mean scorecard across snapshots (equal weight per snapshot).

    Presence rates/scores are averaged; ``n`` / ``n_two_sided`` are summed.
    Landmarks are omitted (too noisy across time); see per-snapshot cards if needed.
    """
    if not cards:
        raise ValueError("no scorecards to aggregate")
    if len(cards) == 1:
        return cards[0]

    preferred = ["deribit", "coincall"]
    found: set[str] = set()
    for c in cards:
        found.update(c.venues)
    venues = [v for v in preferred if v in found] + sorted(found - set(preferred))

    def _agg_block(getter) -> dict[str, Any]:
        keys: set[str] = set()
        for c in cards:
            keys.update(getter(c).keys())
        out: dict[str, Any] = {}
        for key in sorted(keys):
            n_used = []
            per_v: dict[str, list[dict[str, Any]]] = {v: [] for v in venues}
            tenor = delta = None
            for c in cards:
                block = getter(c)
                if key not in block:
                    continue
                cell = block[key]
                tenor = cell.get("tenor", tenor)
                delta = cell.get("delta", delta)
                n_used.append(int(cell.get("n_targets_used") or 0))
                for v in venues:
                    if v in cell.get("venues", {}):
                        per_v[v].append(cell["venues"][v])
            out[key] = {
                "tenor": tenor,
                "delta": delta,
                "n_targets_used": int(round(_mean_scores([float(x) for x in n_used]))) if n_used else 0,
                "venues": {v: _avg_venue_metrics(per_v[v]) for v in venues},
            }
        return out

    grid = _agg_block(lambda c: c.grid)
    wings = _agg_block(lambda c: c.wings)

    presence: dict[str, Any] = {"n_eligible": 0, "per_venue": {}}
    elig = [int(c.presence.get("n_eligible") or 0) for c in cards]
    presence["n_eligible"] = int(round(_mean_scores([float(x) for x in elig]))) if elig else 0
    for v in venues:
        rates, scores, ns, n2 = [], [], [], []
        for c in cards:
            pv = (c.presence.get("per_venue") or {}).get(v)
            if not pv:
                continue
            rates.append(float(pv.get("two_sided_rate") or 0.0))
            scores.append(float(pv.get("score") or 0.0))
            ns.append(int(pv.get("n") or 0))
            n2.append(int(pv.get("n_two_sided") or 0))
        presence["per_venue"][v] = {
            "n": sum(ns),
            "n_two_sided": sum(n2),
            "two_sided_rate": _mean_scores(rates) if rates else 0.0,
            "score": _mean_scores(scores) if scores else 0.0,
        }

    overall = {
        v: _mean_scores([float(c.overall[v]) for c in cards if v in c.overall]) for v in venues
    }

    ts_list = sorted(c.ts_ms for c in cards)
    return ScorecardResult(
        ts_ms=ts_list[-1],
        venues=venues,
        grid=grid,
        wings=wings,
        presence=presence,
        overall=overall,
        landmarks=[],
        meta={
            "n_snapshots": len(cards),
            "ts_ms_first": ts_list[0],
            "ts_ms_last": ts_list[-1],
            "n_matched_mean": _mean(
                [float(c.meta.get("n_matched") or 0) for c in cards]
            ),
            "n_with_delta_mean": _mean(
                [float(c.meta.get("n_with_delta") or 0) for c in cards]
            ),
            "notional_usd": NOTIONAL_USD,
            "weights": dict(OVERALL_WEIGHTS),
            "cell_weights": dict(CELL_WEIGHTS),
            "aggregated": True,
        },
    )


def build_scorecards_from_raw(
    df: pd.DataFrame,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    utc_hour_start: int | None = None,
    utc_hour_end: int | None = None,
) -> list[ScorecardResult]:
    """One scorecard per distinct snapshot ``ts`` in filtered raw_books."""
    filtered = filter_raw_books(
        df,
        start_ms=start_ms,
        end_ms=end_ms,
        utc_hour_start=utc_hour_start,
        utc_hour_end=utc_hour_end,
    )
    if filtered.empty:
        return []
    cards: list[ScorecardResult] = []
    for ts, group in filtered.groupby("ts", sort=True):
        rows = group.to_dict(orient="records")
        pairs = match_raw_rows(rows)
        if not pairs:
            logger.warning("No pairs for ts=%s — skipping", ts)
            continue
        cards.append(build_scorecard(pairs, ts_ms=int(ts)))
    return cards


def build_scorecard_period(
    df: pd.DataFrame,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    utc_hour_start: int | None = None,
    utc_hour_end: int | None = None,
) -> ScorecardResult:
    """Aggregate landmark scorecard over many raw_books snapshots.

    Requires L5 + ``delta`` on raw rows (as written by the daemon after enrichment).
    """
    cards = build_scorecards_from_raw(
        df,
        start_ms=start_ms,
        end_ms=end_ms,
        utc_hour_start=utc_hour_start,
        utc_hour_end=utc_hour_end,
    )
    if not cards:
        raise ValueError("no snapshots in window to score")
    card = aggregate_scorecards(cards)
    card.meta["filter"] = {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "utc_hour_start": utc_hour_start,
        "utc_hour_end": utc_hour_end,
    }
    return card


def build_scorecard_from_store(
    data_dir: Path | str,
    *,
    dates: list[str] | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    utc_hour_start: int | None = None,
    utc_hour_end: int | None = None,
) -> ScorecardResult:
    """Load raw_books from ``ParquetStore`` and build a period scorecard."""
    from cryobookq.pipeline.write import ParquetStore

    store = ParquetStore(Path(data_dir))
    df = store.load_raw_books(dates)
    if df.empty:
        raise ValueError(f"no raw_books under {data_dir}")
    return build_scorecard_period(
        df,
        start_ms=start_ms,
        end_ms=end_ms,
        utc_hour_start=utc_hour_start,
        utc_hour_end=utc_hour_end,
    )


def format_scorecard(card: ScorecardResult) -> str:
    """Human-readable report for CLI / acceptance."""

    def _fmt(x: float | None, width: int = 6, suffix: str = "") -> str:
        if x is None:
            return f"{'n/a':>{width}}{suffix}"
        return f"{x:{width}.2f}{suffix}"

    lines: list[str] = []
    n_snap = int(card.meta.get("n_snapshots") or 1)
    lines.append(
        f"Scorecard venues={','.join(card.venues)}  snapshots={n_snap}  "
        f"ts_last={card.ts_ms}"
    )
    if card.meta.get("aggregated"):
        lines.append(
            f"period ts_ms {card.meta.get('ts_ms_first')} → {card.meta.get('ts_ms_last')}  "
            f"matched_mean={card.meta.get('n_matched_mean')}  "
            f"delta_mean={card.meta.get('n_with_delta_mean')}"
        )
        filt = card.meta.get("filter") or {}
        if any(filt.get(k) is not None for k in filt):
            lines.append(f"filter={filt}")
    else:
        lines.append(
            f"matched={card.meta.get('n_matched')} with_delta={card.meta.get('n_with_delta')} "
            f"expiries={card.meta.get('n_expiries')}"
        )
    lines.append("")
    lines.append("=== Overall (0–10) ===")
    ranked = sorted(card.overall.items(), key=lambda kv: -kv[1])
    for i, (v, s) in enumerate(ranked, 1):
        lines.append(f"  #{i} {v:12s}  {s:5.2f}")
    lines.append("")
    lines.append("=== Presence (|Δ|≥0.05 matched) ===")
    for v in card.venues:
        pv = card.presence["per_venue"][v]
        lines.append(
            f"  {v:12s}  two_sided={pv['two_sided_rate']:.1%}  "
            f"({pv['n_two_sided']}/{pv['n']})  score={pv['score']:.2f}"
        )
    lines.append("")
    lines.append("=== Grid 3×3 (spread% | $10k eff% | depth$k | score) ===")
    for tenor in TENOR_TARGETS:
        for d_label in DELTA_TARGETS:
            key = f"{tenor}:{d_label}"
            cell = card.grid[key]
            parts = [f"{key:16s}"]
            for v in card.venues:
                m = cell["venues"][v]
                dp = None if m["depth_usd"] is None else m["depth_usd"] / 1000.0
                parts.append(
                    f"{v[:3]}:"
                    f"{_fmt(m['spread_pct'], 5, '%')}|"
                    f"{_fmt(m['lift_effective_pct'], 5, '%')}|"
                    f"{_fmt(dp, 6)}|"
                    f"{m['score']:4.1f}"
                )
            lines.append("  ".join(parts))
    lines.append("")
    lines.append("=== Wings 2.5δ ===")
    for tenor in TENOR_TARGETS:
        key = f"{tenor}:{WING_LABEL}"
        cell = card.wings[key]
        parts = [f"{key:16s}"]
        for v in card.venues:
            m = cell["venues"][v]
            parts.append(f"{v}={m['score']:.1f}(spr {_fmt(m['spread_pct'], 5, '%')})")
        lines.append("  ".join(parts))
    lines.append("")
    lines.append("=== Subject means ===")
    for v in card.venues:
        gs = [
            float(card.grid[f"{t}:{d}"]["venues"][v]["score"])
            for t in TENOR_TARGETS
            for d in DELTA_TARGETS
        ]
        ws = [
            float(card.wings[f"{t}:{WING_LABEL}"]["venues"][v]["score"]) for t in TENOR_TARGETS
        ]
        lines.append(
            f"  {v:12s}  grid={_mean_scores(gs):.2f}  wings={_mean_scores(ws):.2f}  "
            f"presence={card.presence['per_venue'][v]['score']:.2f}"
        )
    return "\n".join(lines)
