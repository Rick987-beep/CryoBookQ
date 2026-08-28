"""Executive Summary narrative (deterministic, no LLM)."""

from __future__ import annotations

from cryobookq.analytics.report.labels import DELTA_LABELS, venue_name
from cryobookq.analytics.scorecard import (
    DELTA_TARGETS,
    OVERALL_WEIGHTS,
    TENOR_TARGETS,
    WING_LABEL,
    ScorecardResult,
)


def component_means(card: ScorecardResult) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for v in card.venues:
        gs = [
            float(card.grid[f"{t}:{d}"]["venues"][v]["score"])
            for t in TENOR_TARGETS
            for d in DELTA_TARGETS
            if f"{t}:{d}" in card.grid and v in card.grid[f"{t}:{d}"]["venues"]
        ]
        ws = [
            float(card.wings[f"{t}:{WING_LABEL}"]["venues"][v]["score"])
            for t in TENOR_TARGETS
            if f"{t}:{WING_LABEL}" in card.wings and v in card.wings[f"{t}:{WING_LABEL}"]["venues"]
        ]
        ps = float((card.presence.get("per_venue") or {}).get(v, {}).get("score") or 0.0)
        out[v] = {
            "grid": sum(gs) / len(gs) if gs else 0.0,
            "wings": sum(ws) / len(ws) if ws else 0.0,
            "presence": ps,
        }
    return out


def build_executive_summary(card: ScorecardResult) -> str:
    """Plain-language narrative for management."""
    means = component_means(card)
    ranked = sorted(card.overall.items(), key=lambda kv: -kv[1])
    if len(ranked) < 2:
        leader, lead_s = ranked[0]
        return (
            f"{venue_name(leader)} scores {lead_s:.2f} / 10 on the overall index "
            f"for this sample. Add a second venue to enable head-to-head reading."
        )

    (leader, lead_s), (trailer, trail_s) = ranked[0], ranked[1]
    gap = lead_s - trail_s
    lm, tm = means[leader], means[trailer]

    beats: list[str] = []
    for tenor in TENOR_TARGETS:
        for d in DELTA_TARGETS:
            key = f"{tenor}:{d}"
            cell = card.grid.get(key)
            if not cell:
                continue
            sv = cell["venues"]
            if leader not in sv or trailer not in sv:
                continue
            if float(sv[trailer]["score"]) > float(sv[leader]["score"]):
                beats.append(f"{tenor} {DELTA_LABELS.get(d, d)}")

    parts = [
        f"{venue_name(leader)} leads the overall index at {lead_s:.2f} / 10 versus "
        f"{venue_name(trailer)} at {trail_s:.2f} (gap {gap:.2f}). "
        f"The index weights the 3×3 liquidity grid at {OVERALL_WEIGHTS['grid']:.0%}, "
        f"far-OTM wings at {OVERALL_WEIGHTS['wings']:.0%}, and quote presence at "
        f"{OVERALL_WEIGHTS['presence']:.0%}."
    ]

    if lm["presence"] > tm["presence"] + 0.5:
        pv_l = card.presence["per_venue"][leader]
        pv_t = card.presence["per_venue"][trailer]
        parts.append(
            f" Presence is a major driver: {venue_name(leader)} shows "
            f"{pv_l['two_sided_rate']:.0%} two-sided quotes among matched options with "
            f"|Δ| ≥ 0.05, versus {pv_t['two_sided_rate']:.0%} for {venue_name(trailer)}. "
            f"One-sided or empty books score zero on spread and $10k-lift in that cell."
        )

    if lm["grid"] > tm["grid"]:
        parts.append(
            f" On the core grid, {venue_name(leader)} averages {lm['grid']:.2f} versus "
            f"{tm['grid']:.2f}, typically from deeper L5 books and more reliable "
            f"$10 000 premium fills—especially short-dated."
        )
    else:
        parts.append(
            f" On the core grid means alone, {venue_name(trailer)} is close or ahead "
            f"({tm['grid']:.2f} vs {lm['grid']:.2f}); overall leadership then rests more "
            f"on presence and/or wings."
        )

    if beats:
        shown = ", ".join(beats[:4])
        extra = f" (+{len(beats) - 4} more)" if len(beats) > 4 else ""
        parts.append(
            f" Where {venue_name(trailer)} posts a live two-sided book, it can still win "
            f"individual cells on tighter relative spreads—notably {shown}{extra}. "
            f"The scorecard surfaces that instead of averaging every far-OTM listing equally."
        )

    parts.append(
        f" Wing quality (2.5Δ) averages {lm['wings']:.2f} for {venue_name(leader)} versus "
        f"{tm['wings']:.2f} for {venue_name(trailer)}."
    )
    return "".join(parts)
