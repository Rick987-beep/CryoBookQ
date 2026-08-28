"""Hub dashboard view model and rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from cryobookq.analytics.scorecard import build_scorecard
from cryobookq.hub.app import create_app
from cryobookq.hub.context import build_hub_context
from cryobookq.hub.view import build_dashboard_view, grid_row_tone, score_tone
from cryobookq.pipeline.match import MatchedPair
from cryobookq.pipeline.write import ParquetStore
from cryobookq.types import OptionKey


def _book_row(*, venue: str, key: OptionKey, delta: float, bid: float, ask: float, sz: float) -> dict:
    row = {
        "venue": venue,
        "venue_symbol": f"{venue}-{key.strike}",
        "underlying": key.underlying,
        "expiry_utc_ms": key.expiry_utc_ms,
        "strike": key.strike,
        "is_call": key.is_call,
        "delta": delta,
        "bid_px_1": bid,
        "bid_sz_1": sz,
        "ask_px_1": ask,
        "ask_sz_1": sz,
    }
    for i in range(2, 6):
        row[f"bid_px_{i}"] = bid - (i - 1)
        row[f"bid_sz_{i}"] = sz
        row[f"ask_px_{i}"] = ask + (i - 1)
        row[f"ask_sz_{i}"] = sz
    return row


def _rich_card():
    ts = 1_700_000_000_000
    pairs: list[MatchedPair] = []
    for dte in (1.0, 2.0, 7.0, 14.0, 21.0, 60.0, 90.0, 120.0):
        exp = ts + int(dte * 86400_000)
        for is_call, delta in [
            (True, 0.5),
            (False, -0.5),
            (True, 0.25),
            (False, -0.25),
            (True, 0.075),
            (False, -0.075),
            (True, 0.025),
            (False, -0.025),
        ]:
            key = OptionKey("BTC", exp, 80_000.0 + (1 if is_call else 0), is_call)
            pairs.append(
                MatchedPair(
                    key=key,
                    books={
                        "deribit": _book_row(venue="deribit", key=key, delta=delta, bid=198, ask=210, sz=8),
                        "coincall": _book_row(venue="coincall", key=key, delta=delta, bid=195, ask=215, sz=6),
                        "bybit": _book_row(venue="bybit", key=key, delta=delta, bid=199, ask=211, sz=7),
                        "okx": _book_row(venue="okx", key=key, delta=delta, bid=200, ask=212, sz=7),
                        "binance": _book_row(venue="binance", key=key, delta=delta, bid=201, ask=213, sz=7),
                    },
                )
            )
    return build_scorecard(pairs, ts_ms=ts)


def test_score_tone_helpers() -> None:
    assert score_tone(8.0) == "ok"
    assert score_tone(6.0) == "info"
    assert score_tone(4.0) == "warn"
    assert score_tone(1.0) == "bad"
    assert grid_row_tone(8.5) == "ok"


def test_dashboard_view_from_scorecard() -> None:
    card = _rich_card()
    ctx = build_dashboard_view(card, interval_min=15, n_snapshot_files=4)
    assert ctx["has_data"] is True
    assert len(ctx["ranked_venues"]) == 5
    assert len(ctx["grid_rows"]) == 9
    assert len(ctx["wing_rows"]) == 4
    assert ctx["leader"] is not None
    assert "Impressum" not in ctx["footer"]["impressum"]  # raw impressum text, not label
    assert ctx["copy"]["venues"].startswith("Weighted")


def test_hub_renders_public_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ParquetStore(tmp_path)
    ts = 1_710_000_000_000
    rows = []
    for venue in ("deribit", "coincall", "bybit", "okx", "binance"):
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

    fake_health = {"status": "ok", "last_ts_ms": ts}
    monkeypatch.setattr(
        "cryobookq.hub.context.fetch_daemon_health",
        lambda **_: fake_health,
    )

    app = create_app(tmp_path)
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    body = r.data
    assert b"System health" not in body
    assert b"Overall ranking" in body
    assert b"3\xc3\x973 liquidity grid" in body or b"liquidity grid" in body
    assert b"Impressum" in body
    assert b"Datenschutz" in body
    assert b"Deribit" in body
    assert b"Binance" in body

    ctx = build_hub_context(tmp_path, health=fake_health)
    assert ctx["has_data"] is True
    assert ctx["daemon_status"] == "ok"


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
    assert data["hub_data_dir"] == str(tmp_path)
    assert data["hub_snapshot_n"] == 4


def test_hub_static_url_with_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKQ_HUB_MOUNT", "/bookq")
    monkeypatch.setattr(
        "cryobookq.hub.context.fetch_daemon_health",
        lambda **_: {"status": "ok"},
    )
    from cryobookq.config import get_settings

    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
    app = create_app(tmp_path)
    with app.test_client() as client:
        r = client.get("/", environ_overrides={"SCRIPT_NAME": "/bookq"})
        assert r.status_code == 200
        assert b"/bookq/static/dashboard.css" in r.data
