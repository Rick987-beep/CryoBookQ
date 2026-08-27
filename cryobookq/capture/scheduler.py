"""UTC boundary scheduling with one-shot slot commit (no re-open / no tight loops).

Pattern copied from CryoTrader tickrecorder: once a boundary is *committed*,
it is never attempted again — even if the capture fails. That prevents
rate-limit hammering when REST/WS is down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


def next_boundary(now: datetime | None = None, interval_min: int = 15) -> datetime:
    """Next UTC boundary at :00/:15/:30/:45 (or custom interval minutes)."""
    if now is None:
        now = datetime.now(tz=UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)

    minute = (now.minute // interval_min) * interval_min
    floored = now.replace(minute=minute, second=0, microsecond=0)
    if floored <= now:
        return floored + timedelta(minutes=interval_min)
    return floored


def lead_open(boundary: datetime, lead_s: float = 12.0) -> datetime:
    return boundary - timedelta(seconds=lead_s)


@dataclass
class BoundaryTracker:
    """Tracks the last committed UTC boundary so slots are never re-opened.

    Usage (daemon loop)::

        tracker = BoundaryTracker(interval_min=15)
        while running:
            open_at, boundary = tracker.next_slot(datetime.now(UTC), lead_s=12)
            await sleep_until(open_at)
            tracker.commit(boundary)          # BEFORE the attempt
            await run_snapshot(...)          # success or fail — slot is spent
    """

    interval_min: int = 15
    last_committed: datetime | None = None

    def next_slot(
        self,
        now: datetime,
        *,
        lead_s: float = 12.0,
    ) -> tuple[datetime, datetime]:
        """Return ``(lead_open_at, boundary)`` strictly after ``last_committed``."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)

        boundary = next_boundary(now, self.interval_min)
        if self.last_committed is not None:
            # Skip any boundary <= last committed (same or earlier slot).
            while boundary <= self.last_committed:
                boundary = boundary + timedelta(minutes=self.interval_min)

        return lead_open(boundary, lead_s), boundary

    def commit(self, boundary: datetime) -> None:
        if boundary.tzinfo is None:
            boundary = boundary.replace(tzinfo=UTC)
        else:
            boundary = boundary.astimezone(UTC)
        if self.last_committed is not None and boundary <= self.last_committed:
            raise ValueError(
                f"refusing to commit {boundary.isoformat()} "
                f"<= last_committed {self.last_committed.isoformat()}"
            )
        self.last_committed = boundary


@dataclass
class IntervalSlotTracker:
    """Fixed-interval slots from an epoch (used by soak / live interval tests).

    Same commit-before-attempt semantics as :class:`BoundaryTracker`, but
    aligned to ``epoch + n * interval_s`` instead of UTC clock faces.
    """

    interval_s: float
    epoch_monotonic: float
    last_committed_index: int = -1

    def next_slot(self, now_monotonic: float) -> tuple[float, int]:
        """Return ``(fire_at_monotonic, slot_index)`` after last committed."""
        idx = int((now_monotonic - self.epoch_monotonic) // self.interval_s)
        if idx <= self.last_committed_index:
            idx = self.last_committed_index + 1
        # If we're already past this slot's fire time, still return it (catch-up
        # once); commit will advance so we never re-fire the same index.
        fire_at = self.epoch_monotonic + idx * self.interval_s
        return fire_at, idx

    def commit(self, slot_index: int) -> None:
        if slot_index <= self.last_committed_index:
            raise ValueError(
                f"refusing to commit slot {slot_index} "
                f"<= last_committed_index {self.last_committed_index}"
            )
        self.last_committed_index = slot_index
