"""Black–Scholes delta helpers + Deribit summary enrichment.

Live WS books do not carry greeks. We approximate option delta from Deribit
``get_book_summary_by_currency`` (forward + mark IV) so landmark scorecards
can select 50δ / 25δ / 7.5δ / 2.5δ contracts. One REST call covers the chain.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime

import requests

from cryobookq.symbols import option_key_from_symbol
from cryobookq.types import OptionKey

logger = logging.getLogger(__name__)

DERIBIT_SUMMARY_URL = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_delta(
    forward: float,
    strike: float,
    t_years: float,
    iv_pct: float,
    *,
    is_call: bool,
) -> float | None:
    """Forward BS delta (Deribit-style). ``iv_pct`` is percent (e.g. 45.0)."""
    if forward <= 0 or strike <= 0:
        return None
    if t_years <= 1e-8:
        # At expiry: digital intrinsic
        if is_call:
            return 1.0 if forward > strike else 0.0
        return -1.0 if forward < strike else 0.0
    sigma = iv_pct / 100.0
    if sigma <= 1e-8:
        if is_call:
            return 1.0 if forward > strike else 0.0
        return -1.0 if forward < strike else 0.0
    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * t_years) / (sigma * math.sqrt(t_years))
    if is_call:
        return float(_norm_cdf(d1))
    return float(_norm_cdf(d1) - 1.0)


def fetch_deribit_deltas(
    underlying: str = "BTC",
    *,
    timeout: float = 30.0,
    now_ms: int | None = None,
) -> dict[OptionKey, float]:
    """Map OptionKey → signed delta using book summary mark_iv + underlying_price."""
    r = requests.get(
        DERIBIT_SUMMARY_URL,
        params={"currency": underlying, "kind": "option"},
        timeout=timeout,
    )
    r.raise_for_status()
    rows = r.json().get("result") or []
    now = now_ms if now_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000)
    out: dict[OptionKey, float] = {}
    for row in rows:
        name = row.get("instrument_name") or ""
        key = option_key_from_symbol(name, underlying=underlying)
        if key is None:
            continue
        fwd = float(row.get("underlying_price") or 0)
        iv = float(row.get("mark_iv") or 0)
        t_years = max(0.0, (key.expiry_utc_ms - now) / (1000.0 * 86400.0 * 365.25))
        delta = bs_delta(fwd, key.strike, t_years, iv, is_call=key.is_call)
        if delta is None:
            continue
        out[key] = delta
    logger.info("Deribit delta enrichment: %d instruments", len(out))
    return out
