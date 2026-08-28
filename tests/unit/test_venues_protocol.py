"""Unit tests: Venue Protocol structural compliance + book parsers."""

import json
from pathlib import Path

from cryobookq.types import BookL5
from cryobookq.venues.binance import BinanceVenue, _parse_binance_sides
from cryobookq.venues.bybit import BybitVenue, _parse_bybit_sides
from cryobookq.venues.coincall import CoincallVenue, _extract_symbol, _parse_coincall_book
from cryobookq.venues.deribit import DeribitVenue, _channel, _parse_book_sides, _ws_channel_depth
from cryobookq.venues.okx import OkxVenue, _parse_okx_sides
from cryobookq.venues.protocol import Venue


def test_venues_satisfy_protocol() -> None:
    assert isinstance(DeribitVenue(), Venue)
    assert isinstance(CoincallVenue(), Venue)
    assert isinstance(BybitVenue(), Venue)
    assert isinstance(OkxVenue(), Venue)
    assert isinstance(BinanceVenue(), Venue)


def test_deribit_ws_depth_mapping() -> None:
    assert _ws_channel_depth(5) == 10
    assert _ws_channel_depth(1) == 1
    assert _ws_channel_depth(10) == 10
    assert _ws_channel_depth(15) == 20
    assert _channel("BTC-1JAN30-1-C", 5) == "book.BTC-1JAN30-1-C.none.10.100ms"


def test_deribit_snapshot_parse() -> None:
    data = {
        "timestamp": 1,
        "bids": [[0.01, 1.0], [0.009, 2.0]],
        "asks": [[0.011, 1.5]],
    }
    bid_px, bid_sz, ask_px, ask_sz = _parse_book_sides(data, 5)
    assert bid_px[0] == 0.01
    assert bid_sz[1] == 2.0
    assert ask_px[0] == 0.011
    assert ask_px[1] == 0.0


def test_coincall_abbrev_parse() -> None:
    data = {
        "s": "BTCUSD-03APR26-74000-C",
        "bids": [{"pr": "100.5", "sz": "0.2"}, {"pr": "99", "sz": "1"}],
        "asks": [{"pr": "101", "sz": "0.3"}],
        "ts": 123,
    }
    bid_px, bid_sz, ask_px, ask_sz = _parse_coincall_book(data, 5)
    assert bid_px[0] == 100.5
    assert bid_sz[0] == 0.2
    assert ask_px[0] == 101.0
    assert ask_sz[4] == 0.0


def test_coincall_symbol_name_field() -> None:
    assert _extract_symbol({"symbolName": "BTCUSD-03APR26-74000-C"}) == "BTCUSD-03APR26-74000-C"


def test_bybit_okx_binance_side_parse() -> None:
    b, a = _parse_bybit_sides({"b": [["1720", "2.64"]], "a": [["1730", "5.7"]]})
    assert b[0] == (1720.0, 2.64)
    assert a[0][0] == 1730.0
    ob, oa = _parse_okx_sides({"bids": [["0.0215", "482", "0", "2"]], "asks": [["0.022", "10"]]})
    assert ob[0][1] == 482.0
    bb, ba = _parse_binance_sides({"b": [["1720", "5.88"]], "a": [["1725", "4.22"]]})
    assert bb[0][0] == 1720.0
    assert len(ba) == 1


def test_fixture_sample_loads_if_present() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures" / "sample_books.json"
    assert path.is_file(), "run tools/capture_fixture.py after a dual spike"
    raw = json.loads(path.read_text())
    atm = raw["deribit"]["atm"]
    book = BookL5(
        venue=atm["venue"],
        venue_symbol=atm["venue_symbol"],
        key=None,
        ts_exchange_ms=atm.get("ts_exchange_ms"),
        bid_px=list(atm["bid_px"]),
        bid_sz=list(atm["bid_sz"]),
        ask_px=list(atm["ask_px"]),
        ask_sz=list(atm["ask_sz"]),
    )
    assert len(book.bid_px) == 5
    assert "empty" in raw["deribit"]
    assert "atm" in raw["coincall"]
