# CryoBookQ venues — chosen markets and units

BTC option books only. For each exchange, capture the **dominant liquid** product
line, not every listed variant.

## Chosen markets

| Venue | Product chosen | Rejected | Notes |
|-------|----------------|----------|-------|
| Deribit | Coin-margined BTC (`currency=BTC`) | `BTC_USDC-*` | Hub for listing + Δ |
| Coincall | USD premium | — | Existing |
| Bybit | USDT European (`settleCoin=USDT`) | Coin-inverse (not listed as a separate liquid chain) | Strike is in the symbol |
| Binance | USDT eapi (`underlying=BTCUSDT`) | Inverse | WS on **fstream**, not nbstream |
| OKX | `instFamily=BTC-USD` inverse | `BTC-USD_UM` linear | `sz` is contracts; × `ctVal×ctMult` |

All chosen markets expire **08:00 UTC**. Match on `OptionKey(underlying, expiry_utc_ms, strike, is_call)`.

**Deribit is the listing hub.** Landmarks and Δ come from Deribit. Other venues are
looked up independently. Never require an N-way intersection.

## USD formulas

Adapters emit **native** prices and sizes. Conversion happens only in `normalize_book`.

```
sz_btc = qty_native × size_to_btc
px_usd = px_native × index     if price_ccy == BTC
px_usd = px_native             if price_ccy == USD    # USDT = USD 1:1
level_usd = px_usd × sz_btc    # comparable volume = USD premium notional
```

| Venue | `price_ccy` | `size_to_btc` |
|-------|-------------|---------------|
| Deribit | BTC | 1.0 |
| Coincall | USD | 1.0 |
| Bybit | USD | 1.0 |
| Binance | USD | 1.0 |
| OKX | BTC | `ctVal × ctMult` (live default **0.01**) |

Parquet stores USD prices and BTC sizes (after multiplier). Scoring uses `level_usd`.
Do not store size as dollars of BTC underlying (`sz_btc × index`).

## Capture (summary)

| Venue | Primary | Notes |
|-------|---------|--------|
| Deribit | WS `book.*.none.10.100ms` truncated to L5 | Interval snapshots. Full chain by ~10s. |
| Coincall | WS `orderBook` batches of 100 | Signed URL. Full chain by ~10s. |
| Bybit | WS `orderbook.25.{symbol}` snapshot+delta | Public. Full chain by ~10s. Apply deltas (not first snapshot only). |
| OKX | WS `books5` | Public. Snapshot every 100ms when changed. Full chain by ~10s. |
| Binance | Slow sampler: 4 WS connections × ≤200 streams, SUBSCRIBE paced at 5 msg/s, listen ~30s with peers; REST depth for silent names (~2.5 req/s wall, stop before used-weight 400/min); ticker TOB last resort | `nbstream` is 404; use `fstream`. Depth streams are update-driven (quiet wings send nothing). Live `REQUEST_WEIGHT` is **400/min**, depth weight 2. `wait_for` for Binance is 90s; other venues `BOOKQ_BURST_TIMEOUT_S` (~55s). Ticker fills have epsilon size (spread/presence, not real L5). First apps enable: Deribit+Coincall+Bybit+OKX until a soak proves ≥80% coverage. |

Isolation: per-venue `asyncio.wait_for`; a hang/error skips that venue for the slot.
`quality.ok` = Deribit (hub) met its coverage floor. Peer misses set `quality.incomplete`
and increment health `incomplete_today` without counting a daemon gap.

Coincall/Deribit teardown drops the WebSocket after collect (no batch unsubscribe) so a
slow close handshake cannot cancel a burst that already reached full coverage.

See [ARCHITECTURE.md](ARCHITECTURE.md) for models, imports, and 24h hardening.
