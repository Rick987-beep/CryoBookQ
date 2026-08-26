"""Live: dual venue snapshot + match rate."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import Settings, get_settings
from tests.live.conftest import require_coincall_creds, require_network

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_dual_snapshot_once(tmp_path: Path) -> None:
    require_network()
    require_coincall_creds()
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
    result = await run_snapshot(
        ["deribit", "coincall"],
        settings=settings,
        duration_s=15.0,
        write=True,
    )
    assert result.stats["match_rate"] >= 0.85
    assert "capture_lag_ms" in result.stats["deribit"]
    assert "capture_lag_ms" in result.stats["coincall"]
    df = pd.read_parquet(result.raw_path)
    assert set(df["venue"].unique()) == {"deribit", "coincall"}
    scores = pd.read_parquet(result.scores_path)
    assert len(scores) > 500
    assert "winner_composite" in scores.columns

    # Size-unit sanity on ATM-ish matched two-sided: order of magnitude check (warn-level soft)
    matched = scores[scores["match_status"] == "matched"]
    two = matched[matched["deribit_two_sided"] & matched["coincall_two_sided"]]
    if len(two) > 10:
        ratio = (two["deribit_bid_sz_1"] + 1e-9) / (two["coincall_bid_sz_1"] + 1e-9)
        # Soft: median ratio within 0.01x–100x
        med = float(ratio.median())
        assert 0.01 < med < 100.0, f"size unit sanity median ratio={med}"
