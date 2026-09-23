"""Short iron-condor round-trip friction (The flight of the condor).

Structure
---------
Nearest expiry to **30 days** (max gap 15) on which **every** compared venue
has a two-sided book for the four legs. Calls and puts are chosen separately,
so the wings do not have to be symmetric.

Sell the call and the put whose |delta| is nearest 0.40. Buy a further-OTM
call and put whose |delta| is nearest 0.25 (higher strike for the call, lower
strike for the put). Delta is Deribit's. The same four contracts are priced
on every venue.

100% is the structure mid (net credit, 1 BTC of option size), not Bitcoin:

    mid = (mid_short_call + mid_short_put) − (mid_long_call + mid_long_put)

Open + close vs that mid
------------------------
* Spread: one full top-of-book width per leg (open half-spread + close half-spread).
* Fees: eight standard-tier **taker** fills (open and close on each of four legs).
  Fee USD still uses the exchange formula (rate × BTC index, capped vs that leg's premium).

    leftover_pct = 100 × (mid − spread_usd − fee_usd) / mid

The hub shows leftover_pct (higher is better). A venue is omitted when its
credit is not positive or its fee schedule is missing. If no expiry in range
has four shared two-sided legs, the strip is empty for everyone.
"""

from __future__ import annotations

from typing import Any

from cryobookq.analytics.scorecard import _expiries, _mean
from cryobookq.fees import taker_fee_usd
from cryobookq.pipeline.match import MatchedContract
from cryobookq.pipeline.score import venue_metrics

# Locked structure for the hub strip.
CONDOR_TARGET_DTE = 30.0
CONDOR_MAX_DTE_GAP = 15.0
CONDOR_SHORT_ABS_DELTA = 0.40
CONDOR_LONG_ABS_DELTA = 0.25


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


class _Leg:
    """Adapter so round-trip code can read ``leg.pair.books``."""

    __slots__ = ("pair",)

    def __init__(self, pair: MatchedContract) -> None:
        self.pair = pair


def _hub_abs_delta(pair: MatchedContract) -> float | None:
    row = pair.books.get("deribit")
    if row is None or row.get("delta") is None:
        for candidate in pair.books.values():
            if candidate and candidate.get("delta") is not None:
                row = candidate
                break
    if not row or row.get("delta") is None:
        return None
    try:
        return abs(float(row["delta"]))
    except (TypeError, ValueError):
        return None


def _quoted_on_all(pair: MatchedContract, venues: list[str]) -> bool:
    for venue in venues:
        metrics = venue_metrics(pair.books.get(venue))
        if not metrics["two_sided"] or not metrics["mid_usd"]:
            return False
    return True


def _pick_body_and_wing(
    candidates: list[MatchedContract],
    *,
    wing_is_further,
) -> tuple[MatchedContract, MatchedContract] | None:
    """Short leg nearest 40Δ, wing further OTM and nearest 25Δ."""
    scored = [(pair, delta) for pair in candidates if (delta := _hub_abs_delta(pair)) is not None]
    if not scored:
        return None
    short = min(scored, key=lambda item: (abs(item[1] - CONDOR_SHORT_ABS_DELTA), item[0].key.strike))[0]
    wings = [
        (pair, delta)
        for pair, delta in scored
        if wing_is_further(pair.key.strike, short.key.strike)
    ]
    if not wings:
        return None
    wing = min(wings, key=lambda item: (abs(item[1] - CONDOR_LONG_ABS_DELTA), item[0].key.strike))[0]
    return short, wing


def pick_condor_legs(
    pairs: list[MatchedContract],
    *,
    venues: list[str],
    ts_ms: int,
) -> dict[str, Any] | None:
    """Pick four shared legs, or ``None`` if no expiry in range qualifies.

    A contract counts only when every venue in *venues* has a two-sided book.
    Expiries are tried from closest to 30 days outward, inside the 15-day gap.
    """
    if not venues:
        return None
    expiries = _expiries(pairs, ts_ms)
    ordered = sorted(expiries.items(), key=lambda item: abs(item[1] - CONDOR_TARGET_DTE))
    for exp_ms, listed_dte in ordered:
        if abs(listed_dte - CONDOR_TARGET_DTE) > CONDOR_MAX_DTE_GAP:
            continue
        here = [
            pair
            for pair in pairs
            if pair.has_hub
            and pair.key.expiry_utc_ms == exp_ms
            and _quoted_on_all(pair, venues)
        ]
        calls = _pick_body_and_wing(
            [pair for pair in here if pair.key.is_call],
            wing_is_further=lambda strike, short: strike > short,
        )
        puts = _pick_body_and_wing(
            [pair for pair in here if not pair.key.is_call],
            wing_is_further=lambda strike, short: strike < short,
        )
        if calls is None or puts is None:
            continue
        short_call, long_call = calls
        short_put, long_put = puts
        return {
            "expiry_utc_ms": exp_ms,
            "listed_dte": listed_dte,
            "legs": {
                "short_call": _Leg(short_call),
                "long_call": _Leg(long_call),
                "short_put": _Leg(short_put),
                "long_put": _Leg(long_put),
            },
        }
    return None


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
    # Ignore scorecard placeholders that have no books (Binance is always listed).
    quoted_venues = [venue for venue in venues if any(pair.books.get(venue) for pair in pairs)]
    picked = pick_condor_legs(pairs, venues=quoted_venues, ts_ms=ts_ms)
    if picked is None:
        return empty
    index_px = _index_px(pairs)
    if index_px is None:
        return empty

    per_venue: dict[str, dict[str, float] | None] = {}
    for v in venues:
        per_venue[v] = _venue_round_trip(picked["legs"], v, index_usd=index_px)
    strikes = {name: leg.pair.key.strike for name, leg in picked["legs"].items()}
    return {
        "spec": spec,
        "listed_dte": picked["listed_dte"],
        "expiry_utc_ms": picked["expiry_utc_ms"],
        "index_px": index_px,
        "strikes": strikes,
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
