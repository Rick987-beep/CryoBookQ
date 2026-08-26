"""Venue Protocol — list instruments + burst L5 books."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from cryobookq.types import BookL5, Instrument


@runtime_checkable
class Venue(Protocol):
    """Exchange adapter for orderbook quality capture."""

    name: str

    def list_instruments(self, underlying: str) -> list[Instrument]:
        """Active option instruments for *underlying* (e.g. BTC)."""
        ...

    async def burst_books(
        self,
        symbols: list[str],
        depth: int,
        deadline: datetime,
    ) -> dict[str, BookL5]:
        """Subscribe until *deadline*, return last L5 book per venue symbol.

        Implementations must unsubscribe (or drop the connection) after the
        deadline. Missing symbols may be omitted or returned as empty books.
        """
        ...
