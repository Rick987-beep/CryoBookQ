# CryoBookQ operations

Host: **apps.aureas.xyz** (`91.107.208.208`) — path `/apps/cryobookq`.  
Never confuse with the trading VPS. **Never deploy or wipe `data/` without explicit approval.**

## Units

| Unit | Role | Port |
|------|------|------|
| `cryobookq.service` | Forever snapshot daemon | health **8091** |
| `cryobookq-hub.service` | Flask hub UI | **8088** |

Install both under `/etc/systemd/system/` after approved deploy; enable independently so a hub crash does not stop capture.

```bash
systemctl enable --now cryobookq
systemctl enable --now cryobookq-hub
```

## Health

Daemon embeds ``GET /health`` on ``BOOKQ_HEALTH_PORT`` (default **8091**):

```bash
curl -s http://127.0.0.1:8091/health | python3 -m json.tool
```

Fields: `status`, `last_ts_ms`, `last_ok`, `last_incomplete`, `gaps_today`,
`incomplete_today`, `snapshots_today`, `writes_today`, `day_utc`, `disk_free_mb`,
`clock` (Deribit offset), per-venue coverage in `last_stats`.

Hub (UI) remains on ``BOOKQ_HUB_PORT`` (8088).

## P0 / P1 durability notes

- Each UTC boundary is **committed before capture** — failures never re-open the same slot.
- Coverage floors gate **that venue’s** parquet rows (default Deribit ≥90%; others ≥80%).
  `quality.ok` is true when **Deribit (hub)** met its floor. Other venue failures are
  incomplete, not a daemon gap.
- `BOOKQ_BURST_TIMEOUT_S` (default 40) kills a hung venue burst so peers still finish.
  Peers listen `BOOKQ_WS_COLLECT_S` (default 30). Binance then REST-fills (`BOOKQ_BINANCE_TIMEOUT_S` 90).
- Parquet: ``data/{raw_books,pair_scores}/date=YYYY-MM-DD/part-{ts_ms}.parquet``.
- Disk abort if free &lt; ``BOOKQ_DISK_FREE_ABORT_MB`` (default 500).
- **P1:** Deribit clock sync for boundary opens; instrument list cache (30‑min TTL, stale-on-failure); UTC midnight counter roll; REST off the event loop via ``asyncio.to_thread``.
- Telegram gap alerts: deferred (not in this release).

## Restart / deploy

```bash
systemctl restart cryobookq
systemctl restart cryobookq-hub
./deploy/deploy.sh              # rsync + restart daemon (needs approval for prod)
./deploy/deploy.sh --dry-run
```

## Disk

Warn if free &lt; 5 GB. Archive old Parquet under `data/` monthly if needed.  
**Never delete `data/` without approval.**

## Venues

`--venues deribit,coincall,bybit,okx,binance` (comma-separated). Public MD for
Deribit/Bybit/OKX/Binance; Coincall needs API keys. Do **not** enable all five on
apps until explicitly approved. First production add: Bybit+OKX beside the existing two.
Binance is a 60–90s sampler (`BOOKQ_BINANCE_TIMEOUT_S`); 15-min slots absorb that. Do
not run Binance on a soak cadence shorter than its timeout.

See `docs/VENUES.md` and `docs/ARCHITECTURE.md`.

Missed boundaries increment `gaps_today`. No L5 backfill (point-in-time only).

## Soak checklist (after approved deploy)

- [ ] `systemctl is-active cryobookq` and `cryobookq-hub`
- [ ] Health: last_ts within 20 min; both venues coverage OK; `clock.offset_s` sane
- [ ] `https://apps.aureas.xyz/bookq/` loads
- [ ] Disk growth ≪ 100 MB/day
