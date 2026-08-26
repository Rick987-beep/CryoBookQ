"""Per-pair book quality metrics and winners."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from cryobookq.pipeline.match import MatchedPair

# Composite weights (documented in docs/SCORING.md). Lower spread / cost is better;
# higher depth is better. Each component is 0–1 after normalization within the pair.
COMPOSITE_WEIGHTS = {
    "spread": 0.35,
    "cost_buy": 0.25,
    "cost_sell": 0.25,
    "depth": 0.15,
}

SESSION_WINDOWS = {
    # (start_hour_utc inclusive, end_hour_utc exclusive)
    "Asia": (0, 8),
    "EU": (8, 14),
    "US": (14, 21),
    "Off": (21, 24),
}

DTE_BUCKETS = [
    (0, 2, "0-2"),
    (3, 7, "3-7"),
    (8, 30, "8-30"),
    (31, 90, "31-90"),
    (91, 10_000, "90+"),
]

DELTA_BUCKETS = [
    (0.0, 0.05, "0-0.05"),
    (0.05, 0.15, "0.05-0.15"),
    (0.15, 0.30, "0.15-0.30"),
    (0.30, 0.50, "0.30-0.50"),
    (0.50, 1.01, "0.50+"),
]


def session_for_ts(ts_ms: int) -> str:
    hour = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).hour
    for name, (lo, hi) in SESSION_WINDOWS.items():
        if lo <= hour < hi:
            return name
    return "Off"


def dte_for(expiry_utc_ms: int, ts_ms: int) -> float:
    return max(0.0, (expiry_utc_ms - ts_ms) / (1000 * 86400))


def dte_bucket(dte: float) -> str:
    d = int(math.floor(dte))
    for lo, hi, name in DTE_BUCKETS:
        if lo <= d <= hi:
            return name
    return "90+"


def delta_bucket(abs_delta: float | None) -> str | None:
    if abs_delta is None or (isinstance(abs_delta, float) and math.isnan(abs_delta)):
        return None
    for lo, hi, name in DELTA_BUCKETS:
        if lo <= abs_delta < hi:
            return name
    return None


def _levels(row: dict, side: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for i in range(1, 6):
        px = float(row.get(f"{side}_px_{i}") or 0)
        sz = float(row.get(f"{side}_sz_{i}") or 0)
        if px > 0 and sz > 0:
            out.append((px, sz))
    return out


def venue_metrics(row: dict | None) -> dict[str, Any]:
    """Compute quality metrics for one normalized USD book row."""
    empty = {
        "two_sided": False,
        "spread_usd": None,
        "spread_bps": None,
        "mid_usd": None,
        "bid_sz_1": 0.0,
        "ask_sz_1": 0.0,
        "depth_btc_L5": 0.0,
        "cost_buy_1btc": None,
        "cost_sell_1btc": None,
        "venue_symbol": None,
    }
    if row is None:
        return empty

    bids = _levels(row, "bid")
    asks = _levels(row, "ask")
    two_sided = bool(bids and asks)
    bid1 = bids[0][0] if bids else 0.0
    ask1 = asks[0][0] if asks else 0.0
    bid_sz1 = bids[0][1] if bids else 0.0
    ask_sz1 = asks[0][1] if asks else 0.0
    mid = (bid1 + ask1) / 2.0 if two_sided else None
    spread = (ask1 - bid1) if two_sided else None
    spread_bps = (spread / mid * 10_000) if mid and spread is not None and mid > 0 else None
    depth = sum(sz for _, sz in bids) + sum(sz for _, sz in asks)

    return {
        "two_sided": two_sided,
        "spread_usd": spread,
        "spread_bps": spread_bps,
        "mid_usd": mid,
        "bid_sz_1": bid_sz1,
        "ask_sz_1": ask_sz1,
        "depth_btc_L5": depth,
        "cost_buy_1btc": walk_cost(asks, qty=1.0),
        "cost_sell_1btc": walk_cost(bids, qty=1.0),
        "venue_symbol": row.get("venue_symbol"),
    }


def walk_cost(levels: list[tuple[float, float]], qty: float = 1.0) -> float | None:
    """VWAP cost to buy (asks) or sell (bids) *qty* BTC; None if insufficient depth."""
    if qty <= 0 or not levels:
        return None
    remaining = qty
    notional = 0.0
    filled = 0.0
    for px, sz in levels:
        take = min(remaining, sz)
        notional += take * px
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    if filled + 1e-12 < qty:
        return None
    return notional / filled


def _better_lower(a: float | None, b: float | None) -> str | None:
    if a is None and b is None:
        return None
    if a is None:
        return "coincall"
    if b is None:
        return "deribit"
    if a < b:
        return "deribit"
    if b < a:
        return "coincall"
    return "tie"


def _better_higher(a: float | None, b: float | None) -> str | None:
    if a is None and b is None:
        return None
    if a is None:
        return "coincall"
    if b is None:
        return "deribit"
    if a > b:
        return "deribit"
    if b > a:
        return "coincall"
    return "tie"


def _norm_pair(a: float | None, b: float | None, *, lower_better: bool) -> tuple[float, float]:
    """Map pair values to [0,1] scores (1 = better). Missing → 0."""
    if a is None and b is None:
        return 0.0, 0.0
    if a is None:
        return 0.0, 1.0
    if b is None:
        return 1.0, 0.0
    if a == b:
        return 0.5, 0.5
    lo, hi = min(a, b), max(a, b)
    span = hi - lo
    if span <= 0:
        return 0.5, 0.5
    if lower_better:
        return (hi - a) / span, (hi - b) / span
    return (a - lo) / span, (b - lo) / span


def composite_scores(d: dict[str, Any], c: dict[str, Any]) -> tuple[float, float]:
    ds, cs = _norm_pair(d["spread_usd"], c["spread_usd"], lower_better=True)
    db, cb = _norm_pair(d["cost_buy_1btc"], c["cost_buy_1btc"], lower_better=True)
    dsl, csl = _norm_pair(d["cost_sell_1btc"], c["cost_sell_1btc"], lower_better=True)
    dd, cd = _norm_pair(d["depth_btc_L5"], c["depth_btc_L5"], lower_better=False)
    w = COMPOSITE_WEIGHTS
    der = w["spread"] * ds + w["cost_buy"] * db + w["cost_sell"] * dsl + w["depth"] * dd
    coin = w["spread"] * cs + w["cost_buy"] * cb + w["cost_sell"] * csl + w["depth"] * cd
    return der, coin


def score_pair(pair: MatchedPair, *, ts_ms: int) -> dict[str, Any]:
    d = venue_metrics(pair.deribit)
    c = venue_metrics(pair.coincall)
    abs_delta = None
    for row in (pair.deribit, pair.coincall):
        if row and row.get("delta") is not None:
            abs_delta = abs(float(row["delta"]))
            break

    dte = dte_for(pair.key.expiry_utc_ms, ts_ms)
    weekday = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%A")

    rel_mid = None
    if d["mid_usd"] and c["mid_usd"] and d["mid_usd"] > 0:
        rel_mid = (c["mid_usd"] - d["mid_usd"]) / d["mid_usd"] * 10_000

    comp_d, comp_c = composite_scores(d, c)
    if pair.match_status != "matched":
        winner_comp = None
    elif comp_d > comp_c:
        winner_comp = "deribit"
    elif comp_c > comp_d:
        winner_comp = "coincall"
    else:
        winner_comp = "tie"

    return {
        "ts": ts_ms,
        "underlying": pair.key.underlying,
        "expiry_utc_ms": pair.key.expiry_utc_ms,
        "strike": pair.key.strike,
        "is_call": pair.key.is_call,
        "match_status": pair.match_status,
        "dte": dte,
        "session": session_for_ts(ts_ms),
        "weekday": weekday,
        "abs_delta": abs_delta,
        "dte_bucket": dte_bucket(dte),
        "delta_bucket": delta_bucket(abs_delta),
        "deribit_two_sided": d["two_sided"],
        "deribit_spread_usd": d["spread_usd"],
        "deribit_spread_bps": d["spread_bps"],
        "deribit_mid_usd": d["mid_usd"],
        "deribit_bid_sz_1": d["bid_sz_1"],
        "deribit_ask_sz_1": d["ask_sz_1"],
        "deribit_depth_btc_L5": d["depth_btc_L5"],
        "deribit_cost_buy_1btc": d["cost_buy_1btc"],
        "deribit_cost_sell_1btc": d["cost_sell_1btc"],
        "deribit_venue_symbol": d["venue_symbol"],
        "coincall_two_sided": c["two_sided"],
        "coincall_spread_usd": c["spread_usd"],
        "coincall_spread_bps": c["spread_bps"],
        "coincall_mid_usd": c["mid_usd"],
        "coincall_bid_sz_1": c["bid_sz_1"],
        "coincall_ask_sz_1": c["ask_sz_1"],
        "coincall_depth_btc_L5": c["depth_btc_L5"],
        "coincall_cost_buy_1btc": c["cost_buy_1btc"],
        "coincall_cost_sell_1btc": c["cost_sell_1btc"],
        "coincall_venue_symbol": c["venue_symbol"],
        "rel_mid_bps": rel_mid,
        "winner_spread": _better_lower(d["spread_usd"], c["spread_usd"]) if pair.match_status == "matched" else None,
        "winner_cost_buy": _better_lower(d["cost_buy_1btc"], c["cost_buy_1btc"]) if pair.match_status == "matched" else None,
        "winner_cost_sell": _better_lower(d["cost_sell_1btc"], c["cost_sell_1btc"]) if pair.match_status == "matched" else None,
        "winner_depth": _better_higher(d["depth_btc_L5"], c["depth_btc_L5"]) if pair.match_status == "matched" else None,
        "composite_deribit": comp_d if pair.match_status == "matched" else None,
        "composite_coincall": comp_c if pair.match_status == "matched" else None,
        "winner_composite": winner_comp,
    }


def score_pairs(pairs: list[MatchedPair], *, ts_ms: int) -> list[dict[str, Any]]:
    return [score_pair(p, ts_ms=ts_ms) for p in pairs]
