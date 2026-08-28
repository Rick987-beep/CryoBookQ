"""Load locked hub dashboard prose from ``copy.toml``."""

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


def intro_text() -> str:
    return str(load_copy()["intro"]["text"])


def section(key: str, **fmt: object) -> str:
    raw = str(load_copy()["sections"][key])
    return raw.format(**fmt) if fmt else raw


def footer() -> dict[str, str]:
    return {k: str(v) for k, v in load_copy()["footer"].items()}


def empty_message() -> str:
    return str(load_copy()["empty"]["message"])


def page_title() -> str:
    return str(load_copy()["meta"]["title"])
