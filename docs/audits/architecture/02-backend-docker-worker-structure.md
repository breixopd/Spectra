# Architecture Audit: Backend, Docker, Worker Structure

Status: loop 1 draft
Scope: `app/services`, `app/core`, Dockerfiles, Compose/Swarm, worker-only target interaction.

## Findings

- The control/data-plane split is improving: API controls listeners through `shell_relay_client`, and worker owns listener startup.
- Docker network tests cover API not joining target networks in the test stack, but production and local Compose need continued review as architecture changes.
- Sandbox execution still depends on Docker availability. Some deployment modes mount Docker access on scheduler/tools rather than worker, which can make worker responsibilities unclear.
- Worker image and API image include broad service code; there is likely image bloat and a wider-than-needed runtime surface.
- `app/core/lifespan.py` starts many background tasks and listeners; lifecycle logic should be split into startup checks, service initialization, listeners, and shutdown coordination.
- Remaining test warnings show async resource lifecycles are not fully deterministic in tests.

## Recommended Refactor

- Define explicit service responsibility boundaries:
  - API: auth, HTTP, control-plane orchestration, policy decisions.
  - Worker: target interaction, tool execution, listeners, evidence collection.
  - Scheduler: periodic maintenance, health/reporting jobs, cleanup.
  - AI service: model calls, embeddings, RAG support.
- Split `app/core/lifespan.py` into:
  - `startup_checks.py`
  - `service_init.py`
  - `listeners.py`
  - `shutdown.py`
- Review worker and API Dockerfiles for dependency pruning and code copy minimization.
- Add image size and cold-start benchmarks in CI artifacts.
- Add a Docker permission matrix doc that states which service needs Docker socket, target network access, S3 access, DB access, and service-auth access.

## Verification Targets

- Only worker/tools containers can reach targets.
- No API/scheduler/AI container has target network membership.
- Each service image contains only runtime dependencies needed by that service.
- Shutdown produces no unraisable exceptions, import teardown errors, or leaked aiohttp/asyncpg resources.
