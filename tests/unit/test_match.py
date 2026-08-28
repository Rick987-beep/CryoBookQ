"""Unit: exact matcher — hub vs N-way books."""

from cryobookq.pipeline.match import MatchedPair, match_raw_rows
from cryobookq.types import OptionKey


def _row(venue: str, strike: float, is_call: bool = True) -> dict:
    return {
        "venue": venue,
        "venue_symbol": f"{venue}-{strike}",
        "underlying": "BTC",
        "expiry_utc_ms": 1_800_000_000_000,
        "strike": strike,
        "is_call": is_call,
    }


def test_match_and_unmatched() -> None:
    rows = [
        _row("deribit", 80000),
        _row("coincall", 80000),
        _row("deribit", 90000),  # hub only
    ]
    pairs = match_raw_rows(rows)
    by_strike = {p.key.strike: p for p in pairs}
    assert by_strike[80000].match_status == "matched"
    assert by_strike[80000].has_hub
    assert by_strike[90000].has_hub
    assert by_strike[90000].match_status == "hub"
    assert by_strike[90000].coincall is None


def test_three_venues_same_key() -> None:
    rows = [_row("deribit", 80000), _row("coincall", 80000), _row("bybit", 80000)]
    pairs = match_raw_rows(rows)
    assert len(pairs) == 1
    p = pairs[0]
    assert set(p.books) == {"deribit", "coincall", "bybit"}
    assert p.has_hub


def test_bybit_only_is_not_hub() -> None:
    pairs = match_raw_rows([_row("bybit", 80000)])
    assert len(pairs) == 1
    assert not pairs[0].has_hub
    assert pairs[0].match_status == "unmatched"


def test_legacy_matched_pair_constructor() -> None:
    p = MatchedPair(key=OptionKey("BTC", 1, 1.0, True), deribit=_row("deribit", 1.0))
    assert p.has_hub
    assert p.deribit is not None


def test_option_key_identity() -> None:
    pairs = match_raw_rows([_row("deribit", 1.0), _row("coincall", 1.0)])
    assert pairs[0].key == OptionKey("BTC", 1_800_000_000_000, 1.0, True)
