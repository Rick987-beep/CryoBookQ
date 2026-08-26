"""Composite weights and bucket definitions for pair scoring.

## Per-venue metrics (normalized USD books)

| Metric | Definition |
|--------|------------|
| `two_sided` | Best bid and best ask both > 0 |
| `spread_usd` | ask1 − bid1 |
| `spread_bps` | spread / mid × 10_000 |
| `mid_usd` | (bid1 + ask1) / 2 |
| `depth_btc_L5` | Sum of bid+ask sizes across ≤5 levels |
| `cost_buy_1btc` | VWAP to buy 1 BTC walking asks (null if insufficient size) |
| `cost_sell_1btc` | VWAP to sell 1 BTC walking bids |

## Winners

For each matched pair, lower spread / cost wins; higher depth wins.
`tie` when equal or both null.

## Composite

Within each pair, each component is min-max normalized to [0, 1] (1 = better),
then weighted:

| Component | Weight |
|-----------|--------|
| spread_usd (lower better) | 0.35 |
| cost_buy_1btc (lower better) | 0.25 |
| cost_sell_1btc (lower better) | 0.25 |
| depth_btc_L5 (higher better) | 0.15 |

Missing values score 0 on that component (opponent gets 1 if present).
`winner_composite` is the venue with higher composite (or `tie`).

## Sessions (UTC)

| Session | Hours |
|---------|-------|
| Asia | 00:00–08:00 |
| EU | 08:00–14:00 |
| US | 14:00–21:00 |
| Off | 21:00–24:00 |

## DTE buckets

`0-2`, `3-7`, `8-30`, `31-90`, `90+` (calendar days from snapshot to expiry 08:00 UTC).

## |delta| buckets

`0-0.05`, `0.05-0.15`, `0.15-0.30`, `0.30-0.50`, `0.50+` (when delta enrichment present).
"""
