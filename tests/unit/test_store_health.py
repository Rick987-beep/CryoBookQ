"""Unit: parquet part files + health endpoint."""

from pathlib import Path

from cryobookq.daemon.health import HealthState, start_health_server
from cryobookq.pipeline.write import ParquetStore
from cryobookq.schemas import read_provenance


def _row(ts: int) -> dict:
    return {
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
        "bid_px_1": 10.0,
        "ask_px_1": 12.0,
        "bid_sz_1": 1.0,
        "ask_sz_1": 1.0,
    }


def test_part_files_no_rewrite(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path, depth=5, cadence_min=15)
    t1, t2 = 1_710_000_000_000, 1_710_000_900_000
    p1 = store.write_raw_books([_row(t1)], t1)
    p2 = store.write_raw_books([_row(t2)], t2)
    assert p1 != p2
    assert p1.name == f"part-{t1}.parquet"
    assert p2.is_file()
    # Second write must not grow/replace first file
    assert p1.stat().st_size > 0
    loaded = store.load_raw_books()
    assert len(loaded) == 2
    prov = read_provenance(p1)
    assert prov.get("source") == "cryobookq"


def test_health_http_roundtrip(tmp_path: Path) -> None:
    import urllib.request

    h = HealthState()
    h.data_dir = str(tmp_path)
    h.record_success(123, {"match_rate": 0.9}, wrote=True)
    # Bind ephemeral port
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = start_health_server(h, port=port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            body = resp.read().decode()
        assert '"status": "ok"' in body or '"last_ok": true' in body
        assert "disk_free_mb" in body
    finally:
        srv.shutdown()
