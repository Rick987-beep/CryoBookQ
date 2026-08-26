"""Symbol parse / convert between Deribit and Coincall option names.

Deribit:  BTC-3APR26-74000-C   (day unpadded)
Coincall: BTCUSD-03APR26-74000-C (day zero-padded)

Copied/adapted from CryoTrader exchanges/deribit/symbols.py — do not import CryoTrader.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from cryobookq.types import OptionKey

_EXPIRY_HOUR_UTC = 8

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_MONTH_NUM_TO_NAME = {v: k for k, v in _MONTHS.items()}

_DERIBIT_RE = re.compile(r"^([A-Z]+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+(?:\.\d+)?)-([CP])$")
_COINCALL_RE = re.compile(r"^([A-Z]+)USD-(\d{2})([A-Z]{3})(\d{2})-(\d+(?:\.\d+)?)-([CP])$")


def parse_deribit_symbol(symbol: str) -> dict[str, str] | None:
    m = _DERIBIT_RE.match(symbol)
    if not m:
        return None
    return {
        "underlying": m.group(1),
        "day": m.group(2),
        "month": m.group(3),
        "year": m.group(4),
        "strike": m.group(5),
        "option_type": m.group(6),
    }


def parse_coincall_symbol(symbol: str) -> dict[str, str] | None:
    m = _COINCALL_RE.match(symbol)
    if not m:
        return None
    return {
        "underlying": m.group(1),
        "day": m.group(2),
        "month": m.group(3),
        "year": m.group(4),
        "strike": m.group(5),
        "option_type": m.group(6),
    }


def coincall_to_deribit(symbol: str) -> str | None:
    m = _COINCALL_RE.match(symbol)
    if not m:
        return None
    day = str(int(m.group(2)))
    return f"{m.group(1)}-{day}{m.group(3)}{m.group(4)}-{m.group(5)}-{m.group(6)}"


def deribit_to_coincall(symbol: str) -> str | None:
    parts = parse_deribit_symbol(symbol)
    if not parts:
        return None
    day = parts["day"].zfill(2)
    return (
        f"{parts['underlying']}USD-{day}{parts['month']}{parts['year']}"
        f"-{parts['strike']}-{parts['option_type']}"
    )


def option_expiry_utc(symbol: str) -> datetime | None:
    """Expiry datetime (08:00 UTC) for Deribit or Coincall option symbol."""
    m = _COINCALL_RE.match(symbol) or _DERIBIT_RE.match(symbol)
    if not m:
        return None
    day = int(m.group(2))
    month = _MONTHS.get(m.group(3).upper())
    year = 2000 + int(m.group(4))
    if not month:
        return None
    return datetime(year, month, day, _EXPIRY_HOUR_UTC, 0, 0, tzinfo=UTC)


def option_key_from_symbol(symbol: str, underlying: str | None = None) -> OptionKey | None:
    """Build OptionKey from either venue's symbol string."""
    parts = parse_coincall_symbol(symbol) or parse_deribit_symbol(symbol)
    if not parts:
        return None
    exp = option_expiry_utc(symbol)
    if exp is None:
        return None
    und = underlying or parts["underlying"]
    return OptionKey(
        underlying=und,
        expiry_utc_ms=int(exp.timestamp() * 1000),
        strike=float(parts["strike"]),
        is_call=parts["option_type"] == "C",
    )


def expiry_token(expiry_utc_ms: int) -> str:
    """Format expiry ms as e.g. 28MAR26 (Deribit-style, unpadded day)."""
    dt = datetime.fromtimestamp(expiry_utc_ms / 1000, tz=UTC)
    mon = _MONTH_NUM_TO_NAME[dt.month]
    return f"{dt.day}{mon}{dt.strftime('%y')}"
