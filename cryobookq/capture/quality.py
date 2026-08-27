"""Snapshot quality gate — coverage floors before accepting a write.

Incomplete bursts must not look like healthy forever-data. Tickrecorder skips
low-coverage snapshots; we mirror that with per-venue floors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_FLOORS = {
    "deribit": 0.90,
    "coincall": 0.80,
}


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    """Outcome of evaluating burst stats against coverage floors."""

    ok: bool
    """True when every *requested* venue that did not hard-error meets its floor
    and at least one venue produced usable books."""

    incomplete: bool
    """True when the snapshot should be treated as a gap/incomplete (not ok)."""

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
) -> QualityVerdict:
    """Evaluate per-venue burst stats.

    Parameters
    ----------
    venue_stats:
        Mapping venue → stats dict. Erroring venues should include
        ``{"error": "...", "coverage": 0.0, "n_with_update": 0, ...}``.
    requested:
        Venues that were asked to participate this snapshot.
    floors:
        Minimum coverage ratios; defaults :data:`DEFAULT_FLOORS`.
    """
    floors = {**DEFAULT_FLOORS, **(floors or {})}
    reasons: list[str] = []
    coverages: dict[str, float] = {}
    errors: dict[str, str] = {}
    usable = 0

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
        usable += 1

    # Accept if every non-error venue met its floor AND at least one usable.
    # If a venue hard-errored, the snapshot is incomplete even if the peer is fine
    # (we may still write the peer's rows — caller decides).
    all_ok = usable == len(requested) and not errors and not reasons
    # Partial success: at least one venue met floor, but peer failed → incomplete write OK
    partial = usable >= 1 and (bool(errors) or bool(reasons))
    ok = all_ok
    incomplete = not all_ok
    if usable == 0:
        reasons.append("no_venue_met_coverage_floor")
        incomplete = True
        ok = False
    elif partial and not reasons:
        # errors already recorded
        pass

    return QualityVerdict(
        ok=ok,
        incomplete=incomplete,
        reasons=tuple(reasons),
        coverages=coverages,
        venue_errors=errors,
    )
