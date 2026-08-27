"""Instrument list cache with TTL and stale-on-failure.

Re-fetching ~1000 options every snapshot is fine at 15-min cadence, but a
transient REST blip must not fail the whole capture if we still have a
recent list. Tickrecorder refreshes on a 30-min loop; we mirror that TTL.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from cryobookq.types import Instrument
from cryobookq.venues.coincall import CoincallVenue
from cryobookq.venues.deribit import DeribitVenue

logger = logging.getLogger(__name__)

DEFAULT_TTL_S = 30 * 60  # 30 minutes


@dataclass
class _CacheEntry:
    instruments: list[Instrument]
    fetched_mono: float
    stale: bool = False


@dataclass
class InstrumentCache:
    """Per-venue instrument lists with TTL and last-known-good fallback."""

    ttl_s: float = DEFAULT_TTL_S
    _entries: dict[str, _CacheEntry] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def get(
        self,
        venue: str,
        underlying: str,
        *,
        coincall: CoincallVenue | None = None,
        force: bool = False,
    ) -> tuple[list[Instrument], dict]:
        """Return ``(instruments, meta)``.

        *meta* includes ``from_cache``, ``stale``, ``age_s``, ``n``.
        On fetch failure, returns the previous list marked ``stale=True``
        when available; otherwise re-raises.
        """
        key = f"{venue}:{underlying}"
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if (
                not force
                and entry is not None
                and (now - entry.fetched_mono) < self.ttl_s
                and not entry.stale
            ):
                age = now - entry.fetched_mono
                return list(entry.instruments), {
                    "from_cache": True,
                    "stale": False,
                    "age_s": round(age, 1),
                    "n": len(entry.instruments),
                }

        try:
            instruments = self._fetch(venue, underlying, coincall=coincall)
        except Exception as exc:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None and entry.instruments:
                    entry.stale = True
                    age = time.monotonic() - entry.fetched_mono
                    logger.warning(
                        "Instrument fetch %s failed (%s); using stale list n=%d age=%.0fs",
                        key,
                        exc,
                        len(entry.instruments),
                        age,
                    )
                    return list(entry.instruments), {
                        "from_cache": True,
                        "stale": True,
                        "age_s": round(age, 1),
                        "n": len(entry.instruments),
                        "fetch_error": str(exc),
                    }
            raise

        with self._lock:
            self._entries[key] = _CacheEntry(
                instruments=list(instruments),
                fetched_mono=time.monotonic(),
                stale=False,
            )
        logger.info("Instrument cache refreshed %s n=%d", key, len(instruments))
        return list(instruments), {
            "from_cache": False,
            "stale": False,
            "age_s": 0.0,
            "n": len(instruments),
        }

    def _fetch(
        self,
        venue: str,
        underlying: str,
        *,
        coincall: CoincallVenue | None,
    ) -> list[Instrument]:
        if venue == "deribit":
            return DeribitVenue().list_instruments(underlying)
        if venue == "coincall":
            v = coincall or CoincallVenue()
            return v.list_instruments(underlying)
        raise ValueError(f"unknown venue {venue!r}")

    def invalidate(self, venue: str | None = None) -> None:
        with self._lock:
            if venue is None:
                self._entries.clear()
            else:
                drop = [k for k in self._entries if k.startswith(f"{venue}:")]
                for k in drop:
                    del self._entries[k]


# Shared cache for daemon / soak processes.
INSTRUMENTS = InstrumentCache()
