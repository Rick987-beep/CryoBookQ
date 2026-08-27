# CryoBookQ scoring — landmark scorecard

Product scorecard for ranking option venues (Deribit, Coincall, …).  
Legacy equal-weight `winner_*` columns remain in `pair_scores` for research; **the report card is this scorecard.**

## Subjects

| Subject | Definition |
|---------|------------|
| **3×3 grid** | Tenors × \|Δ\| targets (below) |
| **Wings** | Same tenors at \|Δ\| ≈ **0.025** |
| **Presence** | Two-sided rate among **matched** options with \|Δ\| ≥ 0.05 |

Only **matched** contracts enter landmark selection.

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

Cell score = mean(spread, size, depth) scores.  
Grid subject = mean of 9 cells. Wings = mean of 3 wing cells.  
Presence = `10 × two_sided_rate`.

**Overall** = `0.60×grid + 0.20×wings + 0.20×presence`.

## Deltas

WS books lack greeks. Snapshot enrichment uses Deribit `get_book_summary_by_currency` + forward BS delta from mark IV (attached to both venues’ matched rows by `OptionKey`).

## Legacy pair metrics

`two_sided`, USD spreads, `cost_buy_1btc` (1 BTC **option** notional walk), win flags — still written to Parquet; not the product rank index.
