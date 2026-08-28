"""Live ME3: multi-venue snapshot returns; hub writes."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import pytest

from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import Settings, get_settings
from tests.live.conftest import require_network

pytestmark = pytest.mark.live

TMP = Path("tmp/live")


@pytest.mark.asyncio
async def test_me3_multi_snapshot(tmp_path: Path) -> None:
    require_network()
    base = get_settings()
    settings = Settings(
        underlying=base.underlying,
        depth=base.depth,
        snapshot_interval_min=base.snapshot_interval_min,
        data_dir=tmp_path,
        hub_port=base.hub_port,
        coincall_api_key=base.coincall_api_key,
        coincall_api_secret=base.coincall_api_secret,
        coincall_env=base.coincall_env,
        coverage_floor_deribit=0.90,
        coverage_floor_bybit=0.30,
        coverage_floor_okx=0.30,
        coverage_floor_binance=0.30,
        burst_timeout_s=40.0,
        ws_collect_s=12.0,
        binance_collect_s=12.0,
        binance_rest_budget_s=15.0,
        binance_timeout_s=40.0,
    )
    venues = ["deribit", "bybit", "okx", "binance"]
    t0 = time.perf_counter()
    result = await run_snapshot(venues, settings=settings, duration_s=18.0, write=True)
    elapsed = time.perf_counter() - t0
    assert elapsed < 55.0, f"snapshot hung elapsed={elapsed:.1f}s"
    assert result.stats["deribit"]["coverage"] >= 0.90
    assert result.wrote
    assert result.raw_path
    df = pd.read_parquet(result.raw_path)
    assert "deribit" in set(df["venue"].unique())
    others = set(df["venue"].unique()) & {"bybit", "okx", "binance"}
    assert others, f"expected at least one new venue in parquet, got {df['venue'].unique()}"
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "me3_stats.json").write_text(json.dumps(result.stats, indent=2, default=str) + "\n")
