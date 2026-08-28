"""Exact OptionKey matcher across venues.

``MatchedContract`` groups all venues by key. Deribit is the listing hub:
landmarks use ``has_hub``. Legacy ``match_status=="matched"`` still means
Deribit **and** Coincall (pair_scores winners only).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cryobookq.types import OptionKey


@dataclass(slots=True)
class MatchedContract:
    key: OptionKey
    books: dict[str, dict | None] = field(default_factory=dict)

    @property
    def deribit(self) -> dict | None:
        return self.books.get("deribit")

    @property
    def coincall(self) -> dict | None:
        return self.books.get("coincall")

    @property
    def has_hub(self) -> bool:
        return self.books.get("deribit") is not None

    @property
    def match_status(self) -> str:
        if self.has_hub and self.books.get("coincall") is not None:
            return "matched"
        if self.has_hub:
            return "hub"
        return "unmatched"


def MatchedPair(  # noqa: N802 — legacy constructor name
    *,
    key: OptionKey,
    deribit: dict | None = None,
    coincall: dict | None = None,
    books: dict[str, dict | None] | None = None,
) -> MatchedContract:
    """Backward-compatible constructor used by unit tests."""
    merged: dict[str, dict | None] = dict(books or {})
    if deribit is not None:
        merged["deribit"] = deribit
    if coincall is not None:
        merged["coincall"] = coincall
    return MatchedContract(key=key, books=merged)


def _key_from_row(row: dict) -> OptionKey | None:
    if row.get("expiry_utc_ms") is None or row.get("strike") is None or row.get("is_call") is None:
        return None
    und = row.get("underlying") or "BTC"
    return OptionKey(und, int(row["expiry_utc_ms"]), float(row["strike"]), bool(row["is_call"]))


def match_raw_rows(rows: list[dict]) -> list[MatchedContract]:
    """Group normalized raw_books rows by OptionKey (any venue name)."""
    by_key: dict[OptionKey, dict[str, dict]] = {}
    for row in rows:
        key = _key_from_row(row)
        if key is None:
            continue
        venue = row.get("venue")
        if not venue:
            continue
        by_key.setdefault(key, {})[str(venue)] = row

    return [MatchedContract(key=key, books=dict(venues)) for key, venues in by_key.items()]
