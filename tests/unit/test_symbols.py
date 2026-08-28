"""Unit tests: symbol parse / convert Deribit ↔ Coincall."""

from datetime import UTC, datetime

from cryobookq.symbols import (
    coincall_to_deribit,
    deribit_to_coincall,
    option_expiry_utc,
    option_key_from_symbol,
    parse_binance_symbol,
    parse_bybit_symbol,
    parse_coincall_symbol,
    parse_deribit_symbol,
    parse_okx_symbol,
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


def test_parse_bybit_binance_okx() -> None:
    b = parse_bybit_symbol("BTC-4SEP26-80000-C-USDT")
    assert b is not None and b["day"] == "4" and b["option_type"] == "C"
    n = parse_binance_symbol("BTC-260904-80000-C")
    assert n is not None and n["ymd"] == "260904"
    o = parse_okx_symbol("BTC-USD-260904-80000-C")
    assert o is not None and o["ymd"] == "260904"

    k1 = option_key_from_symbol("BTC-4SEP26-80000-C")
    k2 = option_key_from_symbol("BTC-4SEP26-80000-C-USDT")
    k3 = option_key_from_symbol("BTC-260904-80000-C")
    k4 = option_key_from_symbol("BTC-USD-260904-80000-C")
    assert k1 == k2 == k3 == k4
    assert k1 is not None
    assert option_expiry_utc("BTC-260904-80000-C") == datetime(2026, 9, 4, 8, 0, 0, tzinfo=UTC)
