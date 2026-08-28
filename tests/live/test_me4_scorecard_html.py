"""Live ME4: snapshot ≥3 venues and render Comparison Scorecard HTML."""

from __future__ import annotations

from pathlib import Path

import pytest

from cryobookq.analytics.html_report import write_scorecard_html
from cryobookq.analytics.scorecard import build_scorecard, build_scorecard_from_store
from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import Settings, get_settings
from cryobookq.pipeline.match import match_raw_rows
from tests.live.conftest import require_network

pytestmark = pytest.mark.live

TMP = Path("tmp/live")


@pytest.mark.asyncio
async def test_me4_scorecard_html(tmp_path: Path) -> None:
    require_network()
    base = get_settings()
    settings = Settings(
        underlying=base.underlying,
        depth=base.depth,
        data_dir=tmp_path,
        coincall_api_key=base.coincall_api_key,
        coincall_api_secret=base.coincall_api_secret,
        coincall_env=base.coincall_env,
        coverage_floor_deribit=0.90,
        coverage_floor_bybit=0.30,
        coverage_floor_okx=0.30,
        coverage_floor_binance=0.30,
        burst_timeout_s=40.0,
    )
    venues = ["deribit", "bybit", "okx", "binance"]
    if base.has_coincall_creds:
        venues.insert(1, "coincall")
    result = await run_snapshot(
        venues,
        settings=settings,
        duration_s=15.0,
        write=True,
    )
    assert result.wrote
    assert result.raw_rows
    pairs = match_raw_rows(result.raw_rows)
    hub = [p for p in pairs if p.has_hub]
    assert hub
    card = build_scorecard(pairs, ts_ms=result.ts_ms)
    assert "deribit" in card.overall
    assert 0 <= card.overall["deribit"] <= 10
    from cryobookq.pipeline.match import MatchedPair as make_pair

    deribit_only = [make_pair(key=p.key, deribit=p.deribit) for p in pairs if p.deribit is not None]
    card_d = build_scorecard(deribit_only, ts_ms=result.ts_ms)
    assert abs(card.overall["deribit"] - card_d.overall["deribit"]) < 0.5

    TMP.mkdir(parents=True, exist_ok=True)
    path = write_scorecard_html(card, TMP / "me4_scorecard.html")
    text = Path(path).read_text()
    assert "Deribit" in text
    assert "Bybit" in text or "OKX" in text

    period = build_scorecard_from_store(tmp_path)
    assert "deribit" in period.overall
