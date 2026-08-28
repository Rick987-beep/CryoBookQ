"""Unit: normalize Deribit BTC→USD and size_to_btc."""

import pytest

from cryobookq.pipeline.normalize import normalize_book
from cryobookq.types import BookL5, OptionKey
from cryobookq.venues.spec import VenueSpec


def _book(
    venue: str,
    bid: float,
    ask: float,
    bid_sz: float = 1.0,
    *,
    size_to_btc: float | None = None,
) -> BookL5:
    key = OptionKey("BTC", 1_800_000_000_000, 80000.0, True)
    return BookL5(
        venue=venue,
        venue_symbol="X",
        key=key,
        ts_exchange_ms=1,
        bid_px=[bid, 0, 0, 0, 0],
        bid_sz=[bid_sz, 0, 0, 0, 0],
        ask_px=[ask, 0, 0, 0, 0],
        ask_sz=[1.0, 0, 0, 0, 0],
        size_to_btc=size_to_btc,
    )


def test_deribit_btc_to_usd() -> None:
    row = normalize_book(_book("deribit", 0.01, 0.012), index_px=100_000.0)
    assert row["price_unit"] == "USD"
    assert row["bid_px_1"] == 1000.0
    assert row["ask_px_1"] == 1200.0
    assert row["bid_sz_1"] == 1.0
    assert row["size_to_btc"] == 1.0
    assert row["bid_px_1"] * row["bid_sz_1"] == 1000.0


def test_coincall_already_usd() -> None:
    row = normalize_book(_book("coincall", 1000.0, 1200.0), index_px=100_000.0)
    assert row["bid_px_1"] == 1000.0
    assert row["ask_px_1"] == 1200.0


def test_bybit_usdt_unchanged() -> None:
    row = normalize_book(_book("bybit", 1720.0, 1730.0), index_px=80_000.0)
    assert row["bid_px_1"] == 1720.0
    assert row["size_to_btc"] == 1.0


def test_okx_contract_multiplier() -> None:
    spec = VenueSpec("okx", "BTC", 0.01)
    row = normalize_book(
        _book("okx", 0.0215, 0.022, bid_sz=482.0),
        index_px=80_000.0,
        spec=spec,
    )
    assert row["bid_px_1"] == pytest.approx(0.0215 * 80_000.0)
    assert row["bid_sz_1"] == pytest.approx(4.82)


def test_okx_size_to_btc_on_book() -> None:
    row = normalize_book(
        _book("okx", 0.02, 0.021, bid_sz=100.0, size_to_btc=0.01),
        index_px=100_000.0,
    )
    assert row["bid_sz_1"] == pytest.approx(1.0)
    assert row["bid_px_1"] == pytest.approx(2000.0)
