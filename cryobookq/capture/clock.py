"""Exchange clock sync (Deribit ``public/get_time``).

Wall-clock NTP drift on the apps host can skew 15-minute boundary opens.
We keep ``exchange_unix = time.time() + offset`` where *offset* is measured
from Deribit REST ``get_time``, same idea as CryoTrader tickrecorder.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

logger = logging.getLogger(__name__)

DERIBIT_TIME_URL = "https://www.deribit.com/api/v2/public/get_time"


def fetch_deribit_time_ms(*, timeout: float = 5.0) -> int:
    """Return Deribit server time in milliseconds (blocking REST)."""
    r = requests.get(DERIBIT_TIME_URL, timeout=timeout)
    r.raise_for_status()
    return int(r.json()["result"])


@dataclass
class ExchangeClock:
    """Thread-safe Deribit-aligned clock.

    ``offset_s`` is added to ``time.time()`` so positive means local is
    *behind* Deribit (local + offset ≈ Deribit).
    """

    offset_s: float = 0.0
    last_sync_mono: float | None = None
    last_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def now(self) -> datetime:
        with self._lock:
            return datetime.fromtimestamp(time.time() + self.offset_s, tz=UTC)

    def now_unix(self) -> float:
        with self._lock:
            return time.time() + self.offset_s

    def sync(self, *, quiet: bool = False) -> float:
        """Refresh offset from Deribit. Returns new offset_s. Blocking."""
        t0 = time.time()
        try:
            deribit_ms = fetch_deribit_time_ms()
            # Mid-RTT approximation: compare Deribit ms to local mid-request time.
            local_mid = (t0 + time.time()) / 2.0
            offset = (deribit_ms / 1000.0) - local_mid
            with self._lock:
                self.offset_s = offset
                self.last_sync_mono = time.monotonic()
                self.last_error = None
            direction = "behind Deribit" if offset > 0 else "ahead of Deribit"
            if not quiet:
                logger.info("Exchange clock sync: local is %.3fs %s", abs(offset), direction)
            elif abs(offset) > 1.0:
                logger.warning("Exchange clock offset large: %+.3fs", offset)
            return offset
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.last_error = str(exc)
            logger.warning("Exchange clock sync failed: %s (keeping offset %+.3fs)", exc, self.offset_s)
            raise

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "offset_s": round(self.offset_s, 4),
                "last_sync_age_s": (
                    None
                    if self.last_sync_mono is None
                    else round(time.monotonic() - self.last_sync_mono, 1)
                ),
                "last_error": self.last_error,
            }


# Process-wide clock used by the daemon scheduler.
CLOCK = ExchangeClock()
