"""Exact OptionKey matcher across venues."""

from __future__ import annotations

from dataclasses import dataclass

from cryobookq.types import OptionKey


@dataclass(slots=True)
class MatchedPair:
    key: OptionKey
    deribit: dict | None
    coincall: dict | None

    @property
    def match_status(self) -> str:
        if self.deribit is not None and self.coincall is not None:
            return "matched"
        return "unmatched"


def _key_from_row(row: dict) -> OptionKey | None:
    if row.get("expiry_utc_ms") is None or row.get("strike") is None or row.get("is_call") is None:
        return None
    und = row.get("underlying") or "BTC"
    return OptionKey(und, int(row["expiry_utc_ms"]), float(row["strike"]), bool(row["is_call"]))


def match_raw_rows(rows: list[dict]) -> list[MatchedPair]:
    """Group normalized raw_books rows by OptionKey into matched/unmatched pairs."""
    by_key: dict[OptionKey, dict[str, dict]] = {}
    for row in rows:
        key = _key_from_row(row)
        if key is None:
            continue
        slot = by_key.setdefault(key, {})
        venue = row.get("venue")
        if venue in ("deribit", "coincall"):
            slot[venue] = row

    pairs: list[MatchedPair] = []
    for key, venues in by_key.items():
        pairs.append(
            MatchedPair(
                key=key,
                deribit=venues.get("deribit"),
                coincall=venues.get("coincall"),
            )
        )
    return pairs
