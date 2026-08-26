"""Unit tests: symbol parse / convert Deribit ↔ Coincall."""

from datetime import UTC, datetime

from cryobookq.symbols import (
    coincall_to_deribit,
    deribit_to_coincall,
    option_expiry_utc,
    option_key_from_symbol,
    parse_coincall_symbol,
    parse_deribit_symbol,
)
from cryobookq.types import OptionKey


def test_parse_deribit_unpadded_day() -> None:
    p = parse_deribit_symbol("BTC-3APR26-74000-C")
    assert p is not None
    assert p["day"] == "3"
    assert p["option_type"] == "C"


def test_parse_coincall_padded_day() -> None:
    p = parse_coincall_symbol("BTCUSD-03APR26-74000-C")
    assert p is not None
    assert p["day"] == "03"
    assert p["underlying"] == "BTC"


def test_roundtrip_deribit_coincall() -> None:
    d = "BTC-3APR26-74000-C"
    c = deribit_to_coincall(d)
    assert c == "BTCUSD-03APR26-74000-C"
    assert coincall_to_deribit(c) == d


def test_roundtrip_padded_deribit_day() -> None:
    d = "BTC-28MAR26-100000-P"
    c = deribit_to_coincall(d)
    assert c == "BTCUSD-28MAR26-100000-P"
    assert coincall_to_deribit(c) == d


def test_option_expiry_utc_shared() -> None:
    d_exp = option_expiry_utc("BTC-3APR26-74000-C")
    c_exp = option_expiry_utc("BTCUSD-03APR26-74000-C")
    assert d_exp == c_exp
    assert d_exp == datetime(2026, 4, 3, 8, 0, 0, tzinfo=UTC)


def test_option_key_equality_across_venues() -> None:
    k1 = option_key_from_symbol("BTC-3APR26-74000-C")
    k2 = option_key_from_symbol("BTCUSD-03APR26-74000-C")
    assert k1 is not None and k2 is not None
    assert k1 == k2
    assert k1 == OptionKey("BTC", k1.expiry_utc_ms, 74000.0, True)


def test_bad_symbol_returns_none() -> None:
    assert parse_deribit_symbol("BTC-PERPETUAL") is None
    assert coincall_to_deribit("nope") is None
    assert option_key_from_symbol("ETH-USD") is None
