# Testing Strategy

[<- Wiki Home](home.md) | [Development](development.md) | [Deployment Guide](deployment-guide.md)

---

This page defines the authoritative platform-wide testing strategy for Spectra. It covers what must be verified across the API, UI, workers, scheduler, AI service, proxy, data stores, deployment workflows, and operational scripts.

## Purpose And Scope

This strategy verifies that a change is safe across the whole platform, not just within one file or one feature area. The goal is to prove, at the right depth for the change, that Spectra still:

- serves correct API and UI behavior
- executes missions and tool workflows correctly
- enforces auth, session, and rate-limit controls
- starts and deploys cleanly in containerized environments
- preserves operational safety for backup, restore, health checks, and rollback
- remains stable under expected concurrency and failure conditions

Covered subsystems include:

- FastAPI app, routers, templates, and browser flows
- AI service, scheduler, and worker services
- PostgreSQL, Redis, MinIO, ClickHouse, and TensorZero gateway integrations
- Caddy edge proxy and deployment configuration
- scripts/test.sh, scripts/health_check.sh, and scripts/ops/* workflows

### Definition Of Done By Change Size

| Change size | Done means |
| --- | --- |
| Docs-only or comment-only | The docs are updated, links resolve, and no platform behavior claim is introduced without evidence. |
| Small local code change | Targeted unit tests pass, lint/security checks still pass, and the changed path is exercised once locally. |
| Cross-module or router/API change | Unit plus integration coverage passes, request/response behavior is checked, and UI or live verification is added if the change is user-visible or environment-dependent. |
| High-risk platform change | The required matrix below passes, including live or browser checks where applicable, deployment/config validation, and ops verification for backup, restore, or rollback if touched. |
| Release candidate | All required release-gate items pass; any missing automation is replaced by explicit manual evidence before release. |

## Test Layers

| Layer | What it verifies | Current path | Status |
| --- | --- | --- | --- |
| Unit tests | Local logic, validation, rate-limit behavior, service helpers, model/repository logic | `python3 -m pytest tests/unit/ -q` or `./scripts/test.sh unit` | Implemented |
| Router/API contract tests | Endpoint behavior, request validation, response shape, auth/rate-limit decorators | `docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner` and targeted unit/integration tests | Implemented, but no standalone OpenAPI diff gate |
| Service integration tests | App-to-DB, settings, service wiring, async flows, non-live integrations | `python3 -m pytest tests/integration/ -v --tb=short --timeout=120 -k "not live and not e2e"` | Implemented |
| Live integration tests | Real services, vulnerable targets, tool execution, live ops smoke | `./tests/run_live_tests.sh` and `./tests/run_live_tests.sh --targets` | Implemented |
| Browser/UI tests | Rendered pages, login/setup flows, interactive user behavior | `./tests/run_ui_tests.sh` | Implemented |
| Ops-script smoke tests | Backup/restore, S3, DB maintenance, incident workflows, health checks | `./tests/run_live_tests.sh` covers live ops smoke; manual script checks exist under `scripts/ops/` | Partial |
| Deployment/config validation | Docker image builds, compose validity, TensorZero config parsing, deploy health checks | CI docker-build job, `docker compose ... config --quiet`, release health checks | Implemented |
| Security/static analysis | Lint, code safety checks, dependency audit | `ruff check app/`, `bandit -r app/ -c pyproject.toml --severity-level high --confidence-level high`, and the dependency-audit command noted below | Implemented |
| Performance/benchmark tests | Hot-path latency and throughput for core services and queries | No dedicated benchmark harness committed | Missing harness |
| Burst/load/rate-limit tests | Auth burst resistance, registration burst, queue/tool concurrency, rate-limit enforcement at edge and app layers | No dedicated load harness committed | Missing harness |
| Soak/stability tests | Long-running stability, leak detection, churn handling, retry behavior over time | No committed soak runner or CI job | Missing harness |
| Backup/restore and disaster recovery verification | Backup creation, backup verification, restore safety, rollback path | `scripts/ops/backup_restore.sh`, release pre-deploy backup, rollback workflow | Partial; restore drills are not automated end-to-end |

## Environments

| Environment | Purpose | Minimum verification |
| --- | --- | --- |
| Local developer loop | Fast feedback while iterating | Unit tests for touched code, targeted integration checks, and one local smoke path for the changed behavior |
| CI verification | Default merge gate | Lint, unit tests with coverage, integration tests, Bandit, dependency audit, Docker image build verification, compose validation |
| Release validation | Pre-release confidence on the version to ship | CI-equivalent checks plus release workflow checks, deploy health checks, and backup/rollback readiness |
| Pre-production or staging | Optional but strongly recommended for operator-managed deployments | Run release candidate images against a staging stack, then execute browser smoke, live integration, config validation, health checks, and any migration or restore drill |
| Production-safe smoke checks | Non-destructive verification after deploy or during incident response | Health endpoints, public-status, worker/storage health proxies, backup list/verify, and read-only config or container checks only |

## Concrete Commands

Use the real commands already present in this repo.

| Purpose | Command |
| --- | --- |
| Unit tests | `python3 -m pytest tests/unit/ -q` |
| Unit tests in Docker | `./scripts/test.sh unit` |
| Non-live integration tests | `python3 -m pytest tests/integration/ -v --tb=short --timeout=120 -k "not live and not e2e"` |
| Integration tests in Docker (may require live services) | `./scripts/test.sh integration` |
| Full containerized test stack | `./scripts/test.sh compose` |
| Targeted settings/router/setup validation | `docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner` |
| Live integration tests | `./tests/run_live_tests.sh` |
| Live target-only tests | `./tests/run_live_tests.sh --targets` |
| Browser/UI tests | `./tests/run_ui_tests.sh` |
| Lint | `ruff check app/` |
| Security scan | `bandit -r app/ -c pyproject.toml --severity-level high --confidence-level high` |
| Dependency audit | See the dependency-audit note below. |
| TensorZero config validation | `python3 -c "import tomllib; tomllib.load(open('config/tensorzero.toml', 'rb')); print('tensorzero.toml: valid')"` |
| Dev compose validation | `docker compose --env-file .env.example -f docker/docker-compose.yml config --quiet` |
| Swarm compose validation | `docker compose --env-file .env.example -f docker/docker-compose.swarm.yml config --quiet` |
| Production-safe health check | `./scripts/health_check.sh http://localhost:5000/api/health` |
| Deep health check | `HEALTH_CHECK_FULL=1 ./scripts/health_check.sh http://localhost:5000/api/health` |
| Backup inventory | `./scripts/ops/backup_restore.sh list` |
| Backup integrity check | `./scripts/ops/backup_restore.sh verify <backup_id>` |

Dependency-audit note: use `pip-audit --fix --dry-run -l --ignore-vuln PYSEC-2024-65 --ignore-vuln PYSEC-2024-66 || true` when you need the exact CI-friendly command.

Convenience wrappers also exist in the Makefile, including `make test-unit`, `make test-integration`, `make test-all`, `make test-coverage`, `make lint`, and `make check`.

## Required Test Matrix By Change Type

The minimum required checks scale with the risk of the change.

| Change type | Minimum required verification |
| --- | --- |
| Router/API change | Unit tests, non-live integration tests, targeted router/setup validation when settings or router paths changed, and browser verification if the endpoint affects rendered flows |
| Auth/session change | Unit tests, non-live integration tests, browser/UI tests, explicit login/setup/reset flow verification, and rate-limit checks; burst testing evidence is required for release-level auth changes even if currently manual |
| Mission execution change | Unit tests, non-live integration tests, live target tests at minimum, full live tests if LLM or real tool paths changed, and UI verification if dashboard behavior changed |
| Worker/tooling change | Unit tests, non-live integration tests, live target tests, live ops smoke if scripts or queue behavior changed, and container/build validation when tooling images changed |
| Docker/Caddy/deployment change | Docker build verification, compose validation, health_check smoke, deploy-path verification, and explicit rate-limit or proxy verification if auth/public routes changed |
| Schema/migration change | Unit tests, non-live integration tests, live integration tests, backup list/verify before release, and a non-production restore drill before shipping |
| UI/template change | Browser/UI tests, any affected unit or integration tests for the backing routes, and one manual browser smoke for the changed page or flow |
| Ops/runbook/script change | Script-specific smoke checks, `./scripts/health_check.sh` where applicable, backup list/verify for backup-related changes, and live ops smoke if the script is exercised by the existing live suite |
| Rate-limiting/proxy/security change | Unit tests for the affected logic, browser or API smoke on the protected routes, compose/build validation for proxy changes, and burst/load evidence before release because the main risk is concurrency, not single-request correctness |

## Performance And Burst Testing

These checks should be treated as platform-wide requirements even where the repo does not yet provide dedicated harnesses.

| Workload | What to prove | Current state | What should exist next |
| --- | --- | --- | --- |
| Auth burst and password spray resistance | Login and reset endpoints return expected 429 behavior, preserve `Retry-After` and rate-limit headers, and do not degrade other traffic | Functional rate-limit code and unit coverage exist; no burst harness | A repeatable load suite against auth endpoints with per-IP and per-user assertions |
| Public registration burst | Public setup or registration-related routes remain bounded and fail safely under burst traffic | Edge and app rate-limit policies exist; no burst harness | A public-route load scenario that proves edge and app limits both behave as expected |
| WebSocket and session churn | Reconnect storms, repeated login/logout, and message bursts do not leak memory or leave stale session state | WebSocket rate limiting exists; no churn harness | A churn test that opens and closes many sessions and records memory, reconnect, and error rates |
| Queue throughput | Jobs enqueue, dispatch, retry, and drain at an acceptable rate without backlog explosion | Functional mission and worker tests exist; no throughput benchmark | A queue benchmark that measures latency, backlog growth, retries, and dead-letter behavior |
| Tool execution concurrency | Multiple missions and tool runs behave correctly under concurrent worker load | Live tests exercise real tools functionally; no concurrency harness | A concurrent tool-execution suite across worker replicas and sandbox capacity |
| DB and query hot paths | Auth, mission listing, findings, audit logs, and vector-backed lookups stay within expected latency bounds | No committed benchmark suite | Targeted query benchmarks and query-plan review for hot endpoints |
| Caddy edge rate-limit behavior | Public routes are throttled correctly at the edge and recover cleanly after the limit window | Caddy rate-limit module is built and configured; no burst validation | A proxy-focused load test that proves Caddy behavior under burst traffic |
| App-level Redis-backed rate-limit behavior | Counters stay shared across replicas and return correct headers and retry windows | Redis-backed limiter is implemented; no multi-replica load harness | A multi-replica rate-limit test against Redis-backed storage |
| Memory and CPU ceilings for `app`, `worker`, `scheduler`, and `ai-svc` | Services remain inside declared ceilings or fail predictably and observably under stress | Local compose defines limits for `app` and `ai-svc`; committed `worker` and `scheduler` ceilings are not yet consistently codified | Codified ceilings for all long-running services plus benchmark and soak runs that record RSS, CPU, queue depth, and restart behavior |

Platform-wide rule: if a change materially alters concurrency, retries, session handling, proxying, or resource usage, single-request correctness is not enough. The change is not done until either an automated burst/benchmark harness exists or equivalent manual evidence is recorded for the release.

## Release Gate

Release candidates pass only when all applicable items below are true.

- [ ] Required checks from the change matrix have passed.
- [ ] CI-equivalent checks pass: lint, unit, integration, security scan, Docker build verification, and compose validation.
- [ ] Browser/UI verification has passed for any user-visible or auth/session change.
- [ ] Live integration verification has passed for mission, worker, tool, or environment-dependent changes.
- [ ] Config validation passes for Docker Compose and TensorZero configuration.
- [ ] No new high-severity Bandit finding blocks the release.
- [ ] Schema or migration changes have a verified backup and a non-production restore drill.
- [ ] Deployment candidate passes non-destructive health checks after deploy.
- [ ] Rate-limit, proxy, or security-sensitive changes include explicit burst/load evidence, automated or manual.
- [ ] Rollback path is confirmed for deployment-affecting releases.

Fail the release if a required item is skipped, if a needed harness does not exist and no manual evidence replaces it, or if a verification path only proves startup without proving the affected user or operator workflow.

## Gaps And Future Work

The current repo already has strong unit, integration, live, UI, config, and release-health coverage. It does not yet contain all the harnesses needed for full platform verification.

- No dedicated benchmark suite is committed for endpoint, queue, or query latency baselines.
- No dedicated burst/load harness is committed for auth, registration, WebSocket churn, worker concurrency, or Caddy edge rate limiting.
- No committed soak or stability runner exists for multi-hour verification.
- No standalone API contract or OpenAPI breaking-change gate is committed today.
- Backup creation and backup verification are scriptable, but scheduled automated restore drills are not part of CI.
- A dedicated staging workflow is not committed; teams with a staging environment should treat release validation there as mandatory for high-risk changes.
- `worker` and `scheduler` need explicitly codified resource ceilings before memory/CPU testing can become a hard release gate.

Recommended next additions:

- add `tests/performance/` for repeatable latency and throughput benchmarks
- add `tests/load/` for burst and rate-limit verification against auth, register, WebSocket, queue, and Caddy-protected routes
- add an automated non-production restore drill for migration-bearing releases
- add a staging validation runbook or workflow that mirrors the release gate
