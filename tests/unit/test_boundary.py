"""Unit: boundary / interval slot commit semantics."""

from datetime import UTC, datetime, timedelta

import pytest

from cryobookq.capture.scheduler import BoundaryTracker, IntervalSlotTracker, next_boundary


def test_next_boundary_alignment() -> None:
    now = datetime(2026, 3, 15, 12, 7, 30, tzinfo=UTC)
    assert next_boundary(now, 15) == datetime(2026, 3, 15, 12, 15, 0, tzinfo=UTC)
    exact = datetime(2026, 3, 15, 12, 15, 0, tzinfo=UTC)
    assert next_boundary(exact, 15) == datetime(2026, 3, 15, 12, 30, 0, tzinfo=UTC)


def test_boundary_tracker_never_reopens() -> None:
    tr = BoundaryTracker(interval_min=15)
    now = datetime(2026, 3, 15, 12, 10, 0, tzinfo=UTC)
    open_at, boundary = tr.next_slot(now, lead_s=12)
    assert boundary == datetime(2026, 3, 15, 12, 15, 0, tzinfo=UTC)
    assert open_at == boundary - timedelta(seconds=12)

    tr.commit(boundary)

    # Immediately after commit, even if still before boundary wall time,
    # next slot must be the *following* boundary.
    open2, b2 = tr.next_slot(now, lead_s=12)
    assert b2 == datetime(2026, 3, 15, 12, 30, 0, tzinfo=UTC)
    assert open2 == b2 - timedelta(seconds=12)


def test_boundary_tracker_rejects_double_commit() -> None:
    tr = BoundaryTracker(interval_min=15)
    b = datetime(2026, 3, 15, 12, 15, 0, tzinfo=UTC)
    tr.commit(b)
    with pytest.raises(ValueError):
        tr.commit(b)


def test_interval_slot_tracker() -> None:
    tr = IntervalSlotTracker(interval_s=15.0, epoch_monotonic=1000.0)
    fire, idx = tr.next_slot(1000.0)
    assert idx == 0 and fire == 1000.0
    tr.commit(0)
    fire2, idx2 = tr.next_slot(1005.0)
    assert idx2 == 1 and fire2 == 1015.0
    tr.commit(1)
    # Past due for slot 2
    fire3, idx3 = tr.next_slot(1040.0)
    assert idx3 == 2
