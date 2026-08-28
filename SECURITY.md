# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| `main`  | Yes       |

## Reporting a vulnerability

If you discover a security issue (credential leakage, unsafe deploy defaults, injection in the hub, etc.):

1. **Do not** open a public issue with exploit details.
2. Email the maintainers privately, or use [GitHub Security Advisories](https://github.com/Rick987-beep/CryoBookQ/security/advisories/new) on this repository.
3. Include steps to reproduce, impact, and any suggested fix.

We aim to acknowledge reports within a few business days.

## Scope notes

- CryoBookQ uses **read-only** public market data APIs. It does not execute trades.
- Production `.env` and `servers.toml` must never be committed.
- The public hub at `/bookq/` is informational only; do not embed secrets in client-side assets.

## Safe defaults

- Deploy scripts refuse live rsync without `BOOKQ_ALLOW_DEPLOY=1`.
- `.env` and `servers.toml` are gitignored.
- See [AGENTS.md](AGENTS.md) for agent/automation rules on production hosts.
