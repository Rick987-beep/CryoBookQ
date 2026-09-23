"""Unit: Bullish L2 frames, market-list filter, and registry. No network."""

from cryobookq.venues.registry import make_venue
from cryobookq.venues.bullish import (
    BullishLocalBook,
    apply_l2_message,
    exchange_ts_ms,
    flat_levels,
    instruments_from_rows,
    subscribe_error,
)


def _snap(symbol: str, bids: list[str], asks: list[str], *, pub: str = "1790166000000", eng: str = "1000") -> dict:
    return {
        "type": "snapshot",
        "dataType": "V1TALevel2",
        "data": {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "sequenceNumberRange": [1, 1],
            "timestamp": eng,
            "publishedAtTimestamp": pub,
        },
    }


def test_make_venue_bullish() -> None:
    venue = make_venue("bullish")
    assert venue.name == "bullish"


def test_flat_levels_pairs_strings() -> None:
    assert flat_levels(["280.0000", "0.76900000", "270.0000", "4.95000000"]) == [
        (280.0, 0.769),
        (270.0, 4.95),
    ]


def test_publish_time_beats_stale_engine_timestamp() -> None:
    data = {"timestamp": "1000", "publishedAtTimestamp": "1790166000000"}
    assert exchange_ts_ms(data) == 1790166000000


def test_empty_snapshot_clears_a_previous_book() -> None:
    local: dict[str, BullishLocalBook] = {}
    sym = "BTC-USDC-20260924-86000-C"
    apply_l2_message(
        local,
        _snap(sym, ["280.0000", "1.0", "270.0000", "2.0"], ["330.0000", "3.0"]),
    )
    assert local[sym].levels(5)[0][0] == (280.0, 1.0)
    apply_l2_message(local, _snap(sym, [], []))
    bids, asks = local[sym].levels(5)
    assert bids == []
    assert asks == []


def test_update_deletes_only_zero_size_and_keeps_the_rest() -> None:
    local: dict[str, BullishLocalBook] = {}
    sym = "BTC-USDC-20260924-86000-C"
    apply_l2_message(
        local,
        _snap(sym, ["280.0000", "1.0", "270.0000", "2.0"], ["330.0000", "3.0"]),
    )
    apply_l2_message(
        local,
        {
            "type": "update",
            "data": {
                "symbol": sym,
                "bids": ["280.0000", "0", "260.0000", "4.0"],
                "asks": [],
                "publishedAtTimestamp": "1790166001000",
            },
        },
    )
    bids, asks = local[sym].levels(5)
    assert bids == [(270.0, 2.0), (260.0, 4.0)]
    assert asks == [(330.0, 3.0)]


def test_update_before_snapshot_is_ignored() -> None:
    local: dict[str, BullishLocalBook] = {}
    sym = "BTC-USDC-20260924-86000-C"
    assert apply_l2_message(
        local,
        {
            "type": "update",
            "data": {"symbol": sym, "bids": ["280.0000", "1.0"], "asks": ["330.0000", "1.0"]},
        },
    ) == (None, None)
    assert local == {}


def test_subscribe_nack_is_an_error_and_ack_is_not() -> None:
    nack = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {
            "code": "-32602",
            "errorCode": "29013",
            "errorCodeName": "'NOPE-OPTION' is not a valid symbol",
        },
    }
    assert subscribe_error(nack) == "'NOPE-OPTION' is not a valid symbol"
    ack = {"result": {"responseCode": "200", "message": "Successfully subscribed"}}
    assert subscribe_error(ack) is None
    assert apply_l2_message({}, ack) == (None, None)


def test_market_rows_keep_btc_options_only() -> None:
    rows = [
        {
            "symbol": "BTC-USDC-20260924-85600-C",
            "marketType": "OPTION",
            "marketEnabled": True,
            "underlyingBaseSymbol": "BTC",
            "optionType": "CALL",
        },
        {
            "symbol": "BTC-USDC-20270625-32704-P",
            "marketType": "OPTION",
            "marketEnabled": True,
            "underlyingBaseSymbol": "BTC",
        },
        {
            "symbol": "BTC-USDC-20260924",
            "marketType": "DATED_FUTURE",
            "marketEnabled": True,
            "underlyingBaseSymbol": "BTC",
        },
        {
            "symbol": "ETH-USDC-20260924-4000-C",
            "marketType": "OPTION",
            "marketEnabled": True,
            "underlyingBaseSymbol": "ETH",
        },
        {
            "symbol": "BTC-USDC-20260924-85000-C",
            "marketType": "OPTION",
            "marketEnabled": False,
            "underlyingBaseSymbol": "BTC",
        },
    ]
    inst = instruments_from_rows(rows, "BTC")
    assert [i.venue_symbol for i in inst] == [
        "BTC-USDC-20260924-85600-C",
        "BTC-USDC-20270625-32704-P",
    ]
    assert inst[1].key is not None and inst[1].key.strike == 32704.0
    assert instruments_from_rows(rows, "ETH")[0].venue_symbol == "ETH-USDC-20260924-4000-C"
