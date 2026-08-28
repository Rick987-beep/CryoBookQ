#!/usr/bin/env python3
"""Final acceptance: 4 sequential snapshots (~60s apart), full pipeline + HTML report.

Binance needs up to ~90s per slot, so wall time is ~6–7 minutes even though
snapshots are *started* every 60s when the prior slot has finished.

    .venv/bin/python tools/final_acceptance.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import urllib.request
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.analytics.html_report import write_scorecard_html
from cryobookq.analytics.scorecard import build_scorecard_from_store, format_scorecard, merge_capture_snapshots
from cryobookq.capture.clock import CLOCK
from cryobookq.capture.snapshot import run_snapshot
from cryobookq.config import get_settings
from cryobookq.daemon.health import HEALTH, start_health_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("final_acceptance")

TMP = ROOT / "tmp" / "live"
DATA_DIR = TMP / "final_acceptance"
HTML_OUT = TMP / "final_acceptance_scorecard.html"
LOG_PATH = TMP / "final_acceptance.log"
SUMMARY_PATH = TMP / "final_acceptance_summary.json"
N_SNAPS = 4
GAP_S = 60.0


def _setup_file_log() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(fh)


async def _run() -> int:
    _setup_file_log()
    base = get_settings()
    if DATA_DIR.exists():
        import shutil

        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True)

    venues = ["deribit", "bybit", "okx", "binance"]
    if base.has_coincall_creds:
        venues.insert(1, "coincall")

    settings = replace(
        base,
        data_dir=DATA_DIR,
        burst_timeout_s=max(base.burst_timeout_s, 40.0),
        ws_collect_s=max(base.ws_collect_s, 30.0),
        binance_collect_s=max(base.binance_collect_s, 30.0),
        binance_timeout_s=max(base.binance_timeout_s, 90.0),
    )
    HEALTH.data_dir = str(settings.data_dir)
    HEALTH.disk_free_warn_mb = settings.disk_free_warn_mb

    try:
        await asyncio.to_thread(CLOCK.sync)
        HEALTH.clock = CLOCK.to_dict()
    except Exception as exc:  # noqa: BLE001
        logger.warning("clock sync skipped: %s", exc)

    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    health_port = s.getsockname()[1]
    s.close()
    start_health_server(HEALTH, port=health_port)
    logger.info("health http://127.0.0.1:%d/health", health_port)

    per: list[dict] = []
    t_epoch = time.monotonic()
    next_start = t_epoch

    for slot in range(N_SNAPS):
        wait = next_start - time.monotonic()
        if wait > 0:
            logger.info("waiting %.1fs until slot %d", wait, slot + 1)
            await asyncio.sleep(wait)
        logger.info("=== slot %d/%d ===", slot + 1, N_SNAPS)
        t0 = time.monotonic()
        try:
            result = await run_snapshot(
                venues,
                settings=settings,
                duration_s=30.0,
                write=True,
            )
            q = result.quality
            if q and q.ok and result.wrote:
                HEALTH.record_success(result.ts_ms, result.stats, wrote=True)
            else:
                reason = "; ".join(q.reasons) if q else "unknown"
                HEALTH.record_incomplete(
                    result.ts_ms,
                    result.stats,
                    wrote=result.wrote,
                    reason=reason,
                    gap=not (q and q.ok),
                )
            row = {
                "slot": slot + 1,
                "elapsed_s": round(time.monotonic() - t_epoch, 1),
                "duration_s": round(time.monotonic() - t0, 1),
                "wrote": result.wrote,
                "quality_ok": q.ok if q else None,
                "reasons": list(q.reasons) if q else [],
                "overall": (result.scorecard or {}).get("overall"),
                "venues": (result.scorecard or {}).get("venues"),
                "binance_in_scorecard": "binance"
                in ((result.scorecard or {}).get("venues") or []),
                "capture": (result.scorecard or {}).get("meta", {}).get("capture"),
            }
            for v in venues:
                st = result.stats.get(v) or {}
                row[f"{v}_coverage"] = st.get("coverage")
            row["raw_path"] = result.raw_path
            per.append(row)
            logger.info("%s", json.dumps(row, default=str))
        except Exception as exc:  # noqa: BLE001
            logger.exception("slot %d failed", slot + 1)
            HEALTH.record_failure(str(exc))
            HEALTH.record_gap()
            per.append({"slot": slot + 1, "error": str(exc)})
        next_start = time.monotonic() + GAP_S

    try:
        card = build_scorecard_from_store(DATA_DIR)
        card.meta["capture"] = merge_capture_snapshots(
            [p.get("capture") for p in per if isinstance(p.get("capture"), dict)]
        )
        assert "binance" in card.venues, f"binance missing from scorecard venues={card.venues}"
        print(format_scorecard(card))
        write_scorecard_html(card, HTML_OUT)
        logger.info("HTML %s", HTML_OUT)
    except Exception as exc:  # noqa: BLE001
        logger.exception("period scorecard failed: %s", exc)
        card = None

    health_json = urllib.request.urlopen(f"http://127.0.0.1:{health_port}/health", timeout=5).read()
    health = json.loads(health_json)

    summary = {
        "n_snaps": N_SNAPS,
        "wall_s": round(time.monotonic() - t_epoch, 1),
        "venues": venues,
        "data_dir": str(DATA_DIR),
        "html": str(HTML_OUT),
        "log": str(LOG_PATH),
        "per_slot": per,
        "health": health,
        "scorecard": {
            "venues": card.venues if card else None,
            "overall": card.overall if card else None,
            "n_snapshots": card.meta.get("n_snapshots") if card else 0,
            "capture": card.meta.get("capture") if card else None,
        },
        "checks": {
            "all_wrote": all(p.get("wrote") for p in per if "error" not in p),
            "hub_ok": all(p.get("quality_ok") for p in per if "error" not in p),
            "binance_on_scorecard": card is not None and "binance" in card.venues,
            "binance_in_parquet": card is not None and "binance" in (card.meta.get("capture") or {}),
        },
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    logger.info("summary %s", SUMMARY_PATH)

    ok = (
        summary["checks"]["all_wrote"]
        and summary["checks"]["hub_ok"]
        and summary["checks"]["binance_on_scorecard"]
    )
    return 0 if ok else 2


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
