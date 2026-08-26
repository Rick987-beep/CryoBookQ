"""Canonical types for CryoBookQ snapshots and matching."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class OptionKey:
    """Exact match key across venues: (underlying, expiry_utc_ms, strike, is_call)."""

    underlying: str
    expiry_utc_ms: int
    strike: float
    is_call: bool

    def as_tuple(self) -> tuple[str, int, float, bool]:
        return (self.underlying, self.expiry_utc_ms, self.strike, self.is_call)


@dataclass(slots=True)
class Instrument:
    """One listed option contract on a venue."""

    venue: str
    venue_symbol: str
    key: OptionKey
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class BookL5:
    """Top-5 bid/ask book for one instrument at a capture instant.

    Prices and sizes are venue-native until normalize (M3). Empty levels are 0.0.
    """

    venue: str
    venue_symbol: str
    key: OptionKey | None
    ts_exchange_ms: int | None
    bid_px: list[float]  # len 5
    bid_sz: list[float]
    ask_px: list[float]
    ask_sz: list[float]
    index_px: float | None = None
    mark_px: float | None = None
    delta: float | None = None

    def __post_init__(self) -> None:
        for name in ("bid_px", "bid_sz", "ask_px", "ask_sz"):
            levels = getattr(self, name)
            if len(levels) != 5:
                raise ValueError(f"{name} must have length 5, got {len(levels)}")

    @property
    def is_empty(self) -> bool:
        return all(p == 0.0 for p in self.bid_px) and all(p == 0.0 for p in self.ask_px)

    @property
    def two_sided(self) -> bool:
        return self.bid_px[0] > 0.0 and self.ask_px[0] > 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.key is not None:
            d["key"] = asdict(self.key)
        return d

    @classmethod
    def empty(
        cls,
        venue: str,
        venue_symbol: str,
        key: OptionKey | None = None,
        ts_exchange_ms: int | None = None,
    ) -> BookL5:
        z = [0.0] * 5
        return cls(
            venue=venue,
            venue_symbol=venue_symbol,
            key=key,
            ts_exchange_ms=ts_exchange_ms,
            bid_px=list(z),
            bid_sz=list(z),
            ask_px=list(z),
            ask_sz=list(z),
        )


def pad_levels(
    levels: list[tuple[float, float]] | list[list[float]],
    depth: int = 5,
) -> tuple[list[float], list[float]]:
    """Pad/truncate [(px, sz), ...] to fixed depth; missing levels are 0."""
    px: list[float] = []
    sz: list[float] = []
    for i in range(depth):
        if i < len(levels):
            row = levels[i]
            px.append(float(row[0]))
            sz.append(float(row[1]))
        else:
            px.append(0.0)
            sz.append(0.0)
    return px, sz
