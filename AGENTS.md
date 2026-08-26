# CryoBookQ — Agent instructions

Canonical product + implementation plan: **[docs/SPEC.md](docs/SPEC.md)**  
(Cursor copy: `.cursor/plans/exchange_book_comparer.plan.md`)

This repo is the **orderbook quality comparer** only. Live trading is CryoTrader; backtests are CryoBacktester. Do not import CryoTrader as a package — copy patterns if needed.

---

## Hard rules — NON-NEGOTIABLE

### 1. Plan first — code only on "CODE"

- Do not invent large new scope beyond the current milestone in `docs/SPEC.md`.
- For non-trivial work outside the open milestone, present a short plan and wait for **"CODE"** (exact word).
- "Go ahead" / "yes" do **not** authorize coding.

### 2. No apps deploy without explicit approval

- Never run `deploy/deploy.sh` against **apps.aureas.xyz** / `91.107.208.208` unless the user explicitly allows production deploy.
- Never wipe `/apps/cryobookq/data/` without approval.
- Read-only SSH health checks are OK when requested.

### 3. Never commit secrets

- `.env`, `servers.toml` (with real IPs if sensitive), API keys — never commit.
- Use `.env.example` / `servers.toml.example` only.

### Also

- Never commit unless the user asks.
- Prefer milestone order **M0 → M6** in `docs/SPEC.md`; stop at milestone boundaries for review unless told to continue.

---

## Hosts (do not confuse)

| Role | Where |
|------|--------|
| CryoBookQ forever daemon | **apps.aureas.xyz** → `/apps/cryobookq` |
| CryoTrader slots / tick recorder | Trading VPS `/opt/ct` — **out of scope** |

---

## Testing

```bash
.venv/bin/python -m pytest tests/unit -v          # default
.venv/bin/python -m pytest tests/live -m live -v  # opt-in; needs network / .env
```

Live tests: public market data only — **never place orders**.

---

## Code style

- Python 3.12 — `X | None`, `list[X]`
- `logger = logging.getLogger(__name__)`
- Env params: `BOOKQ_*` (see `.env.example`)
