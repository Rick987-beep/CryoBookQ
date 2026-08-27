"""Unit: exchange clock + instrument cache + day roll."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from cryobookq.capture.clock import ExchangeClock
from cryobookq.capture.instruments import InstrumentCache
from cryobookq.daemon.health import HealthState
from cryobookq.types import Instrument, OptionKey


def test_exchange_clock_sync_sets_offset() -> None:
    clock = ExchangeClock()
    t0 = 1_700_000_000.0
    # Deribit reports mid-request + 250ms → local is 0.25s behind.
    deribit_ms = int((t0 + 0.25) * 1000)
    with patch("cryobookq.capture.clock.fetch_deribit_time_ms", return_value=deribit_ms):
        with patch("cryobookq.capture.clock.time.time", side_effect=[t0, t0]):
            with patch("cryobookq.capture.clock.time.monotonic", return_value=42.0):
                offset = clock.sync()
    assert abs(offset - 0.25) < 1e-6
    assert clock.last_sync_mono == 42.0
    assert clock.last_error is None
    d = clock.to_dict()
    assert d["offset_s"] == 0.25


def test_instrument_cache_hit_within_ttl() -> None:
    cache = InstrumentCache(ttl_s=60.0)
    key = OptionKey("BTC", 1, 1.0, True)
    good = [Instrument(venue="deribit", venue_symbol="BTC-1JAN30-1-C", key=key)]
    with patch.object(cache, "_fetch", return_value=good) as fetch:
        a, meta_a = cache.get("deribit", "BTC")
        b, meta_b = cache.get("deribit", "BTC")
    assert fetch.call_count == 1
    assert meta_a["from_cache"] is False
    assert meta_b["from_cache"] is True and meta_b["stale"] is False
    assert len(a) == len(b) == 1


def test_instrument_cache_stale_on_failure() -> None:
    cache = InstrumentCache(ttl_s=60.0)
    key = OptionKey("BTC", 1, 1.0, True)
    good = [Instrument(venue="deribit", venue_symbol="BTC-1JAN30-1-C", key=key)]

    with patch.object(cache, "_fetch", return_value=good):
        inst, meta = cache.get("deribit", "BTC")
    assert meta["from_cache"] is False and len(inst) == 1

    with patch.object(cache, "_fetch", side_effect=RuntimeError("boom")):
        cache._entries["deribit:BTC"].fetched_mono -= 120
        inst2, meta2 = cache.get("deribit", "BTC")
    assert meta2["stale"] is True
    assert meta2["from_cache"] is True
    assert len(inst2) == 1
    assert "fetch_error" in meta2


def test_instrument_cache_raises_without_prior() -> None:
    cache = InstrumentCache(ttl_s=60.0)
    with patch.object(cache, "_fetch", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            cache.get("deribit", "BTC")


def test_health_utc_day_roll() -> None:
    h = HealthState()
    h.snapshots_today = 5
    h.gaps_today = 2
    h.incomplete_today = 1
    h.writes_today = 4
    h._day_utc = "2026-01-01"
    with patch("cryobookq.daemon.health.datetime") as dt:
        dt.now.return_value = datetime(2026, 1, 2, 0, 0, 1, tzinfo=UTC)
        h.reset_day_counters_if_needed()
    assert h.snapshots_today == 0
    assert h.gaps_today == 0
    assert h.incomplete_today == 0
    assert h.writes_today == 0
    assert h._day_utc == "2026-01-02"


def test_health_as_dict_includes_day_and_clock() -> None:
    h = HealthState()
    h.clock = {"offset_s": 0.1}
    h.data_dir = None
    d = h.as_dict()
    assert "day_utc" in d
    assert d["clock"]["offset_s"] == 0.1
