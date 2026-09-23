# Bullish BTC options venue

## Brief

Add bullish.com to the CryoBookQ comparison the same way as the other venues: public BTC option chain, L5 books, USD premium, BTC size, exact `OptionKey` match to the Deribit hub, and the same scorecard statistics (overall, 3×3 grid, wings, presence) beside the existing exchanges.

Probe findings locked into this design (live, 2026-09-23):

- 1,546 enabled BTC-USDC options. Symbol `BTC-USDC-YYYYMMDD-STRIKE-C|P`. Expiry `08:00:00.000Z`. No ETH options.
- Premium is USDC (treat as USD). Quantity is BTC. `contractMultiplier` is 1. Tick is 10 USDC.
- One public WebSocket (`l2Orderbook`) returned a snapshot for every listed symbol in about 15 seconds. Messages are full-book replacements, including empties. `publishedAtTimestamp` is fresh; engine `timestamp` on empty books can be weeks old.
- REST hybrid books use a different JSON shape and lag. WebSocket is the capture path.
- `marketType=OPTION` works. `optionType`, `underlyingBaseSymbol`, and `_pageSize` do not. Filter BTC on the client.
- Dated futures are `BTC-USDC-YYYYMMDD` with no strike. They must not parse as options.
- Quoted books are usually 1–3 levels, and quotes can flicker empty for a few seconds. Last snapshot wins. Coverage counts a received snapshot, including an empty book.
- About half of hub-overlapping names were two-sided at probe time. That is the market, not a capture failure. Presence will reflect it.
- Ladder mark/Greeks are not the book and not the comparison index. Landmarks keep using Deribit delta.

## Overall acceptance test

full read of all options necessary to have a full statistics set on bullish.com next to the other exchanges.

**Status:** [ ] not started  
**Evidence:** (fill when live)

## Architecture

Sixth venue, same pipeline as Bybit/OKX/Binance. No change to match, score weights, or `RAW_BOOK_COLUMNS`.

```
GET /v1/markets?marketType=OPTION
        → filter underlyingBaseSymbol=BTC, marketEnabled
        → parse symbol → Instrument

wss://api.exchange.bullish.com/trading-api/v1/market-data/orderbook
        → subscribe l2Orderbook per symbol (one socket)
        → each type=snapshot replaces that symbol's book
        → truncate to L5, ts = publishedAtTimestamp
        → drop the socket

normalize (USD px, BTC sz, size_to_btc=1)
        → match OptionKey to Deribit
        → scorecard column "bullish"
```

Daemon default stays `deribit,coincall`. Bullish is opt-in via `--venues` until a soak, same as the first Binance enable. The acceptance run passes the venue list explicitly.

Public market data only. No API key. No orders.

## Models

| Piece | Choice |
|-------|--------|
| Venue name | `bullish` |
| `VenueSpec` | `price_ccy=USD`, `size_to_btc=1.0` |
| `OptionKey` | From the symbol date at 08:00 UTC, strike, `C`/`P`. Underlying `BTC`. |
| Book time | `publishedAtTimestamp` (fallback: engine `timestamp`) |
| Book state | Replace on `snapshot`. A rare `update` applies absolute sizes (qty 0 deletes) and does not drop levels the message omits. |
| Empty flicker | Stored as an empty L5. Last frame in the window is the row. |
| Fee pin | Individual CLOB options: taker 3 bp of underlying, cap 10% of premium (`taker_rate=0.0003`, `premium_cap=0.10`). |
| Coverage floor | 0.80 (`BOOKQ_COVERAGE_FLOOR_BULLISH`), same peer default. |

## Data structures

Native `BookL5` like every other adapter. WebSocket bids/asks are flat `[price, qty, …]` strings. REST is not used for the burst.

`OptionKey` equality with Deribit requires the same expiry millisecond (08:00 UTC), strike, and call/put. Non-round strikes such as `32704` parse as that number and simply fail to match the hub.

## Phases

### Phase 1 — Symbol parser and unit spec

**Status:** done

**Build:** `parse_bullish_symbol` for `BTC-USDC-YYYYMMDD-STRIKE-C|P`. Wire it into `option_expiry_utc` and `option_key_from_symbol`. Reject dated futures (`BTC-USDC-YYYYMMDD`). Add `SPECS["bullish"]`.

**Tests:** `pytest tests/unit/test_symbols.py tests/unit/test_venue_spec.py -q`

**Acceptance:** A Bullish symbol and the Deribit symbol for the same 08:00 UTC expiry, strike, and call produce the same `OptionKey`. A dated future does not parse. `spec_for("bullish")` is USD / 1.0.

| Step | Status |
|------|--------|
| 1 Read plan | [x] |
| 2 Implement | [x] |
| 3 Test (+ live if required) | [x] |
| 4 Review | [x] |
| 5 Document | [x] |
| 6 Git (commit + push) | [x] |

**Live evidence:** not a live phase. Unit: `pytest tests/unit/test_symbols.py tests/unit/test_venue_spec.py -q` → 14 passed. Review: no findings.

### Phase 2 — Full-chain book read

**Status:** done

**Build:** `cryobookq/venues/bullish.py`. `list_instruments` from `GET /trading-api/v1/markets?marketType=OPTION`, client-filtered to enabled BTC options. `burst_books` subscribes `l2Orderbook` for every symbol on one socket, replaces on snapshot, pads to L5, stamps `publishedAtTimestamp`. Register nothing yet (phase 3). Unit-test the message parser with captured frames, including an empty snapshot that clears a previous book.

**Tests:** `pytest tests/unit/test_bullish.py -q` and `pytest tests/live/test_bullish_burst.py -m live -o addopts= -v`

**Acceptance:** Live list returns every enabled BTC option (at least 1,000). A live burst of that full symbol list reaches coverage ≥ 0.90 inside 30 seconds, includes at least one two-sided book, and that book’s prices sit on a 10 USDC tick with a publish time within 5 minutes of now.

| Step | Status |
|------|--------|
| 1 Read plan | [x] |
| 2 Implement | [x] |
| 3 Test (+ live if required) | [x] |
| 4 Review | [x] |
| 5 Document | [x] |
| 6 Git (commit + push) | [x] |

**Live evidence:** `pytest tests/live/test_bullish_burst.py -m live -o addopts= -v` PASSED in 32.43s against `https://api.exchange.bullish.com/trading-api` (markets list + `wss://.../market-data/orderbook` `l2Orderbook`). Asserted ≥1000 BTC options, ETH list empty, coverage ≥ 0.90, collect window 30s (elapsed ≤ 40s), two-sided book, 10 USDC tick, `publishedAtTimestamp` within 5 minutes. Unit: 7 passed. Review fix: ignore an `update` that arrives before the first snapshot.

### Phase 3 — Statistics column beside the other venues

**Status:** done

**Build:** Registry, `KNOWN`, coverage floor env, fee pin, hub/report labels and color, `PREFERRED_VENUES`. Snapshot loop already scores whatever the registry returns; no score formula edits. Docs: `docs/VENUES.md`, README venue count, `.env.example`, `CHANGELOG.md`.

**Tests:** `pytest tests/unit -q` (scorecard, fees, config, registry). A fixture raw-book set that includes Bullish must show Bullish on overall, every grid cell, wings, and presence next to Deribit.

**Acceptance:** Unit scorecard built from fixture books lists `bullish` beside `deribit` with a numeric overall, a 3×3 grid entry, a wings entry, and a presence score. `make_venue("bullish")` constructs the adapter.

| Step | Status |
|------|--------|
| 1 Read plan | [x] |
| 2 Implement | [x] |
| 3 Test (+ live if required) | [x] |
| 4 Review | [x] |
| 5 Document | [x] |
| 6 Git (commit + push) | [x] |

**Live evidence:** not a live phase. `pytest tests/unit -q` → 124 passed, then scorecard/fees/config/bullish re-run → 37 passed after the review fix. Review: Bullish is not forced onto the scorecard when it was not captured.

### Phase 4 — Live statistics set

**Status:** not started

**Build:** Only fixes this phase’s live run exposes. No new product surface.

**Tests:** `pytest tests/unit -q` then the live command below.

**Acceptance:** One live `python -m cryobookq.daemon --once` over `deribit,bybit,okx,binance,bullish` (plus `coincall` when credentials are present) writes `raw_books` that contain `venue=bullish`. The scorecard built from that snapshot has Bullish on overall, the 3×3 grid, wings, and presence, and the same blocks are present for Deribit, Bybit, OKX, and Binance. Open the rendered scorecard HTML and confirm the Bullish column is visible beside those venues.

| Step | Status |
|------|--------|
| 1 Read plan | [ ] |
| 2 Implement | [ ] |
| 3 Test (+ live if required) | [ ] |
| 4 Review | [ ] |
| 5 Document | [ ] |
| 6 Git (commit + push) | [ ] |

**Live evidence:**
