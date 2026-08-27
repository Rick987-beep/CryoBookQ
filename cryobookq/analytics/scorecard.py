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

import math
from dataclasses import dataclass, field
from typing import Any

from cryobookq.pipeline.match import MatchedPair
from cryobookq.pipeline.score import dte_for, venue_metrics

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
    pair: MatchedPair
    abs_delta: float


def _pair_abs_delta(pair: MatchedPair) -> float | None:
    for row in (pair.deribit, pair.coincall):
        if row is None:
            continue
        d = row.get("delta")
        if d is not None:
            try:
                return abs(float(d))
            except (TypeError, ValueError):
                continue
    return None


def _expiries(pairs: list[MatchedPair], ts_ms: int) -> dict[int, float]:
    """expiry_utc_ms → dte."""
    out: dict[int, float] = {}
    for p in pairs:
        if p.match_status != "matched":
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
    pairs: list[MatchedPair],
    *,
    expiry_utc_ms: int,
    target_abs_delta: float,
    is_call: bool,
    max_delta_gap: float = MAX_DELTA_GAP,
) -> LandmarkPick | None:
    candidates: list[tuple[float, MatchedPair, float]] = []
    for p in pairs:
        if p.match_status != "matched":
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
    cell = _mean_scores([spread_s, size_s, depth_s])
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


def _row_for_venue(pair: MatchedPair | None, venue: str) -> dict[str, Any] | None:
    if pair is None:
        return None
    if venue == "deribit":
        return pair.deribit
    if venue == "coincall":
        return pair.coincall
    for row in (pair.deribit, pair.coincall):
        if row is not None and row.get("venue") == venue:
            return row
    return None


def _avg_call_put(
    venues: list[str],
    call_pair: MatchedPair | None,
    put_pair: MatchedPair | None,
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


def _venues_from_pairs(pairs: list[MatchedPair]) -> list[str]:
    found: set[str] = set()
    for p in pairs:
        for row in (p.deribit, p.coincall):
            if row and row.get("venue"):
                found.add(str(row["venue"]))
    # Stable preferred order, then any extras
    preferred = ["deribit", "coincall"]
    out = [v for v in preferred if v in found]
    out.extend(sorted(found - set(out)))
    return out or preferred


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


def presence_scores(pairs: list[MatchedPair], venues: list[str]) -> dict[str, Any]:
    matched = [p for p in pairs if p.match_status == "matched"]
    eligible = []
    for p in matched:
        ad = _pair_abs_delta(p)
        if ad is not None and ad >= PRESENCE_MIN_ABS_DELTA:
            eligible.append(p)
    base = eligible or matched
    out: dict[str, Any] = {"n_eligible": len(base), "per_venue": {}}
    for v in venues:
        n_two = 0
        n = 0
        for p in base:
            row = p.deribit if v == "deribit" else p.coincall if v == "coincall" else _row_for_venue(p, v)
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
    pairs: list[MatchedPair],
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


def build_scorecard(pairs: list[MatchedPair], *, ts_ms: int) -> ScorecardResult:
    venues = _venues_from_pairs(pairs)
    matched = [p for p in pairs if p.match_status == "matched"]
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
            "notional_usd": NOTIONAL_USD,
            "weights": dict(OVERALL_WEIGHTS),
            "tenor_targets": {k: list(v) for k, v in TENOR_TARGETS.items()},
            "delta_targets": dict(DELTA_TARGETS),
            "wing_delta": WING_DELTA,
        },
    )


def format_scorecard(card: ScorecardResult) -> str:
    """Human-readable report for CLI / acceptance."""

    def _fmt(x: float | None, width: int = 6, suffix: str = "") -> str:
        if x is None:
            return f"{'n/a':>{width}}{suffix}"
        return f"{x:{width}.2f}{suffix}"

    lines: list[str] = []
    lines.append(f"Scorecard ts_ms={card.ts_ms} venues={','.join(card.venues)}")
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
