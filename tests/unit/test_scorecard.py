"""Unit tests for landmark scorecard + BS delta."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from cryobookq.analytics.scorecard import (
    aggregate_scorecards,
    build_scorecard,
    build_scorecard_period,
    filter_raw_books,
    hour_in_utc_window,
    lift_notional,
    nearest_expiry,
    relative_spread_pct,
    score_lower_better,
)
from cryobookq.pipeline.greeks import bs_delta
from cryobookq.pipeline.match import MatchedPair
from cryobookq.types import OptionKey


def _book_row(
    *,
    venue: str,
    key: OptionKey,
    delta: float,
    bid: float,
    ask: float,
    bid_sz: float = 2.0,
    ask_sz: float = 2.0,
    deeper: bool = False,
) -> dict:
    row = {
        "venue": venue,
        "venue_symbol": f"{venue}-{key.strike}-{'C' if key.is_call else 'P'}",
        "underlying": key.underlying,
        "expiry_utc_ms": key.expiry_utc_ms,
        "strike": key.strike,
        "is_call": key.is_call,
        "delta": delta,
        "bid_px_1": bid,
        "bid_sz_1": bid_sz,
        "ask_px_1": ask,
        "ask_sz_1": ask_sz,
    }
    for i in range(2, 6):
        if deeper:
            row[f"bid_px_{i}"] = bid - (i - 1)
            row[f"bid_sz_{i}"] = bid_sz
            row[f"ask_px_{i}"] = ask + (i - 1)
            row[f"ask_sz_{i}"] = ask_sz
        else:
            row[f"bid_px_{i}"] = 0.0
            row[f"bid_sz_{i}"] = 0.0
            row[f"ask_px_{i}"] = 0.0
            row[f"ask_sz_{i}"] = 0.0
    return row


def test_bs_delta_atm_call_near_half() -> None:
    d = bs_delta(100.0, 100.0, 30 / 365.25, 50.0, is_call=True)
    assert d is not None
    assert 0.45 < d < 0.55


def test_bs_delta_put_negative() -> None:
    d = bs_delta(100.0, 100.0, 30 / 365.25, 50.0, is_call=False)
    assert d is not None
    assert -0.55 < d < -0.45


def test_relative_spread_pct() -> None:
    key = OptionKey("BTC", 1_700_000_000_000, 80_000.0, True)
    row = _book_row(venue="deribit", key=key, delta=0.5, bid=100.0, ask=110.0)
    assert abs(relative_spread_pct(row) - (10 / 105 * 100)) < 1e-6


def test_lift_notional_fillable() -> None:
    key = OptionKey("BTC", 1_700_000_000_000, 80_000.0, True)
    # mid=105; need $10k → ~95.2 BTC at ask 110 — use deep book
    row = _book_row(
        venue="deribit",
        key=key,
        delta=0.5,
        bid=100.0,
        ask=110.0,
        bid_sz=50.0,
        ask_sz=50.0,
        deeper=True,
    )
    lift = lift_notional(row, notional_usd=10_000.0)
    assert lift["fillable"] is True
    assert lift["vwap"] is not None
    assert lift["effective_pct"] is not None
    assert lift["effective_pct"] > 0


def test_lift_insufficient_is_not_fillable() -> None:
    key = OptionKey("BTC", 1_700_000_000_000, 80_000.0, True)
    row = _book_row(venue="deribit", key=key, delta=0.5, bid=100.0, ask=110.0, ask_sz=0.1)
    assert lift_notional(row, notional_usd=10_000.0)["fillable"] is False


def test_score_lower_better() -> None:
    assert score_lower_better(0.0, 10.0) == 10.0
    assert score_lower_better(10.0, 10.0) == 0.0
    assert score_lower_better(None, 10.0) == 0.0


def test_nearest_expiry_respects_gap() -> None:
    expiries = {1: 2.0, 2: 14.0, 3: 90.0}
    assert nearest_expiry(expiries, 14.0, max_gap=4.0) == (2, 14.0)
    assert nearest_expiry({2: 14.0}, 7.0, max_gap=4.0) is None
    assert nearest_expiry(expiries, 2.0, max_gap=1.5) == (1, 2.0)


def _exp_ms(dte: float, ts_ms: int) -> int:
    return ts_ms + int(dte * 86400_000)


def test_build_scorecard_ranks_tighter_spread() -> None:
    ts = 1_700_000_000_000
    # Expiries near short/mid/far targets
    targets = [1.0, 2.0, 7.0, 14.0, 21.0, 60.0, 90.0, 120.0]
    pairs: list[MatchedPair] = []
    for dte in targets:
        exp = _exp_ms(dte, ts)
        for is_call, delta in [(True, 0.50), (False, -0.50), (True, 0.25), (False, -0.25),
                               (True, 0.075), (False, -0.075), (True, 0.025), (False, -0.025)]:
            strike = 80_000.0 + (0 if abs(delta) > 0.4 else 5_000)
            key = OptionKey("BTC", exp, strike + (100 if is_call else 0), is_call)
            # Deribit tighter spread, deeper book; Coincall wider / often thin
            d_row = _book_row(
                venue="deribit",
                key=key,
                delta=delta,
                bid=200.0,
                ask=204.0,
                bid_sz=30.0,
                ask_sz=30.0,
                deeper=True,
            )
            c_row = _book_row(
                venue="coincall",
                key=key,
                delta=delta,
                bid=190.0,
                ask=220.0,
                bid_sz=1.0,
                ask_sz=1.0,
                deeper=True,
            )
            pairs.append(MatchedPair(key=key, deribit=d_row, coincall=c_row))

    card = build_scorecard(pairs, ts_ms=ts)
    assert card.overall["deribit"] > card.overall["coincall"]
    assert card.presence["per_venue"]["deribit"]["two_sided_rate"] == 1.0
    # At least some grid cells populated
    assert any(c["n_targets_used"] > 0 for c in card.grid.values())


def test_cell_weights_favor_spread() -> None:
    """Tighter spread with thin depth should beat wide spread with huge depth."""
    from cryobookq.analytics.scorecard import CELL_WEIGHTS, contract_metrics

    assert abs(sum(CELL_WEIGHTS.values()) - 1.0) < 1e-9
    key = OptionKey("BTC", 1_700_000_000_000, 80_000.0, True)
    tight = _book_row(
        venue="deribit", key=key, delta=0.5, bid=100.0, ask=101.0, bid_sz=1.0, ask_sz=1.0
    )
    # Deep but wide
    wide = _book_row(
        venue="coincall",
        key=key,
        delta=0.5,
        bid=90.0,
        ask=120.0,
        bid_sz=50.0,
        ask_sz=50.0,
        deeper=True,
    )
    # Patch sizes on tight so $10k still fails → size score 0; spread still strong
    t = contract_metrics(tight, delta_label="50d")
    w = contract_metrics(wide, delta_label="50d")
    assert t["score_spread"] > w["score_spread"]
    assert t["score"] > w["score"]


def test_hour_window_and_filter() -> None:
    assert hour_in_utc_window(12, 12, 18)
    assert not hour_in_utc_window(18, 12, 18)
    assert hour_in_utc_window(23, 22, 6)
    assert hour_in_utc_window(3, 22, 6)
    assert not hour_in_utc_window(12, 22, 6)

    ts_a = int(datetime(2026, 8, 27, 15, 0, tzinfo=UTC).timestamp() * 1000)
    ts_b = int(datetime(2026, 8, 27, 10, 0, tzinfo=UTC).timestamp() * 1000)
    df = pd.DataFrame({"ts": [ts_a, ts_a, ts_b, ts_b], "x": [1, 2, 3, 4]})
    f = filter_raw_books(df, utc_hour_start=12, utc_hour_end=18)
    assert set(f["ts"].unique()) == {ts_a}


def test_aggregate_scorecards_means_overall() -> None:
    ts = 1_700_000_000_000
    targets = [1.0, 2.0, 7.0, 14.0, 21.0, 60.0, 90.0, 120.0]
    pairs: list[MatchedPair] = []
    for dte in targets:
        exp = _exp_ms(dte, ts)
        for is_call, delta in [(True, 0.50), (False, -0.50)]:
            key = OptionKey("BTC", exp, 80_000.0 + (1 if is_call else 0), is_call)
            d_row = _book_row(
                venue="deribit",
                key=key,
                delta=delta,
                bid=200.0,
                ask=204.0,
                bid_sz=30.0,
                ask_sz=30.0,
                deeper=True,
            )
            c_row = _book_row(
                venue="coincall",
                key=key,
                delta=delta,
                bid=190.0,
                ask=220.0,
                bid_sz=5.0,
                ask_sz=5.0,
                deeper=True,
            )
            pairs.append(MatchedPair(key=key, deribit=d_row, coincall=c_row))

    c1 = build_scorecard(pairs, ts_ms=ts)
    c2 = build_scorecard(pairs, ts_ms=ts + 15_000)
    agg = aggregate_scorecards([c1, c2])
    assert agg.meta["n_snapshots"] == 2
    assert abs(agg.overall["deribit"] - c1.overall["deribit"]) < 1e-9
    assert agg.meta.get("aggregated") is True


def test_build_scorecard_period_from_raw_df() -> None:
    ts0 = int(datetime(2026, 8, 27, 13, 0, tzinfo=UTC).timestamp() * 1000)
    rows = []
    for snap in range(3):
        ts = ts0 + snap * 15_000
        for dte in (1.0, 14.0, 90.0):
            exp = ts + int(dte * 86400_000)
            for is_call, delta in [(True, 0.5), (False, -0.5), (True, 0.25), (False, -0.25)]:
                key = OptionKey("BTC", exp, 80_000.0 + (10 if is_call else 0) + dte, is_call)
                for venue, bid, ask, sz in (
                    ("deribit", 100.0, 104.0, 40.0),
                    ("coincall", 98.0, 110.0, 5.0),
                ):
                    r = _book_row(
                        venue=venue,
                        key=key,
                        delta=delta,
                        bid=bid,
                        ask=ask,
                        bid_sz=sz,
                        ask_sz=sz,
                        deeper=True,
                    )
                    r["ts"] = ts
                    rows.append(r)
    df = pd.DataFrame(rows)
    card = build_scorecard_period(df)
    assert card.meta["n_snapshots"] == 3
    card2 = build_scorecard_period(df, utc_hour_start=12, utc_hour_end=18)
    assert card2.meta["n_snapshots"] == 3
    try:
        build_scorecard_period(df, utc_hour_start=0, utc_hour_end=6)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
