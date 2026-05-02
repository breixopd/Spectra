# API audit — spectra_api (read-only)

## Summary
`main.py:8` exposes `app` from `create_app()` (`factory.py`). HTTP routers mount via `routing.include_routers` using `SERVICE_MODE`. Full stack: `/api/v1` (health, auth, tools, missions, targets, findings, exploits, observability, export, system, CVE, wordlists, pentest sessions, helpers, shell, VPN, user settings, billing), MCP at `mcp.py:29`, extra health under `/api`, UI/public routers, admin composite (`admin/__init__.py`) with routes declared as full `/api/admin/...` paths. Rate limiting: `slowapi` + `RATE_LIMIT_STORAGE` (`rate_limit.py:102-107`), default `API_RATE_LIMIT`, exempt prefixes `rate_limit.py:90-99`, per-route `@limiter.limit`. Factory wires `SlowAPIMiddleware` and custom 429 JSON (`factory.py:86-89`). WS `/ws` and shell WS use per-second message caps (`factory.py:230-246`, `shell.py:111-119`). Stripe webhooks (`billing.py`) use `@limiter.limit("30/minute")` plus Redis-backed event-id dedup before reconcile (2026-05).

## Confirmed (file:line)
- `routing.py:37-98` — `include_routers`; full modes `""|all|api`; `ai|worker|scheduler` health-only; `tools` partial; unknown → health-only + log (`routing.py:90-96`).
- `factory.py:72-208` — middleware stack, maintenance (`109-144`), request timeout (`146-170`), body size (`172-185`), `/internal/metrics` + limiter (`194-206`), `include_routers` (`208`).
- `factory.py:187-210` — static + `/ws` only for api-like `SERVICE_MODE`.
- `routing.py:49-51` — `/api/v1`, auth prefix `/auth` → `/api/v1/auth/*`.
- `shell.py:30,52-100` — prefix `/shell`, WS auth, mission ownership, `shell_access` feature.
- `shell.py:137-154` — `@limiter` on `GET /sessions`, `GET /listeners`.
- `missions/__init__.py:21-22` — sub-routers merged (no nested `include_router`).
- `auth/__init__.py:13-17` — login, registration, password, totp, session sub-routers.
- `login.py:54,153` — `RateLimits.LOGIN`, `TOKEN_REFRESH`.
- `session.py` — multiple `@limiter.limit` (e.g. `session.py:32` for `SESSION_READ`).
- `registration.py:21` — `SETUP`; `ui/public.py:503` — `PUBLIC_REGISTER`.
- `missions/core.py:69` — `MISSION_START`; `mission_lifecycle.py:87+` — `MISSION_CONTROL`; `feedback.py:48` — `MISSION_STEER`.
- `lifespan.py:151-170,228` — Redis reachability for rate-limit storage (non-DEBUG can hard-fail).
- `config.py:253` — `SERVICE_MODE` setting.
- `mcp.py:29` — router prefix `/api/mcp`.
- `billing.py` — `POST /webhook` and `POST /webhooks/{provider}` use `@limiter.limit("30/minute")`; Stripe events deduped via Redis before `reconcile_stripe_event`.

## Suspected
- ~~Stripe replay~~ — **Mitigated (2026-05):** verified webhook payloads expose Stripe `event.id`; `billing._claim_stripe_webhook_event` uses Redis `SET NX` (~30d TTL) before `reconcile_stripe_event`. Missing Redis degrades to previous behaviour (no dedup).
- Many admin routes may fall back only to default global limit unless decorated (uneven vs `admin/email.py`, `audit.py`, `content.py`).

## Not reviewed
- Every non-listed router end-to-end; MCP methods; export/tools/findings internals; Caddy edge limits; complete admin module list.

## Recommendations
- Document `SERVICE_MODE` ↔ mounted routes for operators (mirror `routing.py`).
- Periodically audit admin routers for stricter per-route limits where abuse is plausible (many routes inherit global default).
