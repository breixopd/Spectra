# Platform Audit Baseline

## Scope

Pre-release audit covers backend/API/security, frontend/UI, deployment/scaling/maintenance, AI/mission workflows, tests, performance, image size, and operational automation.

## Baseline State

- Health consolidation committed as `5fad285`.
- `.env.test` is intentionally uncommitted and contains live test secrets.
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `SERVICE_AUTH_SECRET` are present in `.env.test`; secret values were not printed.
- Audit docs live in `docs/audits/` to keep module notes out of repo root.

## External Guidance Checked

- OWASP API Security Top 10 2023 remains baseline for SaaS API risk: BOLA, broken auth, excessive exposure, resource abuse, function auth, SSRF, security misconfig, inventory, and unsafe third-party API consumption.
- FastAPI production guidance emphasizes strict Pydantic validation, object-level authorization, explicit CORS origins, rate limits, security headers, dependency scanning, generic 500s, and audit logging.
- Docker multi-host guidance: use Docker Swarm encrypted overlay networks when hosts are swarm members. Use WireGuard/Tailscale-style mesh for non-swarm or NAT-host cases, then keep Caddy as only public ingress.
- TensorZero production docs recommend ClickHouse for higher throughput observability, async writes, batch writes, and bounded write queues to avoid memory growth under load.
- Python/FastAPI image guidance: keep per-service multi-stage slim images, copy only runtime venv/artifacts, remove build tooling from runtime, use non-root users, and copy requirements before app code for caching.
- Unsloth/Gemma/Qwen training guidance: start with opt-in mission datasets in chat format, hold out eval data, use Colab/hosted GPU scripts for LoRA/QLoRA, and keep admin-visible progress/export paths.

## Immediate Risk Notes

- Live LLM generation previously reached TensorZero but failed with provider auth. New `.env.test` key must be re-tested.
- Caddy must remain sole public ingress; app, worker, scheduler, AI, TensorZero, DB, Redis, Garage, and ClickHouse stay internal.
- Avoid backwards compatibility layers unless protecting shipped data/interfaces; project remains pre-release.
