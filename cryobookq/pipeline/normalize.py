"""Normalize venue-native books to USD prices + BTC sizes."""

from __future__ import annotations

from cryobookq.types import BookL5


def normalize_book(book: BookL5, *, index_px: float, capture_lag_ms: float | None = None) -> dict:
    """Return a raw_books row dict with USD prices and BTC sizes.

    Deribit option prices are in BTC; multiply by index for USD.
    Coincall option prices are already USD.
    Sizes on both venues are treated as BTC notional (M3 sanity elsewhere).
    """
    if index_px <= 0:
        raise ValueError(f"index_px must be > 0, got {index_px}")

    if book.venue == "deribit":
        bid_px = [p * index_px if p else 0.0 for p in book.bid_px]
        ask_px = [p * index_px if p else 0.0 for p in book.ask_px]
        mark = (book.mark_px * index_px) if book.mark_px is not None else None
    else:
        bid_px = list(book.bid_px)
        ask_px = list(book.ask_px)
        mark = book.mark_px

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
    }
    for i in range(5):
        row[f"bid_px_{i + 1}"] = bid_px[i]
        row[f"bid_sz_{i + 1}"] = book.bid_sz[i]
        row[f"ask_px_{i + 1}"] = ask_px[i]
        row[f"ask_sz_{i + 1}"] = book.ask_sz[i]
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
