# Improvement plan (synthesised)

## P0 — Security

1. **Shell / command injection surface:** Replace or harden `create_subprocess_shell` paths; mandatory `shlex.quote` per dynamic fragment; fuzz tests (`executor.py`, worker helpers, `tool_jobs`).
2. **Compose / dev defaults:** Document “never use defaults beyond loopback”; fail-fast optional profile for non-test.

## P1 — Reliability / API

1. **Webhook idempotency + rate limits** — Stripe: `30/minute` limiter + Redis event-id claim (~30d TTL) before reconcile (`billing.py`). Other providers: verify per-adapter.
2. **Shell HTTP mutators** — authz review for any browser-callable paths.

## P1 — Observability / CI

1. **`spectra_ai` coverage:** Done in `pyproject` + CI `--cov` (aggregate gate 70%).
2. **Pyright vs Docker parity:** Static-analysis job runs Pyright inside `Dockerfile.test`.

## P2 — Architecture

1. **Reduce `services/*` → `app` imports** for scheduler/worker; extract small shared kernel into `packages/` over time.
2. **ServerNode PK vs UUID convention** — document or normalise (see `backend/01-backend-audit.md`).

## P2 — UX / UI

1. Items from `ui/01-ui-audit.md` (forms, dashboard inputs, shell 404 messaging, branding).

## Big moves (optional)

- Split `spectra_api` health duplication (`/api` vs `/api/v1`) only after client enumeration — [`verification/02-reconciliation.md`](../verification/02-reconciliation.md) records why dual mount stayed intentional for probes.
- Nightly job: `live` / `e2e` / `ui` / soak off PR path.
