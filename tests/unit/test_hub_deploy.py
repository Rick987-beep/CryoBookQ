"""Hub smoke + deploy dry-run."""

import subprocess
from pathlib import Path

from cryobookq.hub.app import create_app
from cryobookq.pipeline.score import score_pairs
from cryobookq.pipeline.match import MatchedPair
from cryobookq.pipeline.write import ParquetStore
from cryobookq.types import OptionKey


def test_hub_renders_fixture_scores(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    key = OptionKey("BTC", 1_800_000_000_000, 80000.0, True)

    def row(bid: float, ask: float) -> dict:
        r = {f"bid_px_{i}": 0.0 for i in range(1, 6)}
        r.update({f"ask_px_{i}": 0.0 for i in range(1, 6)})
        r.update({f"bid_sz_{i}": 0.0 for i in range(1, 6)})
        r.update({f"ask_sz_{i}": 0.0 for i in range(1, 6)})
        r["bid_px_1"] = bid
        r["ask_px_1"] = ask
        r["bid_sz_1"] = 2.0
        r["ask_sz_1"] = 2.0
        r["venue_symbol"] = "S"
        r["delta"] = 0.2
        return r

    ts = 1_710_000_000_000
    pairs = [
        MatchedPair(key=key, deribit=row(100, 110), coincall=row(100, 105)),
    ]
    scores = score_pairs(pairs, ts_ms=ts)
    store.write_pair_scores(scores, ts, append=False)

    app = create_app(tmp_path)
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"Composite winners" in r.data
    h = client.get("/health")
    assert h.status_code == 200
    assert h.get_json()["data_dir"]


def test_deploy_dry_run() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "deploy" / "deploy.sh"
    assert script.is_file()
    proc = subprocess.run(
        ["bash", str(script), "--dry-run"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "dry_run=1" in proc.stdout
    assert "BOOKQ_ALLOW_DEPLOY=1" in proc.stdout

