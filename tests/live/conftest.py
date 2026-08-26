"""Shared live-test helpers."""

from __future__ import annotations

import os

import pytest

from cryobookq.config import get_settings


def require_network() -> None:
    if os.getenv("BOOKQ_SKIP_LIVE") == "1":
        pytest.skip("BOOKQ_SKIP_LIVE=1")


def require_coincall_creds() -> None:
    settings = get_settings()
    if not settings.has_coincall_creds:
        pytest.skip("COINCALL_API_KEY/SECRET not set")
