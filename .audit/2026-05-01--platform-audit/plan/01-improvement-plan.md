# Prioritised improvements (from this audit)

## P0 — security / reliability

1. **Shell execution:** Centralise quoting; prefer `create_subprocess_exec` with argv where possible (`spectra_platform/services/tools/registry/executor.py`, `spectra_worker/helpers.py`, `tool_jobs.py`). ~~Add fuzz tests for metacharacters in targets/args~~ → `CommandBuilder` parametrized metachar regression tests added; worker full-shell fuzz still optional.
2. **Compose defaults:** Ensure non-local deploy paths never rely on `docker/compose.yaml` baked-in secrets; document “required env” for anything beyond loopback test.
3. **SERVICE_MODE:** ~~Unknown values must not mount full API~~ → implemented fail-closed (health-only). ~~Dead `ai`/`worker`/`scheduler`/`tools` router branches~~ → removed from `spectra_api.routing` (split ASGI apps).

## P1 — CI / coverage

1. **Align CI with `pyproject.toml`:** Unit job includes `--cov=spectra_api` and **`--cov=spectra_ai`** (aggregate gate still **70%**; verified **~70.63%**).
2. **Ruff on PR:** `spectra_platform/`, `tests/`, **`services/`**, **`packages/`** (was `app`+`tests` only).
3. **Optional later:** `--cov=spectra_scheduler` in the same aggregate gate (currently drops total **<70%**).

## P1 — architecture

1. **Shared kernel:** Decide long-term boundary: `packages/*` vs `app` as library for microservices (large effort).
2. **Health route duplication:** **Leave as-is** — `/api/health` (hidden schema) + `/api/v1/health` is intentional for probes vs versioned API (`spectra_api/routing.py`).
3. **FastAPI `router.routes.extend` merges** in missions/findings packages — refactor to supported composition when path semantics allow (M–L).

## P2 — tests

1. `tests/unit/services/test_shell_relay_client.py` for relay timeouts/backoff.
2. Split integration tests so non-e2e paths run in CI (`test_tool_execution` subset without `e2e` marker).
3. Optional nightly: `live` + `soak` + Playwright `ui`.

## P2 — observability / Swarm

1. ~~Document external autoscaler pattern next to `docker-compose.swarm.yml`~~ → header comment + `research/01-swarm-self-healing-agents.md`.
2. Consider liveness that **fails** process when dependency permanently broken (trade-off with noisy restarts).
