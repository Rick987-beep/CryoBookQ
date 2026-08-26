# CryoBookQ

Compare **Deribit** vs **Coincall** BTC option orderbook quality across the full chain
(L5 depth, 15-minute aligned snapshots). Analytics library + small hub; forever daemon
on **apps.aureas.xyz** (not the trading VPS).

## Start here

| Doc | Purpose |
|-----|---------|
| **[docs/SPEC.md](docs/SPEC.md)** | Canonical plan |
| [docs/SCORING.md](docs/SCORING.md) | Metrics, composite weights, buckets |
| [docs/OPS.md](docs/OPS.md) | Ops runbook |
| [AGENTS.md](AGENTS.md) | Agent rules (CODE gate; no deploy without approval) |

**Next:** M6 production deploy on apps — **only with explicit approval**.

## Status

**M0–M5 implemented** (local). M6 deploy artifacts ready; apps deploy gated.

## Local setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,hub]"
cp .env.example .env   # fill COINCALL_* from CryoTrader PROD keys
.venv/bin/python -m pytest tests/unit -v
```

### One-shot dual snapshot + scores

```bash
.venv/bin/python -m cryobookq.daemon --once --venues deribit,coincall --duration 18
# or full report:
.venv/bin/python tools/live_score.py --duration 18
```

### Hub (local)

```bash
.venv/bin/python -m cryobookq.hub.app   # http://127.0.0.1:8088/
```

### Analytics snippet

```python
from cryobookq.analytics import load_scores, who_wins
df = load_scores()
print(who_wins(df, session="US", dte_bucket="0-2").attrs["win_rate"])
```

## Deploy

```bash
./deploy/deploy.sh --dry-run
# production requires explicit approval + BOOKQ_ALLOW_DEPLOY=1
```

See `docs/OPS.md`.
