"""Parquet column schemas and provenance helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from cryobookq import __version__

SOURCE = "cryobookq"

RAW_BOOK_COLUMNS = [
    "ts",
    "venue",
    "venue_symbol",
    "underlying",
    "expiry_utc_ms",
    "strike",
    "is_call",
    "index_px",
    "mark_px",
    "delta",
    "capture_lag_ms",
    "price_unit",  # "USD" after normalize; "BTC" or "USD" for raw venue-native
    "bid_px_1",
    "bid_px_2",
    "bid_px_3",
    "bid_px_4",
    "bid_px_5",
    "bid_sz_1",
    "bid_sz_2",
    "bid_sz_3",
    "bid_sz_4",
    "bid_sz_5",
    "ask_px_1",
    "ask_px_2",
    "ask_px_3",
    "ask_px_4",
    "ask_px_5",
    "ask_sz_1",
    "ask_sz_2",
    "ask_sz_3",
    "ask_sz_4",
    "ask_sz_5",
]

PAIR_SCORE_COLUMNS = [
    "ts",
    "underlying",
    "expiry_utc_ms",
    "strike",
    "is_call",
    "match_status",
    "dte",
    "session",
    "weekday",
    "abs_delta",
    "dte_bucket",
    "delta_bucket",
    # Deribit metrics
    "deribit_two_sided",
    "deribit_spread_usd",
    "deribit_spread_bps",
    "deribit_mid_usd",
    "deribit_bid_sz_1",
    "deribit_ask_sz_1",
    "deribit_depth_btc_L5",
    "deribit_cost_buy_1btc",
    "deribit_cost_sell_1btc",
    "deribit_venue_symbol",
    # Coincall metrics
    "coincall_two_sided",
    "coincall_spread_usd",
    "coincall_spread_bps",
    "coincall_mid_usd",
    "coincall_bid_sz_1",
    "coincall_ask_sz_1",
    "coincall_depth_btc_L5",
    "coincall_cost_buy_1btc",
    "coincall_cost_sell_1btc",
    "coincall_venue_symbol",
    # Relative / winners
    "rel_mid_bps",
    "winner_spread",
    "winner_cost_buy",
    "winner_cost_sell",
    "winner_depth",
    "composite_deribit",
    "composite_coincall",
    "winner_composite",
]


def provenance_metadata(*, depth: int, cadence_min: int, extra: dict[str, str] | None = None) -> dict[bytes, bytes]:
    meta = {
        b"source": SOURCE.encode(),
        b"collector_version": __version__.encode(),
        b"depth": str(depth).encode(),
        b"cadence_min": str(cadence_min).encode(),
    }
    if extra:
        for k, v in extra.items():
            meta[k.encode()] = str(v).encode()
    return meta


def read_provenance(path: str | Path) -> dict[str, str]:
    try:
        raw = pq.read_metadata(str(path)).metadata or {}
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = k.decode() if isinstance(k, bytes) else str(k)
        val = v.decode() if isinstance(v, bytes) else str(v)
        out[key] = val
    return out


def atomic_write_parquet(
    df: pd.DataFrame,
    path: Path,
    *,
    depth: int,
    cadence_min: int,
    extra: dict[str, str] | None = None,
) -> None:
    """Write zstd parquet via temp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    table = pa.Table.from_pandas(df, preserve_index=False)
    existing = table.schema.metadata or {}
    table = table.replace_schema_metadata({**existing, **provenance_metadata(depth=depth, cadence_min=cadence_min, extra=extra)})
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)
