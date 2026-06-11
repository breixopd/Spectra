# Spectra — Perfection Context

**Read and follow in full first:** [`PERFECT_PROMPT.md`](./PERFECT_PROMPT.md) at the repo root — generic master prompt (phases, Definition of Done, principles). This file adds Spectra-specific context on top.

**This file is additive.** Apply both documents together. If you only received this file, open `PERFECT_PROMPT.md` before doing anything else.

**Audit folder name:** `.audit/YYYY-MM-DD--spectra/`

---

## Project

| | |
|---|---|
| **Path** | `/home/breixopd14/projects/spectra` |
| **What it is** | Autonomous penetration-testing platform: multi-agent missions, YAML-driven frameworks (PTES/OWASP/NIST), consensus voting on critical decisions, evidence-first findings, plugin tool system, golden worker images, Docker Swarm scaling |
| **Not public yet** | No external users. **Delete legacy paths; do not keep internal backwards-compat shims or feature flags** for platform-invariant behaviour |
| **Docs** | `docs/wiki/` — must match reality; delete stale or superseded material (including `docs/superpowers/` when outdated) |

---

## Architecture (canonical layout)

```
packages/          # Bounded contexts (import via workspace packages)
  common/          # Config, shared types — keep slim, no god-package
  auth/            # JWT (EdDSA preferred), RBAC, rate limits
  persistence/     # SQLAlchemy models, Alembic-facing ORM
  mission/         # Orchestration, frameworks, reporting
  tools/           # Tool execution, sandbox, golden image
  ai-core/         # LLM client, consensus gates, agents
  scaling/         # Server pool, Docker Swarm, auto-scale
  billing/         # Plans, subscriptions, discounts
  system/          # Secret bootstrap, platform settings
services/
  api/             # FastAPI — REST, WebSocket, admin, SPA shell
  ai/              # AI inference service (TensorZero routing)
  worker/          # Mission execution, sandboxes, tool runs
  scheduler/       # Background loops, maintenance, scaling hooks
apps/web/          # React + Vite + TypeScript SPA (product UI)
deploy/docker/     # compose.yaml (dev), docker-compose.swarm.yml (prod)
config/            # tensorzero.toml, frameworks YAML, tailwind for legacy admin CSS
db/alembic/        # Migrations — single head required
scripts/           # first_run.sh, start.sh, ops/swarm_deploy.sh, ops/swarm_multinode_lab.sh
tests/             # unit/, integration/ — live pentest/UI tests are manual in dev, not CI
```

**Package manager:** `uv` workspace (`uv sync`, `uv lock`, `uv run`). **Do not** reintroduce `spectra_platform` monolith or duplicate import trees.

**Import rule:** `scripts/check_import_boundaries.py` enforces acyclic package graph. Fix violations; do not add lazy shims to bypass.

---

## UI model (hybrid — do not regress)

| Surface | Tech | Routes |
|---------|------|--------|
| **Product app** | React SPA (`apps/web/`), always served same-origin from FastAPI | `/login`, `/dashboard`, `/missions`, `/findings`, `/attack-graph`, `/evidence`, `/reports`, `/tools`, `/settings` |
| **Marketing / SEO** | Server-rendered Jinja (`spectra_api.ui.public`) | `/` (landing), `/pricing`, `/register`, `/legal/*`, `/changelog`, `/status`, `/sitemap.xml` |
| **Admin panel** | Jinja + static (`/admin`, `services/api/templates/admin/`) | Users, plans, audit, **models/TensorZero**, server pool, training, monitoring, settings, email, content |

- **No `SPA_ENABLED` flag** — SPA is always on when `dist/` exists; missing build is a safe no-op with a log warning.
- **Legacy authenticated Jinja dashboard** (`spectra_api.ui.pages`) is **retired** — do not remount it.
- **Admin must manage everything**, including LLM model tiers and TensorZero config (`/api/admin/tensorzero`, `config/tensorzero.toml`).
- Test product UI with **cursor-ide-browser MCP** (functionality + styling). Test admin separately.

---

## LLM / DeepSeek (hard rule)

**Only these DeepSeek model IDs are valid:**

| Tier | Model | Thinking |
|------|-------|----------|
| `fast` | `deepseek-v4-flash` | disabled |
| `balanced` | `deepseek-v4-flash` | enabled |
| `capable` | `deepseek-v4-pro` | enabled |

- **`deepseek-chat`**, **`deepseek-reasoner`**, and any pre-V4 IDs are **deprecated** (DeepSeek aliases both legacy names to v4-flash — using them would silently skip Pro for capable tier).
- Source of truth: `config/tensorzero.toml`, enforced by `tests/unit/services/test_tensorzero_config.py` and `tests/unit/api/test_tensorzero_router.py`.
- Gateway: TensorZero container (`TENSORZERO_GATEWAY_URL`). Admin can view/override tier→model mapping.

---

## Infrastructure & secrets

| Component | Role |
|-----------|------|
| **PostgreSQL** | Primary store + pgvector |
| **Redis** | Rate limits, cache, queues |
| **Garage** | S3-compatible object storage (artifacts, registry backend) |
| **Platform registry** | `registry:2` on Garage S3 — golden `spectra-tools` images pushed here, not GHCR for workers |
| **TensorZero + ClickHouse** | LLM gateway + inference telemetry |

**Secrets:** hybrid bootstrap via `scripts/first_run.sh`, `scripts/start.sh`, `spectra_system.secret_bootstrap`. Prefer **EdDSA JWT** keypair over HS256 when possible. Never commit `.env`, keys, or generated `data/`.

**Compose:**

```bash
# Local dev stack
docker compose -f deploy/docker/compose.yaml up -d

# Swarm production
./scripts/ops/swarm_deploy.sh
```

---

## Multi-node Swarm testing (same host)

Use the DinD lab — no extra hardware required:

```bash
./scripts/ops/swarm_multinode_lab.sh up      # manager + N workers on one host
./scripts/ops/swarm_multinode_lab.sh status  # nodes, services, tasks
./scripts/ops/swarm_multinode_lab.sh test-dns # overlay DNS smoke
./scripts/ops/swarm_multinode_lab.sh down
```

**Validate when working on scaling:**

- Cross-node task scheduling (worker replicas on different nodes)
- Overlay network DNS (`redis`, `db`, service names resolve across nodes)
- **Admin server pool** — add/remove nodes, auto-setup on join (`services/api/.../admin/servers.py`, `packages/scaling/`)
- Inter-service auth over Swarm (`SERVICE_AUTH_SECRET`, internal URLs)
- Golden image pull from platform registry on new workers
- Self-healing: unhealthy task replacement, scheduler maintenance loops (`services/scheduler/`)

Related tests: `tests/integration/test_server_pool_integration.py`, `tests/unit/api/test_admin_servers.py`, `tests/unit/worker/test_auto_scaler.py`, `tests/unit/test_swarm_deploy.py`.

---

## Spectra-specific audit targets

Work through these when executing the master prompt phases — **everything**, not a sample:

### Pentest & mission flows
- Full mission lifecycle: scope → recon → exploitation → post-exploitation → report
- Framework switching (PTES/OWASP/NIST YAML), phase gating, advisory vs strict enforcement
- Eight quality gates: plan, tool pick, payload, replan, execution, output parsing, red-flag, consensus
- Evidence-first findings (`proof_status`, `evidence_bundle`, verifier states)
- Attack graph, tool plugins (32+), golden image build/push/rollout
- Sandboxes, OOM escalation, connect-back/shell routing

### Admin panel (`/admin`)
- Users, roles, RBAC, audit log
- **Plans, billing, subscriptions, discounts** (`packages/billing/`, `admin/plans.py`)
- **Model / TensorZero management** (`admin/tensorzero.py`)
- Server pool: add node → auto setup → join Swarm → scale workers
- Training / dataset generation (`admin/training.py`)
- Platform settings, email templates, content, monitoring, rollback

### User-facing flows
- Landing, pricing, register, login, setup wizard, forgot/reset password
- SPA: every screen loads, auth works, WebSocket live updates, responsive layout
- Subscribe / upgrade / discount redemption paths

### Backend & ops
- `scripts/first_run.sh` + `scripts/start.sh` idempotent bootstrap
- Alembic migrations apply cleanly (single head)
- CI workflows (`.github/workflows/ci.yml`, `release.yml`) — fix if broken; gate on local pytest + live deploy
- Profiling profile (cAdvisor, Pyroscope) opt-in via compose profile
- No test artifacts on host: `data/*` is gitignored — use Docker volumes / tmpfs for runtime data

---

## Quality gates (run before claiming done)

```bash
cd /home/breixopd14/projects/spectra
uv sync
ruff check .
uv run pytest tests/unit/ -q --no-cov          # expand as needed
scripts/check_import_boundaries.py
docker compose -f deploy/docker/compose.yaml config
cd apps/web && npm ci && npm run build
```

**Live verification** (on VPS when stack is up):

```bash
curl -sf http://localhost:5000/api/health
curl -sf http://localhost:5000/ | head          # SSR landing
curl -sf http://localhost:5000/login | head     # SPA shell
# Browser: login → /dashboard → missions, findings, admin /admin
```

Log results to `.audit/.../verification/`.

---

## Hard rules (Spectra additions to base prompt)

1. **No legacy / no internal backwards compat** — one way to do things; remove dead code in the same change. See `.cursor/rules/no-legacy-backcompat.mdc`.
2. **No feature flags** for behaviour that should always be true (e.g. SPA, golden image rebuild on plugin change).
3. **Research before keeping** — verify against current docs, similar products, and tests; do not preserve code “just in case.”
4. **Decide autonomously** — pick the option that future-proofs and simplifies; do not ask the user unless irreversible.
5. **Commit locally as you go; do not push** unless explicitly asked.
6. **Keep repo neat** — no stray test data in `data/`, `docker/data/`, `logs/`, `memories/`; respect `.gitignore`.
7. **DeepSeek: v4-flash and v4-pro only** — reject/replace anything else.

---

## Key file index

| Area | Path |
|------|------|
| Config | `packages/common/src/spectra_common/config.py` |
| SPA serving | `services/api/src/spectra_api/ui/spa.py` |
| API factory | `services/api/src/spectra_api/factory.py` |
| Routing | `services/api/src/spectra_api/routing.py` |
| TensorZero config | `config/tensorzero.toml` |
| Golden image | `packages/tools/src/spectra_tools/sandbox/golden_image.py` |
| Server pool | `packages/scaling/src/spectra_scaling/pool_manager.py` |
| Swarm deploy | `scripts/ops/swarm_deploy.sh` |
| Swarm lab | `scripts/ops/swarm_multinode_lab.sh` |
| Admin routers | `services/api/src/spectra_api/api/routers/admin/` |
| SPA app | `apps/web/src/` |
| Migrations | `db/alembic/versions/` |

---

## Start

1. Read `PERFECT_PROMPT.md` + this file
2. Create `.audit/YYYY-MM-DD--spectra/progress.md` with merged Definition of Done
3. Execute master prompt phases with Spectra targets above
4. **Do not stop until everything is done**
