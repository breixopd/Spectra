# Spectra Documentation Wiki

[Architecture](architecture.md) | [Configuration](configuration.md) | [Operations](operations.md) | [Deployment Guide](deployment-guide.md) | [Scaling](scaling.md) | [API Reference](api-reference.md) | [Development](development.md) | [Testing Strategy](testing-strategy.md)

---

Welcome to the Spectra documentation wiki. Spectra is an automated penetration testing platform built with FastAPI, PostgreSQL, and Docker—coordinated agents, consensus gates, and YAML-defined methodologies (PTES, OWASP, NIST).

## Contents

| Page | Description |
|------|-------------|
| [Architecture](architecture.md) | Agents, eight quality gates, YAML frameworks, execution pipeline, microservices, caching |
| [Configuration](configuration.md) | All environment variables and settings organized by section |
| [Deployment Guide](deployment-guide.md) | **Start here** — Docker Compose, Cloudflare, Docker Swarm, CI/CD, rollback, private registry |
| [Operations](operations.md) | Canonical day-2 runbook index — health triage, backups, queue repair, incidents, logging |
| [Scaling](scaling.md) | Multi-server scaling — server pools, S3 storage, read replicas |
| [API Reference](api-reference.md) | REST API endpoints — missions, findings, tools, admin |
| [Plugins](plugins.md) | Tool plugin system — JSON schema, signing, installation methods |
| [Pentest Workflow](pentest-workflow.md) | PTES methodology, quality gates, exploitation strategy |
| [Sandboxes](sandboxes.md) | Per-mission ephemeral containers, isolation, resource tiers, shell sessions |
| [Security](security.md) | Authentication, RBAC, plan tiers, rate limiting, encryption, audit logging |
| [Worker System](worker-system.md) | Background jobs, dead-letter queue, cleanup, notifications, reports |
| [Development](development.md) | Local setup, testing, code structure, contributing |
| [Testing Strategy](testing-strategy.md) | Platform-wide verification layers, change matrix, release gate, and known testing gaps |
| [Runbooks](runbooks.md) | CI parity, pre-release checklist, compose-smoke — executable files live in the repo; see also [About the wiki](about-the-wiki.md) |
| [Frontend Patterns](frontend-patterns.md) | CSP-safe event delegation, modal macro, feature gates, test attributes |
| [Design Tokens](design-tokens.md) | CSS custom properties, color palette, typography, spacing, animations |
| [Roadmap](roadmap.md) | Future improvements and completed milestones |

## Quick Links

- **First time?** Start with [Development](development.md) for local setup, or [Deployment Guide](deployment-guide.md) for production.
- **Planning verification?** See [Testing Strategy](testing-strategy.md) and [Runbooks](runbooks.md) for `./scripts/runbooks/ci-parity.sh` (Docker — matches CI **`static-analysis`** + **`test`** gates).
- **Operating Spectra?** See [Operations](operations.md) for the canonical runbook index and [scripts/ops/README.md](../../scripts/ops/README.md) for the local script catalog.
- **Configuring settings?** See [Configuration](configuration.md) for all environment variables.
- **Adding a tool?** See [Plugins](plugins.md) for the JSON plugin schema.
- **Scaling out?** See [Scaling](scaling.md) for multi-server setup.
- **Working on the frontend?** See [Frontend Patterns](frontend-patterns.md) for event delegation and [Design Tokens](design-tokens.md) for the visual system.
