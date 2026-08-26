"""Unit: normalize Deribit BTC→USD."""

from cryobookq.pipeline.normalize import normalize_book
from cryobookq.types import BookL5, OptionKey


def _book(venue: str, bid: float, ask: float) -> BookL5:
    key = OptionKey("BTC", 1_800_000_000_000, 80000.0, True)
    return BookL5(
        venue=venue,
        venue_symbol="X",
        key=key,
        ts_exchange_ms=1,
        bid_px=[bid, 0, 0, 0, 0],
        bid_sz=[1.0, 0, 0, 0, 0],
        ask_px=[ask, 0, 0, 0, 0],
        ask_sz=[1.0, 0, 0, 0, 0],
    )


def test_deribit_btc_to_usd() -> None:
    row = normalize_book(_book("deribit", 0.01, 0.012), index_px=100_000.0)
    assert row["price_unit"] == "USD"
    assert row["bid_px_1"] == 1000.0
    assert row["ask_px_1"] == 1200.0
    assert row["bid_sz_1"] == 1.0


def test_coincall_already_usd() -> None:
    row = normalize_book(_book("coincall", 1000.0, 1200.0), index_px=100_000.0)
    assert row["bid_px_1"] == 1000.0
    assert row["ask_px_1"] == 1200.0
