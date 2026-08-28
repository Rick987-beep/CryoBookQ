#!/usr/bin/env python3
"""Write an executive HTML scorecard from a data dir or scorecard JSON.

Examples::

    .venv/bin/python tools/scorecard_html.py --data-dir tmp/soak_scorecard_period
    .venv/bin/python tools/scorecard_html.py --json tmp/soak_scorecard_period/scorecard_period.json \\
        --out reports/bookq_scorecard.html --hours 12:18
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

from cryobookq.analytics.html_report import scorecard_from_dict, write_scorecard_html
from cryobookq.analytics.scorecard import build_scorecard_from_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scorecard_html")


def _parse_hours(s: str | None) -> tuple[int | None, int | None]:
    if not s:
        return None, None
    a, b = s.split(":", 1)
    return int(a), int(b)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--data-dir", type=Path, help="Parquet lake with raw_books/")
    src.add_argument("--json", type=Path, help="Existing scorecard_period.json")
    parser.add_argument("--dates", nargs="*", default=None)
    parser.add_argument("--hours", default=None, help="UTC START:END exclusive")
    parser.add_argument("--start-ms", type=int, default=None)
    parser.add_argument("--end-ms", type=int, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output HTML path (default: <data-dir|json-dir>/scorecard.html)",
    )
    parser.add_argument("--title", default="Comparison Scorecard")
    args = parser.parse_args()

    h0, h1 = _parse_hours(args.hours)
    if args.json:
        card = scorecard_from_dict(json.loads(args.json.read_text()))
        out = args.out or (args.json.parent / "scorecard.html")
    else:
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
        out = args.out or (args.data_dir / "scorecard.html")

    write_scorecard_html(card, out, title=args.title)
    logger.info("Wrote %s (snapshots=%s)", out, card.meta.get("n_snapshots", 1))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
