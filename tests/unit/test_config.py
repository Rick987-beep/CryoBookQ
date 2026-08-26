"""Unit tests: config loading."""

import os
from pathlib import Path

from cryobookq.config import Settings, get_settings, load_env


def test_defaults(monkeypatch) -> None:
    for k in list(os.environ):
        if k.startswith("BOOKQ_") or k.startswith("COINCALL_"):
            monkeypatch.delenv(k, raising=False)
    # Avoid loading real .env for this test
    s = Settings()
    assert s.underlying == "BTC"
    assert s.depth == 5
    assert s.snapshot_interval_min == 15
    assert not s.has_coincall_creds


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("BOOKQ_UNDERLYING", "eth")
    monkeypatch.setenv("BOOKQ_DEPTH", "5")
    monkeypatch.setenv("BOOKQ_DATA_DIR", "/tmp/bookq-data")
    monkeypatch.setenv("COINCALL_API_KEY", "k")
    monkeypatch.setenv("COINCALL_API_SECRET", "s")
    s = get_settings(load=False)
    assert s.underlying == "ETH"
    assert s.data_dir == Path("/tmp/bookq-data")
    assert s.has_coincall_creds


def test_load_env_example_exists() -> None:
    example = Path(__file__).resolve().parents[2] / ".env.example"
    assert example.is_file()
    load_env(example)  # should not raise
