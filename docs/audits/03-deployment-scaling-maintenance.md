# Deployment Scaling Maintenance Audit

## Critical / High

- TensorZero was attached only to an internal backend network, blocking outbound OpenRouter DNS/egress. Fixed by attaching TensorZero to the non-internal frontend network without publishing ports.
- Swarm and Compose worker services do not mount the Docker socket, while sandbox/tool execution uses Docker. If worker owns sandbox execution, default stacks likely break tool containers.
- Swarm app does not set passworded `RATE_LIMIT_STORAGE`; Redis uses auth, but app default is unauthenticated Redis URL. API replicas can lose shared rate limit state.
- Ops scripts/docs have mismatches: `migrate_server.sh` still references `spectra_user`; deploy health checks reference scheduler port `5020` while service health uses `5011`; Swarm docs use secret names that do not match stack secret names.
- Autoscaling docs describe Compose scaling, but scheduler uses Swarm backend only.

## Architecture Direction

- Keep Caddy as sole public ingress on 80/443.
- Keep app, AI service, TensorZero, DB, Redis, Garage, ClickHouse, scheduler, and worker internal.
- For swarm members, encrypted overlay networks are acceptable baseline.
- For non-swarm/behind-NAT hosts, add WireGuard/Tailscale-style mesh and make host agent join/provision through private control paths.
- Do not build custom Garage/TensorZero/ClickHouse images just to pull config from DB. Prefer official images plus generated config/secrets, because custom stateful infra images increase patch burden.

## No-Downtime Direction

- Use at least two app replicas before draining/removing any host.
- Caddy upstreams should route only to healthy app instances.
- Sessions must be stateless/shared: JWT/Redis/DB shared secrets and storage must match across replicas.
- Stateful services need managed/external DB/Redis/S3 options or explicit replication/backup before automated host removal.

## Live VPS Checks

- VPS baseline: 4 CPU, 7.8 GiB RAM, 99 GiB free disk, Docker/Compose installed.
- Full test stack live smoke passed on VPS through Caddy.
- Internal direct AI smoke passed on VPS (`app` -> `ai-svc` -> TensorZero -> OpenRouter).
- Caddy failover check passed: after stopping primary `app`, `/api/health` through Caddy stayed healthy via `app-replica`; primary app restarted cleanly.
- Scheduler periodic cleanup crashed because scheduler image excluded `app.worker` while maintenance imported cleanup functions from `app.worker.cleanup_jobs`. Cleanup functions now live under `app.services`, and scheduler cleanup was verified from inside the scheduler container.
- Scheduler image intentionally does not include S3 dependencies such as `aioboto3`; transient mission artifact cleanup now skips with a warning if the storage client is unavailable instead of crashing the periodic cleanup loop.
