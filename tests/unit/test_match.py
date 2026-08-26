"""Unit: exact matcher."""

from cryobookq.pipeline.match import match_raw_rows
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
        _row("deribit", 90000),  # unmatched
    ]
    pairs = match_raw_rows(rows)
    by_strike = {p.key.strike: p for p in pairs}
    assert by_strike[80000].match_status == "matched"
    assert by_strike[90000].match_status == "unmatched"
    assert by_strike[90000].coincall is None


def test_option_key_identity() -> None:
    pairs = match_raw_rows([_row("deribit", 1.0), _row("coincall", 1.0)])
    assert pairs[0].key == OptionKey("BTC", 1_800_000_000_000, 1.0, True)
