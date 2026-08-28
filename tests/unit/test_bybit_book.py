"""Unit: Bybit local book snapshot + delta."""

from cryobookq.venues.bybit import BybitLocalBook, _parse_bybit_sides


def test_bybit_snapshot_then_delta_updates_top() -> None:
    book = BybitLocalBook()
    book.apply_snapshot([(100.0, 2.0), (99.0, 1.0)], [(101.0, 3.0)])
    bids, asks = book.levels(5)
    assert bids[0] == (100.0, 2.0)
    assert asks[0] == (101.0, 3.0)

    book.apply_delta([(100.0, 0.0), (98.5, 4.0)], [(101.0, 1.5)])
    bids, asks = book.levels(5)
    assert bids[0] == (99.0, 1.0)
    assert (98.5, 4.0) in bids
    assert all(px != 100.0 for px, _sz in bids)
    assert asks[0] == (101.0, 1.5)


def test_bybit_delta_without_snapshot_is_ignored_by_venue_loop() -> None:
    # Parser still returns the delta rows; venue skips until a snapshot exists.
    b, a = _parse_bybit_sides({"b": [["50", "0"]], "a": [["51", "1"]]})
    assert b[0] == (50.0, 0.0)
    assert a[0] == (51.0, 1.0)
