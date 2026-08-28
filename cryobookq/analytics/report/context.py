"""Build template context from a ``ScorecardResult``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cryobookq.analytics.report import copy as report_copy
from cryobookq.analytics.report.format import (
    SafeHTML,
    esc,
    fmt_depth_k,
    fmt_num,
    fmt_pct,
    now_iso,
    ts_iso,
)
from cryobookq.analytics.report.labels import (
    DELTA_LABELS,
    TENOR_BLURBS,
    TENOR_LABELS,
    VENUE_COLORS,
    venue_name,
)
from cryobookq.analytics.report.narrative import build_executive_summary, component_means
from cryobookq.analytics.scorecard import (
    CATALOGUE_DEPTH_REF_USD,
    CATALOGUE_EXTRAS_MASS_REF,
    CATALOGUE_HUB_N_REF,
    CATALOGUE_WEIGHTS,
    DELTA_TARGETS,
    HUB_VENUE,
    OVERALL_WEIGHTS,
    TENOR_TARGETS,
    WING_LABEL,
    ScorecardResult,
)

_STYLES_PATH = Path(__file__).resolve().parent / "templates" / "styles.css"


def scorecard_from_dict(d: dict[str, Any]) -> ScorecardResult:
    return ScorecardResult(
        ts_ms=int(d["ts_ms"]),
        venues=list(d["venues"]),
        grid=dict(d.get("grid") or {}),
        wings=dict(d.get("wings") or {}),
        presence=dict(d.get("presence") or {}),
        catalogue=dict(d.get("catalogue") or {}),
        overall={k: float(v) for k, v in (d.get("overall") or {}).items()},
        landmarks=list(d.get("landmarks") or []),
        meta=dict(d.get("meta") or {}),
    )


def _period_subtitle(card: ScorecardResult) -> str:
    n_snap = int(card.meta.get("n_snapshots") or 1)
    bits: list[str] = []
    if card.meta.get("aggregated"):
        first = card.meta.get("ts_ms_first")
        last = card.meta.get("ts_ms_last")
        if first and last:
            bits.append(f"{ts_iso(int(first))} → {ts_iso(int(last))}")
        bits.append(f"{n_snap} snapshot{'s' if n_snap != 1 else ''}")
        mm = card.meta.get("n_matched_mean")
        if mm is not None:
            bits.append(f"~{float(mm):.0f} matched contracts / snap")
    else:
        bits.append(ts_iso(card.ts_ms))
        bits.append("single snapshot")

    filt = card.meta.get("filter") or {}
    if filt.get("utc_hour_start") is not None:
        bits.append(f"UTC hours [{filt['utc_hour_start']}, {filt['utc_hour_end']})")
    return " · ".join(bits)


def _overall_cards_html(card: ScorecardResult) -> SafeHTML:
    ranked = sorted(card.overall.items(), key=lambda kv: -kv[1])
    parts: list[str] = []
    for i, (v, score) in enumerate(ranked):
        badge = "Leader" if i == 0 else f"#{i + 1}"
        leader_cls = " leader" if i == 0 else ""
        color = VENUE_COLORS.get(v, "#5c6b7a")
        parts.append(
            f"""<div class="score-card{leader_cls}" data-venue="{esc(v)}" style="border-left:4px solid {esc(color)}">
  <div class="badge">{esc(badge)}</div>
  <div class="venue">{esc(venue_name(v))}</div>
  <div class="big">{esc(fmt_num(score))}<span class="outof"> / 10</span></div>
</div>"""
        )
    return SafeHTML("\n".join(parts))


def _component_rows_html(card: ScorecardResult, means: dict[str, dict[str, float]]) -> SafeHTML:
    rows: list[str] = []
    for v in card.venues:
        m = means[v]
        pv = card.presence["per_venue"][v]
        rows.append(
            "<tr>"
            f"<th>{esc(venue_name(v))}</th>"
            f"<td class='num'>{esc(fmt_num(card.overall[v]))}</td>"
            f"<td class='num'>{esc(fmt_num(m['grid']))}</td>"
            f"<td class='num'>{esc(fmt_num(m['wings']))}</td>"
            f"<td class='num'>{esc(fmt_pct(100 * pv['two_sided_rate']))} → "
            f"{esc(fmt_num(pv['score']))}</td>"
            "</tr>"
        )
    return SafeHTML("\n".join(rows))


def _presence_rows_html(card: ScorecardResult) -> SafeHTML:
    rows: list[str] = []
    for v in card.venues:
        pv = card.presence["per_venue"][v]
        rows.append(
            f"<tr><th>{esc(venue_name(v))}</th>"
            f"<td class='num'>{esc(fmt_pct(100 * pv['two_sided_rate']))}</td>"
            f"<td class='num'>{esc(pv['n_two_sided'])}/{esc(pv['n'])}</td>"
            f"<td class='num'>{esc(fmt_num(pv['score']))}</td></tr>"
        )
    return SafeHTML("\n".join(rows))


def _grid_header_html(card: ScorecardResult) -> SafeHTML:
    return SafeHTML("".join(f"<th colspan='4'>{esc(venue_name(v))}</th>" for v in card.venues))


def _grid_metric_headers_html(card: ScorecardResult) -> SafeHTML:
    return SafeHTML(
        "".join("<th>Spread</th><th>$10k</th><th>Depth</th><th>Score</th>" for _ in card.venues)
    )


def _grid_rows_html(card: ScorecardResult) -> SafeHTML:
    rows: list[str] = []
    for tenor in TENOR_TARGETS:
        for d in DELTA_TARGETS:
            key = f"{tenor}:{d}"
            cell = card.grid.get(key)
            if not cell:
                continue
            label = f"{tenor} {DELTA_LABELS.get(d, d)}"
            tds = [f"<th scope='row'>{esc(label)}</th>"]
            scores = [float(cell["venues"][v]["score"]) for v in card.venues if v in cell["venues"]]
            best = max(scores) if scores else None
            for v in card.venues:
                m = cell["venues"].get(v, {})
                sc = float(m.get("score") or 0)
                cls = (
                    "num best"
                    if best is not None and abs(sc - best) < 1e-9 and len(scores) > 1
                    else "num"
                )
                tds.append(f"<td class='{cls}'>{esc(fmt_pct(m.get('spread_pct')))}</td>")
                tds.append(f"<td class='{cls}'>{esc(fmt_pct(m.get('lift_effective_pct')))}</td>")
                tds.append(f"<td class='{cls}'>{esc(fmt_depth_k(m.get('depth_usd')))}</td>")
                tds.append(f"<td class='{cls} score'>{esc(fmt_num(sc, 1))}</td>")
            rows.append("<tr>" + "".join(tds) + "</tr>")
    return SafeHTML("\n".join(rows))


def _wing_venue_headers_html(card: ScorecardResult) -> SafeHTML:
    return SafeHTML("".join(f"<th>{esc(venue_name(v))}</th>" for v in card.venues))


def _wing_rows_html(card: ScorecardResult) -> SafeHTML:
    rows: list[str] = []
    totals: dict[str, float] = {}
    spreads: dict[str, list[float | None]] = {v: [] for v in card.venues}
    for tenor in TENOR_TARGETS:
        key = f"{tenor}:{WING_LABEL}"
        cell = card.wings.get(key)
        if not cell:
            continue
        tds = [f"<th scope='row'>{esc(TENOR_LABELS.get(tenor, tenor))} 2.5Δ</th>"]
        scores: list[float] = []
        for v in card.venues:
            m = cell["venues"].get(v, {})
            sc = float(m.get("score") or 0)
            scores.append(sc)
            totals[v] = totals.get(v, 0.0) + sc
            spreads[v].append(m.get("spread_pct"))
            tds.append(
                f"<td class='num'>{esc(fmt_num(sc, 1))} "
                f"<span class='muted'>(spr {esc(fmt_pct(m.get('spread_pct')))})</span></td>"
            )
        rows.append("<tr>" + "".join(tds) + "</tr>")
    n_tenor = max(1, sum(1 for t in TENOR_TARGETS if f"{t}:{WING_LABEL}" in card.wings))
    means = {v: totals.get(v, 0.0) / n_tenor for v in card.venues}
    best = max(means.values()) if means else None
    tds = ["<th scope='row'>Total</th>"]
    for v in card.venues:
        sc = means.get(v, 0.0)
        cls = (
            "num best score"
            if best is not None and abs(sc - best) < 1e-9 and len(means) > 1
            else "num score"
        )
        spr = _mean_maybe(spreads.get(v) or [])
        tds.append(
            f"<td class='{cls}'>{esc(fmt_num(sc, 1))} "
            f"<span class='muted'>(spr {esc(fmt_pct(spr))})</span></td>"
        )
    rows.append("<tr class='total'>" + "".join(tds) + "</tr>")
    return SafeHTML("\n".join(rows))


def _mean_maybe(xs: list[float | None]) -> float | None:
    vals = [float(x) for x in xs if x is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _catalogue_rows_html(card: ScorecardResult) -> SafeHTML:
    per = (card.catalogue or {}).get("per_venue") or {}
    if not per:
        return SafeHTML("")
    scores = [float(per[v]["score"]) for v in card.venues if v in per]
    best = max(scores) if scores else None
    rows: list[str] = []
    for v in card.venues:
        pv = per.get(v)
        if not pv:
            continue
        sc = float(pv.get("score") or 0)
        cls = (
            "num best score"
            if best is not None and abs(sc - best) < 1e-9 and len(scores) > 1
            else "num score"
        )
        n_inst = int(pv.get("n_instruments") or 0)
        n_hub = int(pv.get("n_hub_two_sided") or 0)
        n_ex = int(pv.get("n_extras") or 0)
        extras_cell = (
            "n/a"
            if v == HUB_VENUE
            else (
                f"{esc(fmt_num(pv.get('extras_score')))} "
                f"<span class='muted'>({n_ex} names)</span>"
            )
        )
        rows.append(
            "<tr>"
            f"<th>{esc(venue_name(v))}</th>"
            f"<td class='num muted'>{n_inst}</td>"
            f"<td class='num'>{esc(fmt_num(pv.get('hub_coverage_score')))} "
            f"<span class='muted'>({n_hub} two-sided)</span></td>"
            f"<td class='num'>{extras_cell}</td>"
            f"<td class='{cls}'>{esc(fmt_num(sc))}</td>"
            "</tr>"
        )
    return SafeHTML("\n".join(rows))


def _tenor_dl_html() -> SafeHTML:
    parts = [
        f"<dt>{esc(TENOR_LABELS[t])}</dt><dd>{esc(TENOR_BLURBS[t])} "
        f"Targets: {', '.join(str(int(x)) for x in TENOR_TARGETS[t])} DTE.</dd>"
        for t in TENOR_TARGETS
    ]
    return SafeHTML("".join(parts))


def _capture_rows_html(card: ScorecardResult) -> SafeHTML:
    cap = card.meta.get("capture") or {}
    if not cap:
        return SafeHTML(
            "<tr><td colspan='5' class='muted'>No capture metadata for this report.</td></tr>"
        )
    rows: list[str] = []
    for v in card.venues:
        st = cap.get(v)
        if not st:
            if v in {"binance"}:
                rows.append(
                    f"<tr><td>{esc(venue_name(v))}</td>"
                    f"<td colspan='4' class='muted'>No books captured in this window.</td></tr>"
                )
            continue
        cov = st.get("coverage_mean", st.get("coverage"))
        cov_s = esc(fmt_pct(100 * float(cov))) if cov is not None else "n/a"
        n_inst = st.get("n_instruments")
        n_up = st.get("n_with_update")
        books_s = f"{n_up}/{n_inst}" if n_inst is not None else "n/a"
        if n_up is None and n_inst is not None and cov is not None and n_inst:
            books_s = f"{int(round(float(cov) * n_inst))}/{n_inst}"
        dur = st.get("duration_s_mean", st.get("duration_s"))
        dur_s = f"{float(dur):.1f}s" if dur is not None else "n/a"
        flags = st.get("flags") or []
        note_s = esc("; ".join(flags[:6])) if flags else "—"
        rows.append(
            f"<tr data-venue='{esc(v)}'>"
            f"<td>{esc(venue_name(v))}</td>"
            f"<td class='num'>{cov_s}</td>"
            f"<td class='num'>{esc(books_s)}</td>"
            f"<td class='num'>{esc(dur_s)}</td>"
            f"<td class='note'>{note_s}</td>"
            "</tr>"
        )
    return SafeHTML("\n".join(rows) if rows else "<tr><td colspan='5'>—</td></tr>")


def _methodology_dl_html() -> SafeHTML:
    items = report_copy.section("methodology")["items"]
    parts = [f"<dt>{esc(it['term'])}</dt><dd>{esc(it['definition'])}</dd>" for it in items]
    return SafeHTML("\n".join(parts))


def _safe_copy_html(text: str, **fmt: object) -> SafeHTML:
    """Format copy that may contain intentional HTML tags."""
    return SafeHTML(text.format(**fmt))


def build_report_context(
    card: ScorecardResult,
    *,
    title: str = "Comparison Scorecard",
    subtitle: str | None = None,
    executive_summary: str | None = None,
) -> dict[str, Any]:
    """Assemble the dict consumed by ``scorecard.html``."""
    means = component_means(card)
    summary_text = executive_summary or build_executive_summary(card)
    summary_html = SafeHTML(
        "".join(f"<p>{esc(p.strip())}</p>" for p in summary_text.split("\n\n") if p.strip())
    )
    meta = report_copy.meta()
    sec_overall = report_copy.section("overall")
    sec_components = report_copy.section("components")
    sec_executive = report_copy.section("executive")
    sec_presence = report_copy.section("presence")
    sec_grid = report_copy.section("grid")
    sec_wings = report_copy.section("wings")
    sec_catalogue = report_copy.section("catalogue")
    sec_capture = report_copy.section("capture")
    sec_methodology = report_copy.section("methodology")
    generated = now_iso()
    weights = {
        "grid_pct": f"{OVERALL_WEIGHTS['grid']:.0%}",
        "wings_pct": f"{OVERALL_WEIGHTS['wings']:.0%}",
        "presence_pct": f"{OVERALL_WEIGHTS['presence']:.0%}",
    }

    return {
        "title": title,
        "subtitle": subtitle or _period_subtitle(card),
        "venue_list": " vs ".join(venue_name(v) for v in card.venues),
        "eyebrow": meta["eyebrow"],
        "footer": meta["footer"].format(generated=generated),
        "generated": generated,
        "styles": SafeHTML(_STYLES_PATH.read_text(encoding="utf-8")),
        "headings": {
            "overall": sec_overall["heading"],
            "components": sec_components["heading"],
            "executive": sec_executive["heading"],
            "presence": sec_presence["heading"],
            "grid": sec_grid["heading"],
            "wings": sec_wings["heading"],
            "catalogue": sec_catalogue["heading"],
            "capture": sec_capture["heading"],
            "methodology": sec_methodology["heading"],
        },
        "explain": {
            "overall": _safe_copy_html(sec_overall["explain"]),
            "components": _safe_copy_html(sec_components["explain"], **weights),
            "presence": _safe_copy_html(sec_presence["explain"]),
            "grid": _safe_copy_html(sec_grid["explain"]),
            "grid_delta": _safe_copy_html(sec_grid["delta_note"]),
            "wings": _safe_copy_html(sec_wings["explain"]),
            "catalogue": _safe_copy_html(
                sec_catalogue["explain"],
                n_ref=CATALOGUE_HUB_N_REF,
                depth_ref=CATALOGUE_DEPTH_REF_USD,
                mass_ref=CATALOGUE_EXTRAS_MASS_REF,
                hub_pct=f"{CATALOGUE_WEIGHTS['hub_coverage']:.0%}",
                extras_pct=f"{CATALOGUE_WEIGHTS['extras']:.0%}",
            ),
            "capture": _safe_copy_html(sec_capture["explain"]),
        },
        "executive_summary": summary_html,
        "overall_cards": _overall_cards_html(card),
        "component_rows": _component_rows_html(card, means),
        "presence_rows": _presence_rows_html(card),
        "grid_venue_headers": _grid_header_html(card),
        "grid_metric_headers": _grid_metric_headers_html(card),
        "grid_rows": _grid_rows_html(card),
        "tenor_dl": _tenor_dl_html(),
        "wing_venue_headers": _wing_venue_headers_html(card),
        "wing_rows": _wing_rows_html(card),
        "catalogue_rows": _catalogue_rows_html(card),
        "capture_rows": _capture_rows_html(card),
        "methodology_dl": _methodology_dl_html(),
    }
