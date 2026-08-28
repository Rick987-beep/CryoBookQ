# CryoBookQ scoring — landmark scorecard

Product scorecard for ranking option venues (Deribit, Coincall, …).  
Legacy equal-weight `winner_*` columns remain in `pair_scores` for research; **the report card is this scorecard.**

## Subjects

| Subject | Definition |
|---------|------------|
| **3×3 grid** | Tenors × \|Δ\| targets (below) |
| **Wings** | Same tenors at \|Δ\| ≈ **0.025** |
| **Presence** | Two-sided rate among **hub (Deribit-listed)** options this venue also listed, with \|Δ\| ≥ 0.05 |

Only **hub** contracts (Deribit listed this snapshot) enter landmark selection.
Other venues are looked up independently. Missing book → that venue’s cell is 0;
peers are unchanged. Never require an N-way intersection.

USD: prices are USD premium per 1 BTC of option; depth and $10k lift use
**premium notional** `px_usd × sz_btc` after `size_to_btc` (see `docs/VENUES.md`).

### Tenors (nearest listed expiry per target, then average)

| Label | Targets (DTE) | Max gap to listed |
|-------|---------------|-------------------|
| short | 1, 2 | 1.5d |
| mid | 7, 14, 21 | 4d |
| far | 60, 90, 120 | 15d |

### Delta targets

| Label | \|Δ\| |
|-------|------|
| 50d | 0.50 |
| 25d | 0.25 |
| 7p5d | 0.075 |
| 2p5d (wings) | 0.025 |

Per (expiry, \|Δ\|): pick **nearest call** and **nearest put** (max \|Δ\| gap 0.10), score each, **average**.

## Per-contract metrics (USD books)

| Metric | Definition |
|--------|------------|
| `spread_pct` | \((ask1-bid1)/mid × 100\) — requires two-sided |
| `$10k lift` | Walk asks until **$10 000 premium** notional; report VWAP and \((VWAP-mid)/mid × 100\) |
| `depth_usd` | Σ (px × sz) over L5 bids+asks |

One-sided or missing landmark → metrics null, component score **0**.

## 0–10 scores (absolute refs — multi-venue safe)

Lower-better (spread / lift %): `10 × clamp(1 − value/ref, 0, 1)`  
Higher-better (depth $): `10 × clamp(value/ref, 0, 1)`

| Δ label | spread ref % | $10k eff ref % | depth ref $ |
|---------|--------------|----------------|-------------|
| 50d | 8 | 4 | 80 000 |
| 25d | 15 | 8 | 40 000 |
| 7p5d | 40 | 20 | 15 000 |
| 2p5d | 80 | 40 | 5 000 |

Cell score = ``0.65×spread + 0.25×$10k_lift + 0.10×depth`` (small tickets → spread first).  
Grid component = mean of 9 cells. Wings = mean of 3 wing cells.  
Presence = `10 × two_sided_rate`.

**Overall** = `0.60×grid + 0.20×wings + 0.20×presence`.

## Deltas

WS books lack greeks. Snapshot enrichment uses Deribit `get_book_summary_by_currency` + forward BS delta from mark IV (attached to both venues’ matched rows by `OptionKey`).

## Multi-snapshot / time windows

Scorecards for a period are built from **`raw_books`** Parquet (needs L5 + delta),
not from `pair_scores` alone:

1. Load parts (optionally filter by date / `ts` range / UTC hour window).
2. Build one scorecard per distinct snapshot `ts`.
3. **Equal-weight average** metrics and 0–10 scores across those snapshots.

```bash
# Offline period report
.venv/bin/python tools/scorecard_period.py --data-dir ./data --hours 12:18

# Comparison Scorecard HTML (shareable)
.venv/bin/python tools/scorecard_html.py --data-dir ./data --out reports/scorecard.html

# After soak (auto): tools/soak_interval.py writes scorecard_period.json
```

`--hours START:END` is `[START, END)` UTC (e.g. `12:18` = 12:00–17:59). Wrap-around
windows like `22:6` are supported.

## HTML report

`cryobookq.analytics.report` (shim: `html_report`) renders a self-contained
**Comparison Scorecard** — suitable for exchange counterparties.

### Module map (extendable)

| Path | Role |
|------|------|
| [`cryobookq/analytics/report/copy.toml`](../cryobookq/analytics/report/copy.toml) | Locked section headings + explain/methodology prose |
| [`templates/scorecard.html`](../cryobookq/analytics/report/templates/scorecard.html) | Page shell; `{% include %}` section snippets |
| [`templates/snippets/`](../cryobookq/analytics/report/templates/snippets/) | One HTML snippet per section (hero, overall, …) |
| [`templates/styles.css`](../cryobookq/analytics/report/templates/styles.css) | Layout / chrome (inlined at render) |
| `context.py` | `ScorecardResult` → template variables (tables as SafeHTML) |
| `narrative.py` | Executive Summary text |
| `engine.py` | Tiny `{{ var }}` + `{% include %}` renderer (no Jinja dep) |

Add a section: new snippet + one include line in `scorecard.html` + copy keys +
context fields. Swap wording: edit `copy.toml` only. Keep public imports via
`cryobookq.analytics.html_report`.

### Report wording (locked)

Use these labels in all future scorecard HTML / narrative copy:

| UI label | Notes |
|----------|--------|
| **Comparison Scorecard** | Document title / H1 (not “BTC Option Book Quality Scorecard”) |
| **Executive Summary** | Narrative section (not “Executive reading”) |
| **Component summary** | Weighted blend section (not “Subject summary”) |
| **components** | Grid, wings, presence are **components** of the overall index |

Prefer **components** over “subjects”, “aspects”, or “categories”: in composite-score /
index construction, “components” is the usual financial term for weighted parts of an
aggregate.
