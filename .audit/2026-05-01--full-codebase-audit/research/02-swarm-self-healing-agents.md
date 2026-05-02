# External research — Swarm, self-healing, agent memory

## Docker Swarm / scaling

- Swarm has **rolling updates** (`update_config`, `rollback_config`) — already used in `docker/docker-compose.swarm.yml`.
- **Native metric autoscaling is not built in**; typical pattern is Prometheus + cAdvisor + a small controller calling `docker service scale` / Docker API ([MoldStud scaling guide](https://moldstud.com/articles/p-scaling-microservices-in-docker-swarm-a-practical-guide-for-efficient-deployment), [Docker service create](https://docs.docker.com/reference/cli/docker/service/create/)).
- **Health checks vs restart:** Swarm restart policies apply to **process exit**; unhealthy tasks may need external watchdogs or app-level probes that exit on fatal degradation — see [OneUptime discussion of auto-healing without naive reliance on healthcheck alone](https://oneuptime.com/blog/post/2026-02-08-how-to-set-up-docker-container-auto-healing-without-orchestration/view).
- **Managers:** odd number of managers (e.g. 3) for quorum — general Swarm guidance ([Toxigon](https://toxigon.com/best-practices-for-docker-swarm-management)).

## Autonomous pentesting / agent memory (product direction)

- Research stacks combine **RAG** (CVE/NVD), **multi-step memory** (episodes, reflections), and **tool orchestration** (e.g. Metasploit/Nmap) — survey: [AutoSecAgent / recursive memory + RAG](https://link.springer.com/article/10.1007/s11227-026-08439-z) (Springer; cookie wall may block).
- **Memory manipulation** is an explicit attack class for agentic systems — [redteams.ai lab](https://redteams.ai/topics/labs/intermediate/lab-agent-memory-manipulation).
- Spectra already aligns partially: tenant-scoped RAG (`RAGRequest`), tool context; gaps called out in [`plan/01-improvement-plan.md`](../plan/01-improvement-plan.md).

## OPEN (product)

- Nightly `live` / `e2e` job policy vs PR-only CI.
- Whether to add external autoscaler docs vs implement a minimal `spectra-scaler` service later.
