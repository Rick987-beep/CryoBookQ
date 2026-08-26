# CryoBookQ operations

Host: **apps.aureas.xyz** (`91.107.208.208`) — path `/apps/cryobookq`.  
Never confuse with the trading VPS. **Never deploy or wipe `data/` without explicit approval.**

## Health

```bash
curl -s http://127.0.0.1:8088/health   # on server (hub)
journalctl -u cryobookq -f
./deploy/deploy.sh --status
./deploy/deploy.sh --logs
```

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
