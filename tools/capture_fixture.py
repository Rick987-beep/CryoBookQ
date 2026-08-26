#!/usr/bin/env python3
"""Capture redacted sample fixtures (ATM + wing + empty) for offline tests.

Uses live spikes when available under tmp/, or runs a short dual burst.
Writes JSON under tests/fixtures/ (no secrets).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.config import get_settings
from cryobookq.types import BookL5
from cryobookq.venues.coincall import CoincallVenue
from cryobookq.venues.deribit import DeribitVenue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("capture_fixture")


def _pick_samples(books: dict[str, BookL5], index_hint: float | None) -> dict[str, dict]:
    """Pick ATM (nearest strike), a wing (far strike), and an empty book if any."""
    items = list(books.values())
    if not items:
        return {}

    def strike_of(b: BookL5) -> float:
        if b.key is not None:
            return b.key.strike
        # parse from symbol trailing -STRIKE-C
        parts = b.venue_symbol.rsplit("-", 2)
        try:
            return float(parts[-2])
        except (IndexError, ValueError):
            return 0.0

    mid = index_hint
    if mid is None:
        strikes = sorted(strike_of(b) for b in items)
        mid = strikes[len(strikes) // 2] if strikes else 0.0

    two_sided = [b for b in items if b.two_sided]
    empty = [b for b in items if b.is_empty]
    pool = two_sided or items
    atm = min(pool, key=lambda b: abs(strike_of(b) - mid))
    wing = max(pool, key=lambda b: abs(strike_of(b) - mid))
    out = {
        "atm": atm.to_dict(),
        "wing": wing.to_dict(),
    }
    if empty:
        out["empty"] = empty[0].to_dict()
    else:
        # Synthetic empty for regression if market has no empty wings right now
        out["empty"] = BookL5.empty(
            venue=atm.venue,
            venue_symbol=f"{atm.venue_symbol}-EMPTY-SAMPLE",
            key=atm.key,
        ).to_dict()
        out["empty"]["synthetic"] = True
    return out


async def _live_capture(duration: float) -> tuple[dict[str, BookL5], dict[str, BookL5], float | None]:
    settings = get_settings()
    deribit = DeribitVenue()
    coincall = CoincallVenue(settings)
    d_syms = [i.venue_symbol for i in deribit.list_instruments(settings.underlying)]
    c_syms = [i.venue_symbol for i in coincall.list_instruments(settings.underlying)]
    # Index from Deribit REST
    import requests

    idx = None
    try:
        r = requests.get(
            "https://www.deribit.com/api/v2/public/get_index_price",
            params={"index_name": "btc_usd"},
            timeout=10,
        )
        idx = float(r.json()["result"]["index_price"])
    except Exception:  # noqa: BLE001
        pass

    (d_books, _), (c_books, _) = await asyncio.gather(
        deribit.burst_books(d_syms, duration_s=duration),
        coincall.burst_books(c_syms, duration_s=duration),
    )
    return d_books, c_books, idx


def _from_tmp(path: Path) -> dict[str, BookL5]:
    from cryobookq.types import OptionKey

    raw = json.loads(path.read_text())
    books: dict[str, BookL5] = {}
    for sym, d in (raw.get("books") or {}).items():
        key = None
        if d.get("key"):
            k = d["key"]
            key = OptionKey(k["underlying"], k["expiry_utc_ms"], k["strike"], k["is_call"])
        books[sym] = BookL5(
            venue=d["venue"],
            venue_symbol=d["venue_symbol"],
            key=key,
            ts_exchange_ms=d.get("ts_exchange_ms"),
            bid_px=list(d["bid_px"]),
            bid_sz=list(d["bid_sz"]),
            ask_px=list(d["ask_px"]),
            ask_sz=list(d["ask_sz"]),
            index_px=d.get("index_px"),
            mark_px=d.get("mark_px"),
            delta=d.get("delta"),
        )
    return books


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--from-tmp", action="store_true", help="Use tmp/*_spike.json if present")
    parser.add_argument("--outdir", type=Path, default=Path("tests/fixtures"))
    args = parser.parse_args()

    d_path = Path("tmp/deribit_spike.json")
    c_path = Path("tmp/coincall_spike.json")
    idx = None
    if args.from_tmp and d_path.is_file() and c_path.is_file():
        d_books = _from_tmp(d_path)
        c_books = _from_tmp(c_path)
        logger.info("Loaded from tmp dumps")
    else:
        d_books, c_books, idx = await _live_capture(args.duration)

    args.outdir.mkdir(parents=True, exist_ok=True)
    deribit_fx = _pick_samples(d_books, idx)
    coincall_fx = _pick_samples(c_books, idx)
    payload = {
        "meta": {
            "index_hint": idx,
            "n_deribit": len(d_books),
            "n_coincall": len(c_books),
            "note": "Sample books for unit tests; not full chain.",
        },
        "deribit": deribit_fx,
        "coincall": coincall_fx,
    }
    out = args.outdir / "sample_books.json"
    out.write_text(json.dumps(payload, indent=2))
    logger.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
