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
- Coverage floors (default Deribit ≥90%, Coincall ≥80%) gate parquet writes.
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

## Gaps

Missed boundaries increment `gaps_today`. No L5 backfill (point-in-time only).

## Soak checklist (after approved deploy)

- [ ] `systemctl is-active cryobookq` and `cryobookq-hub`
- [ ] Health: last_ts within 20 min; both venues coverage OK; `clock.offset_s` sane
- [ ] `https://apps.aureas.xyz/bookq/` loads
- [ ] Disk growth ≪ 100 MB/day
