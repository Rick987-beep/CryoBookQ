"""Unit tests for executive HTML scorecard report."""

from __future__ import annotations

from cryobookq.analytics.html_report import (
    build_executive_summary,
    render_scorecard_html,
    scorecard_from_dict,
)
from cryobookq.analytics.scorecard import build_scorecard
from cryobookq.pipeline.match import MatchedPair
from cryobookq.types import OptionKey


def _book_row(*, venue: str, key: OptionKey, delta: float, bid: float, ask: float, sz: float) -> dict:
    row = {
        "venue": venue,
        "venue_symbol": f"{venue}-{key.strike}",
        "underlying": key.underlying,
        "expiry_utc_ms": key.expiry_utc_ms,
        "strike": key.strike,
        "is_call": key.is_call,
        "delta": delta,
        "bid_px_1": bid,
        "bid_sz_1": sz,
        "ask_px_1": ask,
        "ask_sz_1": sz,
    }
    for i in range(2, 6):
        row[f"bid_px_{i}"] = bid - (i - 1)
        row[f"bid_sz_{i}"] = sz
        row[f"ask_px_{i}"] = ask + (i - 1)
        row[f"ask_sz_{i}"] = sz
    return row


def _mini_card():
    ts = 1_700_000_000_000
    pairs = []
    for dte in (1.0, 2.0, 7.0, 14.0, 21.0, 60.0, 90.0, 120.0):
        exp = ts + int(dte * 86400_000)
        for is_call, delta in [(True, 0.5), (False, -0.5), (True, 0.25), (False, -0.25)]:
            key = OptionKey("BTC", exp, 80_000.0 + (1 if is_call else 0), is_call)
            pairs.append(
                MatchedPair(
                    key=key,
                    deribit=_book_row(
                        venue="deribit", key=key, delta=delta, bid=200, ask=204, sz=40
                    ),
                    coincall=_book_row(
                        venue="coincall", key=key, delta=delta, bid=190, ask=220, sz=5
                    ),
                )
            )
    return build_scorecard(pairs, ts_ms=ts)


def test_html_contains_sections_and_venues() -> None:
    card = _mini_card()
    doc = render_scorecard_html(card)
    assert "Comparison Scorecard" in doc
    assert "Deribit" in doc and "Coincall" in doc
    assert "Overall index" in doc
    assert "Presence" in doc
    assert "Liquidity grid" in doc
    assert "Wings" in doc
    assert "Methodology" in doc
    assert "Executive Summary" in doc
    assert "Component summary" in doc
    assert "$10k" in doc or "$10" in doc


def test_executive_summary_mentions_leader() -> None:
    card = _mini_card()
    text = build_executive_summary(card)
    assert "Deribit" in text
    assert "/ 10" in text


def test_roundtrip_dict() -> None:
    card = _mini_card()
    again = scorecard_from_dict(card.to_dict())
    assert again.overall["deribit"] == card.overall["deribit"]
    assert "Deribit" in render_scorecard_html(again)
