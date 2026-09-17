"""Short iron-condor round-trip friction (The flight of the condor).

Structure
---------
Nearest Deribit-listed expiry to **30 days**, max gap 15 days
(BTC monthlies often sit ~22d or ~43d; a 5-day window misses both).
Sell call + put nearest |delta| = 0.40; buy call + put nearest |delta| = 0.25.

100% is the structure mid (net credit, 1 BTC of option size), not Bitcoin:

    mid = (mid_short_call + mid_short_put) − (mid_long_call + mid_long_put)

Open + close vs that mid
------------------------
* Spread: one full top-of-book width per leg (open half-spread + close half-spread).
* Fees: eight standard-tier **taker** fills (open and close on each of four legs).
  Fee USD still uses the exchange formula (rate × BTC index, capped vs that leg's premium).

    leftover_pct = 100 × (mid − spread_usd − fee_usd) / mid

The hub shows leftover_pct (higher is better). A venue is omitted when any leg
is missing/one-sided, index is unknown, or mid credit is not positive.
"""

from __future__ import annotations

from typing import Any

from cryobookq.analytics.scorecard import (
    MAX_DELTA_GAP,
    _expiries,
    _mean,
    nearest_expiry,
    nearest_pair,
)
from cryobookq.fees import taker_fee_usd
from cryobookq.pipeline.match import MatchedContract
from cryobookq.pipeline.score import venue_metrics

# Locked structure for the hub strip.
CONDOR_TARGET_DTE = 30.0
CONDOR_MAX_DTE_GAP = 15.0
CONDOR_SHORT_ABS_DELTA = 0.40
CONDOR_LONG_ABS_DELTA = 0.25

_LEG_SPEC: tuple[tuple[str, float, bool], ...] = (
    ("short_call", CONDOR_SHORT_ABS_DELTA, True),
    ("short_put", CONDOR_SHORT_ABS_DELTA, False),
    ("long_call", CONDOR_LONG_ABS_DELTA, True),
    ("long_put", CONDOR_LONG_ABS_DELTA, False),
)


def _index_px(pairs: list[MatchedContract]) -> float | None:
    """First positive ``index_px`` on any book row (USD BTC index)."""
    for p in pairs:
        for row in p.books.values():
            if not row:
                continue
            try:
                px = float(row.get("index_px") or 0)
            except (TypeError, ValueError):
                continue
            if px > 0:
                return px
    return None


def pick_condor_legs(
    pairs: list[MatchedContract],
    *,
    ts_ms: int,
) -> dict[str, Any] | None:
    """Pick the four IC legs, or ``None`` if expiry/delta/structure fails."""
    expiries = _expiries(pairs, ts_ms)
    hit = nearest_expiry(expiries, CONDOR_TARGET_DTE, max_gap=CONDOR_MAX_DTE_GAP)
    if hit is None:
        return None
    exp_ms, listed_dte = hit
    legs: dict[str, Any] = {}
    for name, target, is_call in _LEG_SPEC:
        pick = nearest_pair(
            pairs,
            expiry_utc_ms=exp_ms,
            target_abs_delta=target,
            is_call=is_call,
            max_delta_gap=MAX_DELTA_GAP,
        )
        if pick is None:
            return None
        legs[name] = pick

    # Degenerate condor: inner and outer landed on the same strike.
    if legs["short_call"].pair.key == legs["long_call"].pair.key:
        return None
    if legs["short_put"].pair.key == legs["long_put"].pair.key:
        return None

    return {
        "expiry_utc_ms": exp_ms,
        "listed_dte": listed_dte,
        "legs": legs,
    }


def _venue_round_trip(
    legs: dict[str, Any],
    venue: str,
    *,
    index_usd: float,
) -> dict[str, float] | None:
    """Spread + 8 taker fees vs the short-IC mid credit on this venue."""
    mids: dict[str, float] = {}
    spread_usd = 0.0
    fee_usd = 0.0
    for name, pick in legs.items():
        row = pick.pair.books.get(venue)
        m = venue_metrics(row)
        if not m["two_sided"] or m["spread_usd"] is None or not m["mid_usd"]:
            return None
        mid = float(m["mid_usd"])
        mids[name] = mid
        spread_usd += float(m["spread_usd"])
        one_fill = taker_fee_usd(
            venue,
            index_usd=index_usd,
            premium_usd=mid,
            size_btc=1.0,
        )
        if one_fill is None:
            return None
        # Open + close, both modelled as taker at the snapshot mid.
        fee_usd += 2.0 * one_fill

    mid_credit = (mids["short_call"] + mids["short_put"]) - (mids["long_call"] + mids["long_put"])
    if mid_credit <= 0:
        return None
    rt_usd = spread_usd + fee_usd
    leftover_pct = (mid_credit - rt_usd) / mid_credit * 100.0
    return {
        "mid_credit_usd": mid_credit,
        "spread_usd": spread_usd,
        "fee_usd": fee_usd,
        "rt_usd": rt_usd,
        "rt_pct_of_mid": rt_usd / mid_credit * 100.0,
        "leftover_pct_of_mid": leftover_pct,
        "n_legs": 4.0,
    }


def iron_condor_snapshot(
    pairs: list[MatchedContract],
    venues: list[str],
    *,
    ts_ms: int,
) -> dict[str, Any]:
    """Per-venue round-trip cost for one snapshot. Empty ``per_venue`` if unusable."""
    spec = {
        "target_dte": CONDOR_TARGET_DTE,
        "max_dte_gap": CONDOR_MAX_DTE_GAP,
        "short_abs_delta": CONDOR_SHORT_ABS_DELTA,
        "long_abs_delta": CONDOR_LONG_ABS_DELTA,
    }
    empty: dict[str, Any] = {
        "spec": spec,
        "listed_dte": None,
        "expiry_utc_ms": None,
        "index_px": None,
        "per_venue": {v: None for v in venues},
    }
    picked = pick_condor_legs(pairs, ts_ms=ts_ms)
    if picked is None:
        return empty
    index_px = _index_px(pairs)
    if index_px is None:
        return empty

    per_venue: dict[str, dict[str, float] | None] = {}
    for v in venues:
        per_venue[v] = _venue_round_trip(picked["legs"], v, index_usd=index_px)
    return {
        "spec": spec,
        "listed_dte": picked["listed_dte"],
        "expiry_utc_ms": picked["expiry_utc_ms"],
        "index_px": index_px,
        "per_venue": per_venue,
    }


def aggregate_condor(cards: list[Any]) -> dict[str, Any]:
    """Equal-weight mean of per-snapshot condor metrics (skip null venues)."""
    if not cards:
        return {"spec": {}, "listed_dte": None, "expiry_utc_ms": None, "index_px": None, "per_venue": {}}

    first = cards[0].condor if getattr(cards[0], "condor", None) else {}
    spec = dict(first.get("spec") or {})
    venues: list[str] = []
    seen: set[str] = set()
    for c in cards:
        for v in c.venues:
            if v not in seen:
                seen.add(v)
                venues.append(v)

    dtes = [float(c.condor["listed_dte"]) for c in cards if (c.condor or {}).get("listed_dte") is not None]
    idxs = [float(c.condor["index_px"]) for c in cards if (c.condor or {}).get("index_px") is not None]

    per_venue: dict[str, dict[str, float] | None] = {}
    for v in venues:
        rows: list[dict[str, float]] = []
        for c in cards:
            row = (c.condor or {}).get("per_venue", {}).get(v)
            if isinstance(row, dict) and row.get("leftover_pct_of_mid") is not None:
                rows.append(row)
        if not rows:
            per_venue[v] = None
            continue
        per_venue[v] = {
            "mid_credit_usd": _mean([r.get("mid_credit_usd") for r in rows]) or 0.0,
            "spread_usd": _mean([r.get("spread_usd") for r in rows]) or 0.0,
            "fee_usd": _mean([r.get("fee_usd") for r in rows]) or 0.0,
            "rt_usd": _mean([r.get("rt_usd") for r in rows]) or 0.0,
            "rt_pct_of_mid": _mean([r.get("rt_pct_of_mid") for r in rows]) or 0.0,
            "leftover_pct_of_mid": _mean([r.get("leftover_pct_of_mid") for r in rows]) or 0.0,
            "n_legs": 4.0,
            "n_snaps": float(len(rows)),
        }

    return {
        "spec": spec,
        "listed_dte": _mean(dtes),
        "expiry_utc_ms": None,
        "index_px": _mean(idxs),
        "per_venue": per_venue,
        "aggregated": True,
    }
