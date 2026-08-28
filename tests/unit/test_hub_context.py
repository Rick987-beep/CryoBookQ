"""Hub context and rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from cryobookq.hub.app import create_app
from cryobookq.hub.context import build_hub_context
from cryobookq.pipeline.write import ParquetStore


def test_hub_renders_multi_venue_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ParquetStore(tmp_path)
    ts = 1_710_000_000_000
    rows = []
    for venue in ("deribit", "coincall", "bybit"):
        rows.append(
            {
                "ts": ts,
                "venue": venue,
                "underlying": "BTC",
                "expiry_utc_ms": ts + 7 * 86400_000,
                "strike": 80_000.0,
                "is_call": True,
                "venue_symbol": f"{venue}-C",
                "delta": 0.5,
                "bid_px_1": 100.0,
                "ask_px_1": 102.0,
                "bid_sz_1": 2.0,
                "ask_sz_1": 2.0,
                **{f"bid_px_{i}": 0.0 for i in range(2, 6)},
                **{f"ask_px_{i}": 0.0 for i in range(2, 6)},
                **{f"bid_sz_{i}": 0.0 for i in range(2, 6)},
                **{f"ask_sz_{i}": 0.0 for i in range(2, 6)},
            }
        )
    store.write_raw_books(rows, ts, append=False)

    fake_health = {
        "status": "ok",
        "last_ts_ms": ts,
        "last_ok": True,
        "snapshots_today": 1,
        "writes_today": 1,
        "gaps_today": 0,
        "incomplete_today": 0,
        "uptime_s": 120.0,
        "disk_free_mb": 50_000,
        "clock": {"offset_s": 0.03},
        "last_stats": {
            "deribit": {
                "coverage": 1.0,
                "n_instruments": 100,
                "duration_s": 30.0,
                "notes": [],
            },
            "binance": {
                "coverage": 1.0,
                "n_instruments": 658,
                "duration_s": 79.0,
                "notes": ["ticker_fill=103", "rest_429=0"],
            },
            "quality": {"ok": True, "coverages": {"deribit": 1.0, "binance": 1.0}},
        },
    }
    monkeypatch.setattr(
        "cryobookq.hub.context.fetch_daemon_health",
        lambda **_: fake_health,
    )

    app = create_app(tmp_path)
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    body = r.data
    assert b"System health" in body
    assert b"Exchange scores" in body
    assert b"Deribit" in body
    assert b"Binance" in body
    assert b"ticker_fill" in body

    ctx = build_hub_context(tmp_path, health=fake_health)
    assert len(ctx["venue_rows"]) >= 5
    assert ctx["status"] == "ok"


def test_hub_health_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cryobookq.hub.context.fetch_daemon_health",
        lambda **_: {"status": "degraded", "snapshots_today": 0},
    )
    app = create_app(tmp_path)
    h = app.test_client().get("/health")
    assert h.status_code == 200
    data = h.get_json()
    assert data["status"] == "degraded"
    assert "hub_data_dir" in data
