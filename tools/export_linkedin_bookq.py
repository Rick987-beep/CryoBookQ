#!/usr/bin/env python3
"""Export LinkedIn square PNG from assets/linkedin-bookq-ranking.html via avis Playwright."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AVIS_PKG = Path.home() / "agent-commons" / "tools" / "avis"
sys.path.insert(0, str(AVIS_PKG))

from agent_visuals.serve import render_ephemeral  # noqa: E402

HTML = ROOT / "assets" / "linkedin-bookq-ranking.html"
OUT = ROOT / "assets" / "linkedin-bookq-ranking.png"


def main() -> None:
    html = HTML.read_text(encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    render_ephemeral(html, OUT, 1080, 1080, dpr=2.0)
    print(OUT.resolve())


if __name__ == "__main__":
    main()
