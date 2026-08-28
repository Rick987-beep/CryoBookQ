"""Load locked report prose from ``copy.toml``."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

COPY_PATH = Path(__file__).resolve().parent / "copy.toml"


@lru_cache(maxsize=1)
def load_copy() -> dict[str, Any]:
    with COPY_PATH.open("rb") as f:
        return tomllib.load(f)


def section(name: str) -> dict[str, Any]:
    return dict(load_copy()["sections"][name])


def meta() -> dict[str, Any]:
    return dict(load_copy()["meta"])
