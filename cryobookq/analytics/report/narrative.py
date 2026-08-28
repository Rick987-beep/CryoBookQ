"""Executive Summary narrative (deterministic, no LLM)."""

from __future__ import annotations

from cryobookq.analytics.report.labels import venue_name
from cryobookq.analytics.scorecard import (
    DELTA_TARGETS,
    HUB_VENUE,
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


def _unique_max(values: dict[str, float], *, min_gap: float = 1e-9) -> str | None:
    if not values:
        return None
    ranked = sorted(values.items(), key=lambda kv: -kv[1])
    if len(ranked) == 1:
        return ranked[0][0]
    if ranked[0][1] > ranked[1][1] + min_gap:
        return ranked[0][0]
    return None


def _unique_min(values: dict[str, float], *, min_gap: float = 1e-9) -> str | None:
    if not values:
        return None
    ranked = sorted(values.items(), key=lambda kv: kv[1])
    if len(ranked) == 1:
        return ranked[0][0]
    if ranked[0][1] < ranked[1][1] - min_gap:
        return ranked[0][0]
    return None


def _cat(card: ScorecardResult, v: str) -> dict:
    return dict((card.catalogue.get("per_venue") or {}).get(v) or {})


def _venue_sentence(v: str, card: ScorecardResult, means: dict[str, dict[str, float]]) -> str:
    """One sentence on what stands out for this venue in the sample."""
    name = venue_name(v)
    ov = float(card.overall.get(v) or 0.0)
    m = means[v]
    pv = (card.presence.get("per_venue") or {}).get(v) or {}
    cat = _cat(card, v)
    n_inst = int(cat.get("n_instruments") or 0)
    n_ex = int(cat.get("n_extras") or 0)
    n_hub = int(cat.get("n_hub_two_sided") or 0)
    rate = float(pv.get("two_sided_rate") or 0.0)
    cat_s = float(cat.get("score") or 0.0)

    others = [x for x in card.venues if x in card.overall]
    grid_m = {x: means[x]["grid"] for x in others}
    wing_m = {x: means[x]["wings"] for x in others}
    pres_m = {x: float((card.presence.get("per_venue") or {}).get(x, {}).get("two_sided_rate") or 0) for x in others}
    extra_m = {x: float(_cat(card, x).get("n_extras") or 0) for x in others}
    inst_m = {x: float(_cat(card, x).get("n_instruments") or 0) for x in others}
    cat_m = {x: float(_cat(card, x).get("score") or 0) for x in others}

    if v == HUB_VENUE:
        return (
            f"{name} scores {ov:.2f} / 10 as the listing hub, with {n_hub} two-sided quotes "
            f"among eligible names and {n_inst} captured books in this sample."
        )
    if _unique_min(pres_m, min_gap=0.05) == v:
        return (
            f"{name} scores {ov:.2f} / 10, listing {n_inst} books but two-sided on only "
            f"{rate:.0%} of hub names it listed, which zeros spread and $10k lift on those cells."
        )
    if _unique_max(extra_m, min_gap=1.0) == v and n_ex > 0:
        return (
            f"{name} scores {ov:.2f} / 10 and leads on names the hub does not quote two-sided "
            f"({n_ex} extras from {n_inst} captured books)."
        )
    if _unique_min(extra_m, min_gap=1.0) == v and len(others) > 2:
        return (
            f"{name} scores {ov:.2f} / 10, with little surface beyond the hub "
            f"({n_ex} extras, {n_inst} captured books)."
        )
    if _unique_max(cat_m, min_gap=0.05) == v:
        return (
            f"{name} scores {ov:.2f} / 10, with the highest Catalogue score ({cat_s:.2f}) "
            f"on {n_hub} hub names and {n_ex} extras."
        )
    if _unique_max(grid_m, min_gap=0.05) == v:
        return (
            f"{name} scores {ov:.2f} / 10, with the strongest 3×3 grid mean in this sample "
            f"({m['grid']:.2f})."
        )
    if _unique_max(wing_m, min_gap=0.05) == v:
        return (
            f"{name} scores {ov:.2f} / 10, with the strongest 2.5Δ wing mean ({m['wings']:.2f})."
        )
    if _unique_max(pres_m, min_gap=0.02) == v:
        return (
            f"{name} scores {ov:.2f} / 10, with two-sided quotes on {rate:.0%} of the hub names "
            f"it listed ({n_hub} names)."
        )
    if _unique_max(inst_m, min_gap=1.0) == v:
        return (
            f"{name} scores {ov:.2f} / 10, with the largest captured book count "
            f"({n_inst} instruments)."
        )
    return (
        f"{name} scores {ov:.2f} / 10, with a grid mean of {m['grid']:.2f}, "
        f"wings at {m['wings']:.2f}, and {rate:.0%} two-sided presence on {n_hub} hub names "
        f"({n_inst} instruments)."
    )


def build_executive_summary(card: ScorecardResult) -> str:
    """Plain-language narrative for management. No em dashes."""
    means = component_means(card)
    ranked = sorted(card.overall.items(), key=lambda kv: -kv[1])
    if not ranked:
        return "No venues scored in this sample."
    if len(ranked) < 2:
        leader, lead_s = ranked[0]
        return (
            f"{venue_name(leader)} scores {lead_s:.2f} / 10 on the overall index "
            f"for this sample. Add a second venue to enable head-to-head reading."
        )

    (leader, lead_s), (second, second_s) = ranked[0], ranked[1]
    gap = lead_s - second_s
    paras = [
        f"{venue_name(leader)} leads the overall index at {lead_s:.2f} / 10. "
        f"{venue_name(second)} is next at {second_s:.2f} (gap {gap:.2f}).",
        f"The index is a 0 to 10 book-quality score. It weights the 3×3 liquidity grid at "
        f"{OVERALL_WEIGHTS['grid']:.0%}, far out-of-the-money wings at "
        f"{OVERALL_WEIGHTS['wings']:.0%}, and two-sided quote presence at "
        f"{OVERALL_WEIGHTS['presence']:.0%}.",
    ]
    for v, _ in ranked:
        paras.append(_venue_sentence(v, card, means))
    return "\n\n".join(paras)
