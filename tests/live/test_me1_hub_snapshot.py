"""Live ME1: dual snapshot uses Deribit hub; LCD match rate still high."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import Settings, get_settings
from tests.live.conftest import require_coincall_creds, require_network

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_me1_hub_snapshot(tmp_path: Path) -> None:
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
    assert result.stats["deribit"]["coverage"] >= 0.90
    assert result.stats["coincall"]["coverage"] >= 0.80
    assert result.stats.get("n_hub", 0) >= 500
    assert result.scorecard is not None
    overall = result.scorecard["overall"]
    assert "deribit" in overall and "coincall" in overall
    assert 0 <= overall["deribit"] <= 10
    assert 0 <= overall["coincall"] <= 10

    df = pd.read_parquet(result.raw_path)
    assert set(df["venue"].unique()) == {"deribit", "coincall"}
    n_hub = int(result.stats["n_hub"])
    n_matched = int(result.stats["n_matched"])
    assert n_matched / n_hub >= 0.80

    scores = pd.read_parquet(result.scores_path)
    two = scores[scores["match_status"] == "matched"]
    two = two[two["deribit_two_sided"] & two["coincall_two_sided"]]
    if len(two) > 10:
        ratio = (two["deribit_bid_sz_1"] + 1e-9) / (two["coincall_bid_sz_1"] + 1e-9)
        med = float(ratio.median())
        assert 0.01 < med < 100.0, f"size unit sanity median ratio={med}"
