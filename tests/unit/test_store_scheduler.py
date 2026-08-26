"""Unit: parquet write/load + scheduler."""

from datetime import UTC, datetime
from pathlib import Path

from cryobookq.capture.scheduler import next_boundary
from cryobookq.pipeline.write import ParquetStore
from cryobookq.schemas import read_provenance


def test_next_boundary_alignment() -> None:
    now = datetime(2026, 3, 15, 12, 7, 30, tzinfo=UTC)
    assert next_boundary(now, 15) == datetime(2026, 3, 15, 12, 15, 0, tzinfo=UTC)
    exact = datetime(2026, 3, 15, 12, 15, 0, tzinfo=UTC)
    assert next_boundary(exact, 15) == datetime(2026, 3, 15, 12, 30, 0, tzinfo=UTC)


def test_parquet_roundtrip(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path, depth=5, cadence_min=15)
    ts = 1_710_000_000_000
    rows = [
        {
            "ts": ts,
            "venue": "deribit",
            "venue_symbol": "BTC-1JAN30-1-C",
            "underlying": "BTC",
            "expiry_utc_ms": ts + 86400000,
            "strike": 1.0,
            "is_call": True,
            "index_px": 100000.0,
            "mark_px": None,
            "delta": 0.5,
            "capture_lag_ms": 100.0,
            "price_unit": "USD",
            **{f"bid_px_{i}": 0.0 for i in range(1, 6)},
            **{f"bid_sz_{i}": 0.0 for i in range(1, 6)},
            **{f"ask_px_{i}": 0.0 for i in range(1, 6)},
            **{f"ask_sz_{i}": 0.0 for i in range(1, 6)},
        }
    ]
    rows[0]["bid_px_1"] = 10.0
    rows[0]["ask_px_1"] = 12.0
    rows[0]["bid_sz_1"] = 1.0
    rows[0]["ask_sz_1"] = 1.0
    path = store.write_raw_books(rows, ts, append=False)
    assert path.is_file()
    prov = read_provenance(path)
    assert prov.get("source") == "cryobookq"
    assert prov.get("depth") == "5"
    loaded = store.load_raw_books()
    assert len(loaded) == 1
    assert loaded.iloc[0]["bid_px_1"] == 10.0
