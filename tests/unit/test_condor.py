"""Iron-condor round-trip cost (The flight of the condor)."""

from __future__ import annotations

from cryobookq.analytics.condor import (
    CONDOR_LONG_ABS_DELTA,
    CONDOR_SHORT_ABS_DELTA,
    CONDOR_TARGET_DTE,
    aggregate_condor,
    iron_condor_snapshot,
)
from cryobookq.analytics.scorecard import ScorecardResult, aggregate_scorecards, build_scorecard
from cryobookq.fees import taker_fee_usd
from cryobookq.pipeline.match import MatchedPair
from cryobookq.types import OptionKey


def _row(
    *,
    venue: str,
    key: OptionKey,
    delta: float,
    bid: float,
    ask: float,
    index_px: float = 100_000.0,
) -> dict:
    row = {
        "venue": venue,
        "venue_symbol": f"{venue}-{key.strike}-{'C' if key.is_call else 'P'}",
        "underlying": key.underlying,
        "expiry_utc_ms": key.expiry_utc_ms,
        "strike": key.strike,
        "is_call": key.is_call,
        "delta": delta,
        "index_px": index_px,
        "bid_px_1": bid,
        "bid_sz_1": 2.0,
        "ask_px_1": ask,
        "ask_sz_1": 2.0,
    }
    for i in range(2, 6):
        row[f"bid_px_{i}"] = 0.0
        row[f"bid_sz_{i}"] = 0.0
        row[f"ask_px_{i}"] = 0.0
        row[f"ask_sz_{i}"] = 0.0
    return row


def _condor_pairs(
    *,
    ts: int,
    coincall_one_sided: bool = False,
    index_px: float = 100_000.0,
) -> list:
    exp = ts + int(CONDOR_TARGET_DTE * 86400_000)
    # Distinct strikes so inner/outer legs cannot collapse onto one contract.
    specs = [
        (True, CONDOR_SHORT_ABS_DELTA, 82_000.0, 400.0, 420.0),
        (False, -CONDOR_SHORT_ABS_DELTA, 82_000.0, 400.0, 420.0),
        (True, CONDOR_LONG_ABS_DELTA, 88_000.0, 200.0, 220.0),
        (False, -CONDOR_LONG_ABS_DELTA, 76_000.0, 200.0, 220.0),
    ]
    pairs = []
    for is_call, delta, strike, bid, ask in specs:
        key = OptionKey("BTC", exp, strike + (1 if is_call else 0), is_call)
        cc_ask = bid if coincall_one_sided else ask
        cc_bid = bid
        pairs.append(
            MatchedPair(
                key=key,
                books={
                    "deribit": _row(
                        venue="deribit", key=key, delta=delta, bid=bid, ask=ask, index_px=index_px
                    ),
                    "coincall": _row(
                        venue="coincall",
                        key=key,
                        delta=delta,
                        bid=cc_bid,
                        ask=cc_ask if not coincall_one_sided else 0.0,
                        index_px=index_px,
                    ),
                },
            )
        )
    return pairs


def test_condor_rt_matches_hand_math() -> None:
    ts = 1_700_000_000_000
    pairs = _condor_pairs(ts=ts)
    out = iron_condor_snapshot(pairs, ["deribit", "coincall"], ts_ms=ts)
    d = out["per_venue"]["deribit"]
    assert d is not None
    index_px = 100_000.0
    # Short mids 410, long mids 210 → net credit $400.
    assert abs(d["mid_credit_usd"] - 400.0) < 1e-9
    # Four full TOB widths of $20 = $80.
    assert abs(d["spread_usd"] - 80.0) < 1e-9
    fee40 = taker_fee_usd("deribit", index_usd=index_px, premium_usd=410.0)
    fee25 = taker_fee_usd("deribit", index_usd=index_px, premium_usd=210.0)
    fee_usd = 2 * 2 * fee40 + 2 * 2 * fee25  # 2 sides × 2 fills × 2 tenors
    assert abs(d["fee_usd"] - fee_usd) < 1e-9
    rt = 80.0 + fee_usd
    assert abs(d["rt_usd"] - rt) < 1e-9
    assert abs(d["rt_pct_of_mid"] - rt / 400.0 * 100.0) < 1e-9
    assert abs(d["leftover_pct_of_mid"] - (400.0 - rt) / 400.0 * 100.0) < 1e-9


def test_one_sided_wing_drops_the_structure() -> None:
    """A leg nobody shares is not used. With no alternate, the strip is empty."""
    ts = 1_700_000_000_000
    pairs = _condor_pairs(ts=ts, coincall_one_sided=True)
    out = iron_condor_snapshot(pairs, ["deribit", "coincall"], ts_ms=ts)
    assert out["listed_dte"] is None
    assert out["per_venue"]["deribit"] is None
    assert out["per_venue"]["coincall"] is None


def test_skips_strike_missing_on_one_venue() -> None:
    """Prefer a shared strike over the Deribit-only strike nearest the target delta."""
    ts = 1_700_000_000_000
    exp = ts + int(CONDOR_TARGET_DTE * 86400_000)

    def add(pairs, *, strike, is_call, delta, venues):
        key = OptionKey("BTC", exp, strike, is_call)
        books = {
            venue: _row(venue=venue, key=key, delta=delta, bid=400.0 if abs(delta) > 0.3 else 200.0, ask=420.0 if abs(delta) > 0.3 else 220.0)
            for venue in venues
        }
        pairs.append(MatchedPair(key=key, books=books))

    pairs: list = []
    # Deribit-only 40Δ call. Shared call is a bit further off.
    add(pairs, strike=89_000.0, is_call=True, delta=0.40, venues=("deribit",))
    add(pairs, strike=90_000.0, is_call=True, delta=0.36, venues=("deribit", "bybit"))
    add(pairs, strike=94_000.0, is_call=True, delta=0.25, venues=("deribit", "bybit"))
    add(pairs, strike=84_000.0, is_call=False, delta=-0.40, venues=("deribit", "bybit"))
    add(pairs, strike=80_000.0, is_call=False, delta=-0.26, venues=("deribit", "bybit"))
    out = iron_condor_snapshot(pairs, ["deribit", "bybit"], ts_ms=ts)
    assert out["per_venue"]["deribit"] is not None
    assert out["per_venue"]["bybit"] is not None
    assert out["strikes"]["short_call"] == 90_000.0
    assert out["strikes"]["long_call"] == 94_000.0
    assert out["strikes"]["short_put"] == 84_000.0
    assert out["strikes"]["long_put"] == 80_000.0


def test_missing_30dte_yields_empty() -> None:
    ts = 1_700_000_000_000
    exp = ts + int(7 * 86400_000)
    key = OptionKey("BTC", exp, 80_000.0, True)
    pairs = [
        MatchedPair(
            key=key,
            books={
                "deribit": _row(venue="deribit", key=key, delta=0.4, bid=100, ask=110),
            },
        )
    ]
    out = iron_condor_snapshot(pairs, ["deribit"], ts_ms=ts)
    assert out["listed_dte"] is None
    assert out["per_venue"]["deribit"] is None


def test_nearest_listed_near_30d_is_accepted() -> None:
    """BTC monthlies often sit ~22 DTE; max gap 15 must still pick them."""
    ts = 1_700_000_000_000
    exp = ts + int(22 * 86400_000)
    specs = [
        (True, CONDOR_SHORT_ABS_DELTA, 82_000.0, 400.0, 420.0),
        (False, -CONDOR_SHORT_ABS_DELTA, 82_000.0, 400.0, 420.0),
        (True, CONDOR_LONG_ABS_DELTA, 88_000.0, 200.0, 220.0),
        (False, -CONDOR_LONG_ABS_DELTA, 76_000.0, 200.0, 220.0),
    ]
    pairs = []
    for is_call, delta, strike, bid, ask in specs:
        key = OptionKey("BTC", exp, strike + (1 if is_call else 0), is_call)
        pairs.append(
            MatchedPair(
                key=key,
                books={"deribit": _row(venue="deribit", key=key, delta=delta, bid=bid, ask=ask)},
            )
        )
    out = iron_condor_snapshot(pairs, ["deribit"], ts_ms=ts)
    assert out["listed_dte"] is not None
    assert abs(out["listed_dte"] - 22.0) < 0.01
    assert out["per_venue"]["deribit"] is not None


def test_scorecard_and_aggregate_keep_condor() -> None:
    ts = 1_700_000_000_000
    pairs = _condor_pairs(ts=ts)
    card = build_scorecard(pairs, ts_ms=ts)
    assert card.condor["per_venue"]["deribit"] is not None
    agg = aggregate_scorecards([card, card])
    assert agg.condor["per_venue"]["deribit"]["leftover_pct_of_mid"] == (
        card.condor["per_venue"]["deribit"]["leftover_pct_of_mid"]
    )
    # Dummy card without condor still aggregates.
    empty = ScorecardResult(ts_ms=ts + 1, venues=["deribit"], condor={})
    mixed = aggregate_condor([card, empty])
    assert mixed["per_venue"]["deribit"]["n_snaps"] == 1.0
