#!/usr/bin/env python3
"""Build a landmark scorecard from many raw_books snapshots on disk.

Examples::

    # All parts under data dir
    .venv/bin/python tools/scorecard_period.py --data-dir tmp/soak_interval

    # UTC afternoon window
    .venv/bin/python tools/scorecard_period.py --data-dir ./data --hours 12:18
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryobookq.analytics.scorecard import build_scorecard_from_store, format_scorecard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scorecard_period")


def _parse_hours(s: str | None) -> tuple[int | None, int | None]:
    if not s:
        return None, None
    a, b = s.split(":", 1)
    return int(a), int(b)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--dates", nargs="*", default=None, help="Optional date=YYYY-MM-DD list")
    parser.add_argument("--hours", default=None, help="UTC hour window START:END exclusive, e.g. 12:18")
    parser.add_argument("--start-ms", type=int, default=None)
    parser.add_argument("--end-ms", type=int, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    h0, h1 = _parse_hours(args.hours)
    try:
        card = build_scorecard_from_store(
            args.data_dir,
            dates=args.dates,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
            utc_hour_start=h0,
            utc_hour_end=h1,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 2

    print(format_scorecard(card))
    print()
    print(json.dumps({"overall": card.overall, "meta": card.meta}, indent=2, default=str))
    out = args.json_out or (args.data_dir / "scorecard_period.json")
    out.write_text(json.dumps(card.to_dict(), indent=2, default=str))
    logger.info("Wrote %s (snapshots=%s)", out, card.meta.get("n_snapshots"))
    return 0 if card.meta.get("n_snapshots", 0) >= 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
