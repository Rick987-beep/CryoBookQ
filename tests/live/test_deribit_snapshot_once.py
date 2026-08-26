"""Live: deribit --once snapshot writes parquet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import Settings, get_settings
from tests.live.conftest import require_network

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_deribit_snapshot_once(tmp_path: Path) -> None:
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
    )
    result = await run_snapshot(["deribit"], settings=settings, duration_s=12.0, write=True)
    assert result.stats["deribit"]["n_with_update"] > 500
    assert result.index_px > 0
    assert result.raw_path is not None
    df = pd.read_parquet(result.raw_path)
    assert len(df) > 500
    for col in ("bid_px_1", "ask_px_5", "index_px", "venue"):
        assert col in df.columns
    assert (df["index_px"] > 0).all()
    assert set(df["venue"].unique()) == {"deribit"}
