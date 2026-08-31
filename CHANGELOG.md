# Changelog

All notable changes to CryoBookQ are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-08-31

Production soak on apps.aureas.xyz: Coincall was dropped on ~11% of 15‑minute
slots even after a successful full-catalogue collect. Deployed and verified on
the 10:15 UTC boundary after this release.

### Fixed

- **Coincall / Deribit post-collect timeout** — After `ws_done` (~34.8s, 100%
  coverage), batch unsubscribe plus a 5s WebSocket `close_timeout` pushed the
  burst past `BOOKQ_BURST_TIMEOUT_S` (40s). `asyncio.wait_for` cancelled the
  task and discarded books that were already captured (`matched=0` for the
  slot). Teardown now drops the connection (`teardown=drop_ws`) with
  `close_timeout=1`.
- **Health under-counted peer misses** — When Deribit (hub) met its floor and
  parquet wrote, `_record_result` treated the slot as full success and never
  incremented `incomplete_today`, so ops health looked clean while Coincall was
  timing out. Peer incompletes now set `last_incomplete`, increment the daily
  counter, and surface `status=incomplete` while keeping `last_ok` for the hub.
- **`pyproject.toml` layout** — `dependencies` had been nested under
  `[project.urls]`, which newer setuptools/pip rejects and blocked editable
  reinstall on deploy.

### Changed

- Default `BOOKQ_BURST_TIMEOUT_S` raised from **40 → 55** so connect/subscribe
  and short WS teardown have headroom after a ~34s lead-open collect window.
- Ops / venue docs updated for teardown behaviour, health semantics, and the
  new timeout default.

### Verified (apps)

- Daemon + hub active; public `/bookq/` 200.
- Post-deploy slot: Coincall `coverage=1.0`, `duration_s≈35.8`,
  `teardown=drop_ws`; quality OK; no timeout in journal.

## [0.1.0] — 2026-08-28

Initial multi-exchange production line: Deribit hub with Coincall, Bybit, OKX,
and Binance L5 bursts; parquet store; public scorecard hub; systemd deploy on
apps.aureas.xyz.

[0.1.1]: https://github.com/Rick987-beep/CryoBookQ/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Rick987-beep/CryoBookQ/releases/tag/v0.1.0
