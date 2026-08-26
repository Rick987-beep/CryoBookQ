"""Unit tests: BookL5 / OptionKey round-trip."""

from cryobookq.types import BookL5, OptionKey, pad_levels


def test_option_key_hashable() -> None:
    k = OptionKey("BTC", 1_700_000_000_000, 80000.0, True)
    assert k in {k}
    assert k.as_tuple()[2] == 80000.0


def test_empty_book_roundtrip() -> None:
    key = OptionKey("BTC", 1_700_000_000_000, 50000.0, False)
    b = BookL5.empty("deribit", "BTC-1JAN30-50000-P", key=key, ts_exchange_ms=123)
    assert b.is_empty
    assert not b.two_sided
    d = b.to_dict()
    assert d["bid_px"] == [0.0] * 5
    assert d["ask_sz"] == [0.0] * 5
    assert d["key"]["strike"] == 50000.0


def test_pad_levels_truncate_and_pad() -> None:
    px, sz = pad_levels([(1.0, 2.0), (0.9, 3.0)], depth=5)
    assert px == [1.0, 0.9, 0.0, 0.0, 0.0]
    assert sz == [2.0, 3.0, 0.0, 0.0, 0.0]
    px2, _ = pad_levels([(i, 1.0) for i in range(10)], depth=5)
    assert len(px2) == 5


def test_two_sided_book() -> None:
    b = BookL5(
        venue="coincall",
        venue_symbol="BTCUSD-03APR26-74000-C",
        key=None,
        ts_exchange_ms=1,
        bid_px=[100.0, 99.0, 0, 0, 0],
        bid_sz=[0.5, 0.5, 0, 0, 0],
        ask_px=[101.0, 102.0, 0, 0, 0],
        ask_sz=[0.4, 0.4, 0, 0, 0],
    )
    assert b.two_sided
    assert not b.is_empty


def test_book_requires_depth_5() -> None:
    try:
        BookL5(
            venue="x",
            venue_symbol="y",
            key=None,
            ts_exchange_ms=None,
            bid_px=[1.0],
            bid_sz=[1.0],
            ask_px=[1.0],
            ask_sz=[1.0],
        )
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
