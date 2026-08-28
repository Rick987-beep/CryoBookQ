"""Snapshot quality gate — per-venue floors; overall ok = hub (Deribit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

HUB = "deribit"

DEFAULT_FLOORS = {
    "deribit": 0.90,
    "coincall": 0.80,
    "bybit": 0.80,
    "okx": 0.80,
    "binance": 0.80,
}


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    """Outcome of evaluating burst stats against coverage floors."""

    ok: bool
    """True when the listing hub (Deribit) met its floor, or — if hub was not
    requested — at least one venue met its floor."""

    incomplete: bool
    """True when any requested venue failed or missed its floor."""

    reasons: tuple[str, ...] = ()
    coverages: dict[str, float] = field(default_factory=dict)
    venue_errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "incomplete": self.incomplete,
            "reasons": list(self.reasons),
            "coverages": dict(self.coverages),
            "venue_errors": dict(self.venue_errors),
        }


def evaluate_quality(
    venue_stats: dict[str, dict[str, Any]],
    *,
    requested: list[str],
    floors: dict[str, float] | None = None,
    hub: str = HUB,
) -> QualityVerdict:
    floors = {**DEFAULT_FLOORS, **(floors or {})}
    reasons: list[str] = []
    coverages: dict[str, float] = {}
    errors: dict[str, str] = {}
    met: set[str] = set()

    for venue in requested:
        st = venue_stats.get(venue) or {}
        if st.get("error"):
            errors[venue] = str(st["error"])
            coverages[venue] = float(st.get("coverage") or 0.0)
            reasons.append(f"{venue}:error:{errors[venue][:120]}")
            continue

        cov = float(st.get("coverage") or 0.0)
        coverages[venue] = cov
        floor = float(floors.get(venue, 0.8))
        if cov < floor:
            reasons.append(f"{venue}:coverage {cov:.2%} < floor {floor:.0%}")
            continue
        met.add(venue)

    hub_requested = hub in requested
    if hub_requested:
        ok = hub in met
    else:
        ok = bool(met)
    incomplete = bool(reasons) or bool(errors) or not met
    if not met:
        reasons.append("no_venue_met_coverage_floor")
        ok = False
        incomplete = True

    return QualityVerdict(
        ok=ok,
        incomplete=incomplete,
        reasons=tuple(reasons),
        coverages=coverages,
        venue_errors=errors,
    )
