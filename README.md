# CryoBookQ

Compare **Deribit** vs **Coincall** BTC option orderbook quality across the full chain
(L5 depth, 15-minute aligned snapshots). Analytics library + small hub; forever daemon
on **apps.aureas.xyz** (not the trading VPS).

## Start here

| Doc | Purpose |
|-----|---------|
| **[docs/SPEC.md](docs/SPEC.md)** | **Canonical plan** — target state, deploy/ops, milestones M0–M6, tests |
| [AGENTS.md](AGENTS.md) | Rules for AI agents (CODE gate, no deploy without approval) |

**Next implementation step:** milestone **M2** (Deribit collector + raw Parquet). Say **CODE**.

## Status

**M0 + M1 done** (2026-08-26):

- Venue WS bursts feasible: dual full-chain ~956 instruments, **100% coverage** each side in ~18s
- Coincall options WS **requires signed URL** (creds in `.env`)
- Deribit interval books accept depth **1/10/20** only — we subscribe **10** and store top **5**
- Package skeleton: `Venue` Protocol, `OptionKey`/`BookL5`, symbol converters, config

## Layout

```
cryobookq/     # Python package
docs/SPEC.md   # full design + implementation plan
tests/         # unit / fixtures / live (opt-in)
tools/         # spike scripts (M0)
deploy/        # systemd + deploy.sh (M5+)
```

## Local setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # fill COINCALL_* from CryoTrader PROD keys
.venv/bin/python -m pytest tests/unit -v
```

Live / spikes:

```bash
.venv/bin/python tools/spike_dual.py --duration 18
.venv/bin/python tools/capture_fixture.py --from-tmp
.venv/bin/python -m pytest tests/live -m live -v
```

## Credentials

Secrets live in `.env` (gitignored). See `.env.example`. Do not commit keys.
Coincall read-only keys are required for options WebSocket (confirmed in M0).

## Deploy

Target: `/apps/cryobookq` on `apps.aureas.xyz`. **Never deploy without explicit approval.**
See `docs/SPEC.md` § Deployment & maintenance.
