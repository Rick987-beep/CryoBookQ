# Contributing to CryoBookQ

Thank you for your interest in CryoBookQ. This project compares public option orderbook data for research — contributions that improve correctness, clarity, or test coverage are welcome.

## Before you start

1. Read [docs/SPEC.md](docs/SPEC.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design constraints.
2. Read [AGENTS.md](AGENTS.md) if you use coding agents — large scope changes need an explicit **CODE** approval in maintainer workflows.
3. **Never commit secrets** (`.env`, `servers.toml` with real credentials, API keys).

## Development setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,hub]"
cp .env.example .env
pytest tests/unit -v
```

## Pull requests

1. Fork and create a feature branch from `main`.
2. Keep changes focused — one logical change per PR when possible.
3. Add or update tests for behavior you change.
4. Run `pytest tests/unit -v` and `ruff check .` before opening the PR.
5. Update docs if you change scoring, venues, config env vars, or ops behavior.

## Live tests

Live tests hit **public market data only** and must never place orders:

```bash
pytest tests/live -m live -o addopts= -v
```

Mark new network tests with `@pytest.mark.live`.

## Code style

- Python 3.12 — use `X | None`, `list[X]`.
- `logger = logging.getLogger(__name__)`.
- Config via `BOOKQ_*` env vars; document new vars in `.env.example`.
- Venue-specific logic stays in `cryobookq/venues/`; pipeline code stays venue-agnostic.

## Deploy

Do **not** run production deploy scripts against apps.aureas.xyz without explicit maintainer approval. See [docs/OPS.md](docs/OPS.md).

## Questions

Open a [GitHub issue](https://github.com/Rick987-beep/CryoBookQ/issues) for bugs or design questions.
