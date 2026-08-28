"""One slow Binance sampler snapshot + scores.

Runs the full mitigation (4 WS sockets, paced SUBSCRIBE, ~50s listen, paced REST,
ticker remainder) beside the Deribit hub, then writes parquet + scorecard HTML.

    .venv/bin/python tools/acceptance_binance_slow.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.analytics.html_report import write_scorecard_html
from cryobookq.analytics.scorecard import build_scorecard, format_scorecard
from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import get_settings
from cryobookq.pipeline.match import match_raw_rows


TMP = ROOT / "tmp" / "live"
LOG_PATH = TMP / "binance_slow.log"
DATA_DIR = TMP / "binance_slow"
HTML_PATH = TMP / "binance_slow_scorecard.html"
STATS_PATH = TMP / "binance_slow_stats.json"


def _setup_logging() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    root.handlers.clear()
    root.addHandler(sh)
    root.addHandler(fh)


def _catalogue_lines(notes: list[str]) -> list[str]:
    return [n for n in notes if n.startswith("cat_") or n.startswith("rest_") or n.startswith("ticker")]


async def _run() -> int:
    _setup_logging()
    log = logging.getLogger("acceptance_binance_slow")
    base = get_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = replace(
        base,
        data_dir=DATA_DIR,
        coverage_floor_binance=0.80,
    )
    log.info(
        "start collect=%.0fs rest_budget=%.0fs wait=%.0fs data=%s",
        settings.binance_collect_s,
        settings.binance_rest_budget_s,
        settings.burst_wait_s("binance"),
        DATA_DIR,
    )
    t0 = time.perf_counter()
    result = await run_snapshot(
        ["deribit", "binance"],
        settings=settings,
        duration_s=18.0,
        write=True,
    )
    elapsed = time.perf_counter() - t0
    bn = result.stats.get("binance") or {}
    hub = result.stats.get("deribit") or {}
    notes = list(bn.get("notes") or [])
    log.info("elapsed=%.1fs wrote=%s quality_ok=%s", elapsed, result.wrote, bool(result.quality and result.quality.ok))
    log.info("deribit coverage=%.1f%% n=%s", 100.0 * float(hub.get("coverage") or 0), hub.get("n_instruments"))
    log.info(
        "binance coverage=%.1f%% n=%s with_update=%s duration=%.1fs",
        100.0 * float(bn.get("coverage") or 0),
        bn.get("n_instruments"),
        bn.get("n_with_update"),
        bn.get("duration_s") or 0,
    )
    for line in _catalogue_lines(notes):
        log.info("catalogue %s", line)
    log.info("binance notes=%s", notes)
    log.info("binance errors=%s", (bn.get("subscribe_errors") or [])[:5])

    STATS_PATH.write_text(json.dumps(result.stats, indent=2, default=str) + "\n")
    if result.raw_rows:
        pairs = match_raw_rows(result.raw_rows)
        card = build_scorecard(pairs, ts_ms=result.ts_ms)
        write_scorecard_html(card, HTML_PATH)
        log.info("scorecard\n%s", format_scorecard(card))
        log.info("html=%s", HTML_PATH)
        overall = card.overall
        log.info("overall=%s", overall)
    else:
        log.warning("no raw rows; skip scorecard")

    log.info("log=%s stats=%s", LOG_PATH, STATS_PATH)
    if not result.wrote:
        return 2
    if float(bn.get("coverage") or 0) < 0.80:
        log.error("binance coverage below 80%% floor")
        return 3
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
