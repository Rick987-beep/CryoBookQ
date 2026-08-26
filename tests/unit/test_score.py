"""Unit: scoring, walk costs, buckets, winners."""

from cryobookq.pipeline.match import MatchedPair
from cryobookq.pipeline.score import (
    COMPOSITE_WEIGHTS,
    dte_bucket,
    score_pair,
    session_for_ts,
    venue_metrics,
    walk_cost,
)
from cryobookq.types import OptionKey


def _usd_row(bid: float, ask: float, bid_sz: float = 2.0, ask_sz: float = 2.0) -> dict:
    return {
        "venue_symbol": "S",
        "bid_px_1": bid,
        "bid_px_2": 0,
        "bid_px_3": 0,
        "bid_px_4": 0,
        "bid_px_5": 0,
        "bid_sz_1": bid_sz,
        "bid_sz_2": 0,
        "bid_sz_3": 0,
        "bid_sz_4": 0,
        "bid_sz_5": 0,
        "ask_px_1": ask,
        "ask_px_2": 0,
        "ask_px_3": 0,
        "ask_px_4": 0,
        "ask_px_5": 0,
        "ask_sz_1": ask_sz,
        "ask_sz_2": 0,
        "ask_sz_3": 0,
        "ask_sz_4": 0,
        "ask_sz_5": 0,
        "delta": 0.25,
    }


def test_walk_cost_insufficient() -> None:
    assert walk_cost([(100.0, 0.5)], qty=1.0) is None


def test_walk_cost_vwap() -> None:
    # 0.5 @ 100 + 0.5 @ 110 = 105
    assert walk_cost([(100.0, 0.5), (110.0, 1.0)], qty=1.0) == 105.0


def test_empty_wing_null_costs() -> None:
    empty = {
        "venue_symbol": "WING",
        **{f"bid_px_{i}": 0 for i in range(1, 6)},
        **{f"bid_sz_{i}": 0 for i in range(1, 6)},
        **{f"ask_px_{i}": 0 for i in range(1, 6)},
        **{f"ask_sz_{i}": 0 for i in range(1, 6)},
    }
    m = venue_metrics(empty)
    assert not m["two_sided"]
    assert m["cost_buy_1btc"] is None
    assert m["spread_usd"] is None


def test_tighter_spread_wins() -> None:
    key = OptionKey("BTC", 1_800_000_000_000, 80000.0, True)
    pair = MatchedPair(
        key=key,
        deribit=_usd_row(100, 110),  # spread 10
        coincall=_usd_row(100, 105),  # spread 5 → coincall wins
    )
    # ts far before expiry
    row = score_pair(pair, ts_ms=1_700_000_000_000)
    assert row["winner_spread"] == "coincall"
    assert row["match_status"] == "matched"
    assert abs(COMPOSITE_WEIGHTS["spread"] + COMPOSITE_WEIGHTS["cost_buy"] + COMPOSITE_WEIGHTS["cost_sell"] + COMPOSITE_WEIGHTS["depth"] - 1.0) < 1e-9


def test_session_and_dte_buckets() -> None:
    from datetime import UTC, datetime

    us = datetime(2026, 3, 15, 16, 0, tzinfo=UTC)
    ts_ms = int(us.timestamp() * 1000)
    assert session_for_ts(ts_ms) == "US"
    assert dte_bucket(1.2) == "0-2"
    assert dte_bucket(5) == "3-7"
    assert dte_bucket(100) == "90+"
