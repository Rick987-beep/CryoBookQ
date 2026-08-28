# CryoBookQ architecture

Parallel **capture** → serial **normalize / match / score** → parquet **lake** → analytics.
v1 is not a plugin framework, message queue, or per-venue process.

## Data models

| Type | Layer | Invariant |
|------|--------|-----------|
| `OptionKey` | identity | `(underlying, expiry_utc_ms, strike, is_call)` |
| `Instrument` | listing | Symbol + key + `raw` (multipliers) |
| `VenueSpec` | units | `price_ccy`, `size_to_btc` |
| `BookL5` | native | Adapter output; px/sz venue-native |
| Normalized row | lake | `RAW_BOOK_COLUMNS`: USD px, BTC sz, generic `venue` |
| `MatchedContract` | join | `key` + `books: dict[str, row \| None]`; hub = Deribit present |
| `ScorecardResult` | analytics | Derived from `raw_books`; not a lake schema |

**Lake contract:** `raw_books` is the comparable dataset. Do not add `deribit_*` /
`bybit_*` columns there. Wide `pair_scores` columns are frozen Deribit↔Coincall legacy.

**Normalize is the only unit conversion.** Adapters must not multiply by index.

## Pipeline

```
per venue (asyncio, wait_for):
  list_instruments → burst_books → BookL5 native

join (no venue I/O):
  normalize → match → scorecard → ParquetStore part-{ts}.parquet
```

`snapshot.py` loops a **registry**. It must not contain exchange URLs.

## Imports

```
types, schemas, config, symbols
    ↑
venues/  (protocol, spec, registry, per-venue adapters)
    ↑
pipeline/  (normalize, match, score, write)  — spec + types, not bybit.py
    ↑
capture/ → daemon / analytics / hub
```

Forbidden: venue adapters importing pipeline; analytics importing a concrete adapter.

**Sixth venue:** `venues/foo.py` + parser + `SPECS["foo"]` + registry + floor env +
live test + HTML label. No edits to match/scorecard/`RAW_BOOK_COLUMNS` except generic
columns (`size_to_btc`).

## Hardening (24h)

| Layer | Mechanism |
|-------|-----------|
| OS | systemd `Restart=on-failure`, `MemoryMax=2G` |
| Slot | Commit boundary before capture; never re-open |
| Venue | `wait_for` + `gather(return_exceptions=True)` + WS `finally` close |
| I/O | REST `timeout=`; no wait-forever loops |
| Lists | Instrument cache, stale-on-failure |
| Clock | Keep last offset if sync fails |
| Disk | Abort threshold; immutable part files |
| Health | `GET /health`; `ok` = hub; gaps only if hub fails |

Self-heal: retry the failed venue on the **next** 15-min slot. Do not blacklist venues.
