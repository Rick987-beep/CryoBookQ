"""Acceptance: 4 snapshots (~1 min cadence), all venues, scorecard HTML.

    .venv/bin/python tools/acceptance_multi.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    out_html = ROOT / "tmp" / "live" / "acceptance_scorecard.html"
    out_html.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(ROOT / "tools" / "soak_interval.py"),
        "--total",
        "60",
        "--interval",
        "15",
        "--duration",
        "12",
        "--data-dir",
        str(ROOT / "tmp" / "live" / "acceptance"),
        "--relaxed-floors",
        "--html-out",
        str(out_html),
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
