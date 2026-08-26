# CryoBookQ

Compare **Deribit** vs **Coincall** BTC option orderbook quality across the full chain
(L5 depth, 15-minute aligned snapshots). Analytics library + small hub; forever daemon
on **apps.aureas.xyz** (not the trading VPS).

## Start here

| Doc | Purpose |
|-----|---------|
| **[docs/SPEC.md](docs/SPEC.md)** | **Canonical plan** — target state, deploy/ops, milestones M0–M6, tests |
| [AGENTS.md](AGENTS.md) | Rules for AI agents (CODE gate, no deploy without approval) |
| `.cursor/plans/exchange_book_comparer.plan.md` | Same plan (Cursor plans UI) |

**Next implementation step:** milestone **M0** (venue WS spikes + fixtures) in `docs/SPEC.md`.

## Status

Repo bootstrap only. Collectors, scoring, hub, and apps deploy are not implemented yet.

## Layout

```
cryobookq/     # Python package (empty stubs)
docs/SPEC.md   # full design + implementation plan
tests/         # unit / fixtures / live (opt-in)
tools/         # spike scripts (M0)
deploy/        # systemd + deploy.sh (M5+)
```

## Local setup (later)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
cp servers.toml.example servers.toml   # fill apps host if deploying
.venv/bin/python -m pytest tests/unit -v
```

Live tests (after M0+): `.venv/bin/python -m pytest tests/live -m live -v`

## Credentials

Secrets live in `.env` (gitignored). See `.env.example`. Do not commit keys.
Coincall read-only keys may be needed for options WebSocket (confirmed in M0).

## Deploy

Target: `/apps/cryobookq` on `apps.aureas.xyz`. **Never deploy without explicit approval.**
See `docs/SPEC.md` § Deployment & maintenance.
