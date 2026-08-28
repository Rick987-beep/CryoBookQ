"""Normalize venue-native books to USD prices + BTC sizes.

The only unit-conversion site. Adapters must emit native px/sz.
"""

from __future__ import annotations

from cryobookq.types import BookL5
from cryobookq.venues.spec import VenueSpec, spec_for


def normalize_book(
    book: BookL5,
    *,
    index_px: float,
    capture_lag_ms: float | None = None,
    spec: VenueSpec | None = None,
) -> dict:
    """Return a raw_books row dict with USD prices and BTC sizes."""
    if index_px <= 0:
        raise ValueError(f"index_px must be > 0, got {index_px}")

    try:
        spec = spec or spec_for(book.venue)
    except KeyError:
        spec = VenueSpec(book.venue, "USD", 1.0)

    size_to_btc = book.size_to_btc if book.size_to_btc and book.size_to_btc > 0 else spec.size_to_btc
    btc_premium = spec.price_ccy == "BTC"

    def _px(p: float) -> float:
        if not p:
            return 0.0
        return p * index_px if btc_premium else p

    bid_px = [_px(p) for p in book.bid_px]
    ask_px = [_px(p) for p in book.ask_px]
    mark = book.mark_px
    if mark is not None and btc_premium:
        mark = mark * index_px

    bid_sz = [s * size_to_btc if s else 0.0 for s in book.bid_sz]
    ask_sz = [s * size_to_btc if s else 0.0 for s in book.ask_sz]

    key = book.key
    row = {
        "venue": book.venue,
        "venue_symbol": book.venue_symbol,
        "underlying": key.underlying if key else None,
        "expiry_utc_ms": key.expiry_utc_ms if key else None,
        "strike": key.strike if key else None,
        "is_call": key.is_call if key else None,
        "index_px": index_px,
        "mark_px": mark,
        "delta": book.delta,
        "capture_lag_ms": capture_lag_ms,
        "price_unit": "USD",
        "size_to_btc": size_to_btc,
    }
    for i in range(5):
        row[f"bid_px_{i + 1}"] = bid_px[i]
        row[f"bid_sz_{i + 1}"] = bid_sz[i]
        row[f"ask_px_{i + 1}"] = ask_px[i]
        row[f"ask_sz_{i + 1}"] = ask_sz[i]
    return row


def books_to_raw_rows(
    books: dict[str, BookL5],
    *,
    ts_ms: int,
    index_px: float,
    capture_lag_ms: float | None = None,
) -> list[dict]:
    rows = []
    for book in books.values():
        row = normalize_book(book, index_px=index_px, capture_lag_ms=capture_lag_ms)
        row["ts"] = ts_ms
        rows.append(row)
    return rows
