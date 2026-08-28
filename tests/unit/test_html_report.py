"""Unit tests for executive HTML scorecard report."""

from __future__ import annotations

from cryobookq.analytics.report import copy as report_copy
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


def _mini_card(*, include_bybit: bool = True):
    ts = 1_700_000_000_000
    pairs = []
    for dte in (1.0, 2.0, 7.0, 14.0, 21.0, 60.0, 90.0, 120.0):
        exp = ts + int(dte * 86400_000)
        for is_call, delta in [(True, 0.5), (False, -0.5), (True, 0.25), (False, -0.25)]:
            key = OptionKey("BTC", exp, 80_000.0 + (1 if is_call else 0), is_call)
            extra = {}
            if include_bybit:
                extra = {
                    "bybit": _book_row(
                        venue="bybit", key=key, delta=delta, bid=198, ask=210, sz=8
                    )
                }
            pairs.append(
                MatchedPair(
                    key=key,
                    deribit=_book_row(
                        venue="deribit", key=key, delta=delta, bid=200, ask=204, sz=40
                    ),
                    coincall=_book_row(
                        venue="coincall", key=key, delta=delta, bid=190, ask=220, sz=5
                    ),
                    books=extra,
                )
            )
    return build_scorecard(pairs, ts_ms=ts)


def test_html_contains_sections_and_venues() -> None:
    report_copy.load_copy.cache_clear()
    card = _mini_card()
    doc = render_scorecard_html(card)
    assert "Comparison Scorecard" in doc
    assert "Deribit" in doc and "Coincall" in doc
    assert "Bybit" in doc
    assert 'data-venue="bybit"' in doc
    assert "Deribit-listed" in doc or "hub" in doc.lower()
    assert "on both venues" not in doc
    assert "matched pair" not in doc.lower()
    assert "1. Overall index" in doc
    assert "2. Component summary" in doc
    assert "3. Executive Summary" in doc
    assert "4. Presence" in doc
    assert "5. Liquidity grid" in doc
    assert "6. Wings" in doc
    assert "7. Catalogue" in doc
    assert "8. Capture quality" in doc
    assert "9. Methodology" in doc
    assert "\u2014" not in doc
    assert ">Total<" in doc
    assert "Catalogue" in doc
    assert "Instruments" in doc
    assert "Methodology" in doc
    assert "Executive Summary" in doc
    assert "Component summary" in doc
    assert "$10k" in doc or "$10" in doc


def test_executive_summary_mentions_leader() -> None:
    from cryobookq.analytics.report.labels import venue_name

    card = _mini_card()
    text = build_executive_summary(card)
    assert "Deribit" in text
    assert "/ 10" in text
    assert "\u2014" not in text
    assert "--" not in text
    for v in card.venues:
        assert venue_name(v) in text
    paras = [p for p in text.split("\n\n") if p.strip()]
    assert len(paras) >= 2 + len(card.venues)


def test_html_missing_venue_does_not_drop_deribit() -> None:
    with_peer = _mini_card(include_bybit=True)
    without = _mini_card(include_bybit=False)
    assert with_peer.overall["deribit"] == without.overall["deribit"]
    assert with_peer.overall["coincall"] == without.overall["coincall"]
    doc = render_scorecard_html(with_peer)
    assert "Bybit" in doc
    assert "Deribit" in render_scorecard_html(without)


def test_roundtrip_dict() -> None:
    card = _mini_card()
    again = scorecard_from_dict(card.to_dict())
    assert again.overall["deribit"] == card.overall["deribit"]
    assert again.catalogue["per_venue"]["deribit"]["n_instruments"] == (
        card.catalogue["per_venue"]["deribit"]["n_instruments"]
    )
    assert "Deribit" in render_scorecard_html(again)
    assert "Catalogue" in render_scorecard_html(again)
