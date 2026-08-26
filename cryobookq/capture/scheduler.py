"""15-min boundary helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def next_boundary(now: datetime | None = None, interval_min: int = 15) -> datetime:
    """Next UTC boundary at :00/:15/:30/:45 (or custom interval)."""
    if now is None:
        now = datetime.now(tz=UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)

    # Floor to interval, then add one interval if not exactly on boundary
    minute = (now.minute // interval_min) * interval_min
    floored = now.replace(minute=minute, second=0, microsecond=0)
    if floored < now:
        return floored + timedelta(minutes=interval_min)
    if floored == now and (now.second > 0 or now.microsecond > 0):
        return floored + timedelta(minutes=interval_min)
    # Exactly on boundary with 0 sec → that boundary is "now"; next is +interval
    if floored == now:
        return floored + timedelta(minutes=interval_min)
    return floored


def lead_open(boundary: datetime, lead_s: float = 12.0) -> datetime:
    return boundary - timedelta(seconds=lead_s)
