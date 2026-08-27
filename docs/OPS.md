# CryoBookQ operations

Host: **apps.aureas.xyz** (`91.107.208.208`) — path `/apps/cryobookq`.  
Never confuse with the trading VPS. **Never deploy or wipe `data/` without explicit approval.**

## Health

Daemon embeds ``GET /health`` on ``BOOKQ_HEALTH_PORT`` (default **8091**):

```bash
curl -s http://127.0.0.1:8091/health | python3 -m json.tool
```

Fields: `status`, `last_ts_ms`, `last_ok`, `last_incomplete`, `gaps_today`,
`incomplete_today`, `snapshots_today`, `writes_today`, `disk_free_mb`,
per-venue coverage in `last_stats`.

Hub (optional UI) remains on ``BOOKQ_HUB_PORT`` (8088).

## P0 durability notes

- Each UTC boundary is **committed before capture** — failures never re-open the same slot (no rate-limit tight loop).
- Coverage floors (default Deribit ≥90%, Coincall ≥80%) gate parquet writes; partial peer success may still write.
- Parquet layout: ``data/{raw_books,pair_scores}/date=YYYY-MM-DD/part-{ts_ms}.parquet`` (immutable parts; no full-day rewrite).
- Disk abort if free &lt; ``BOOKQ_DISK_FREE_ABORT_MB`` (default 500).

## Restart / deploy

```bash
systemctl restart cryobookq
./deploy/deploy.sh              # rsync + restart (needs approval for prod)
./deploy/deploy.sh --dry-run
```

## Disk

Warn if free &lt; 5 GB. Archive old Parquet under `data/` monthly if needed.  
**Never delete `data/` without approval.**

## Gaps

Missed boundaries increment `gaps_today`. No L5 backfill (point-in-time only).

## Soak checklist (after approved deploy)

- [ ] `systemctl is-active cryobookq`
- [ ] Health: last_ts within 20 min; both venues coverage OK
- [ ] `https://apps.aureas.xyz/bookq/` loads
- [ ] Disk growth ≪ 100 MB/day
