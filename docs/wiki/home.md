# Spectra Documentation Wiki

[Architecture](architecture.md) | [Configuration](configuration.md) | [Operations](operations.md) | [Deployment](deployment.md) | [Scaling](scaling.md) | [API Reference](api-reference.md) | [Development](development.md) | [Testing Strategy](testing-strategy.md)

---

Welcome to the Spectra documentation wiki. Spectra is a Multi-Agent System (MAS) for automated security assessments built with FastAPI, PostgreSQL, and Docker.

## Contents

| Page | Description |
|------|-------------|
| [Architecture](architecture.md) | System design — 12 AI agents, MAKER framework, execution pipeline, learning system |
| [Configuration](configuration.md) | All environment variables and settings organized by section |
| [Deployment Guide](deployment-guide.md) | **Start here** — Docker Compose, Cloudflare, Docker Swarm, Caddy, backups, monitoring |
| [Operations](operations.md) | Canonical day-2 runbook index — health triage, backups, queue repair, incidents, logging |
| [Deployment](deployment.md) | CI/CD pipeline, versioning, rollback procedures |
| [Microservices](microservices-split.md) | Service architecture — app, AI, scheduler, worker, inter-service communication |
| [Scaling](scaling.md) | Multi-server scaling — server pools, S3 storage, read replicas |
| [API Reference](api-reference.md) | REST API endpoints — missions, findings, tools, admin |
| [Plugins](plugins.md) | Tool plugin system — JSON schema, signing, installation methods |
| [Pentest Workflow](pentest-workflow.md) | PTES methodology, quality gates, exploitation strategy |
| [Sandboxes](sandboxes.md) | Per-mission ephemeral containers, isolation, resource tiers |
| [Security](security.md) | Authentication, RBAC, encryption, network isolation, audit logging |
| [Authentication](authentication.md) | JWT tokens, password reset, rate limiting, RBAC roles, API keys |
| [Worker System](worker-system.md) | Background jobs, dead-letter queue, cleanup, notifications, reports |
| [Development](development.md) | Local setup, testing, code structure, contributing |
| [Testing Strategy](testing-strategy.md) | Platform-wide verification layers, change matrix, release gate, and known testing gaps |
| [Access Control](access-control.md) | Roles, permissions, admin boundaries, approval flows |
| [Private Registry Setup](private-registry-setup.md) | GHCR/private registry authentication and deployment setup |
| [Shell Sessions](shell-sessions.md) | Interactive shell session handling and audit trail |
| [Plan Tiers](plan-tiers.md) | Subscription plan limits, quotas, and feature gating |
| [Roadmap](roadmap.md) | Future improvements and completed milestones |

## Quick Links

- **First time?** Start with [Development](development.md) for local setup, or [Deployment Guide](deployment-guide.md) for production.
- **Planning verification?** See [Testing Strategy](testing-strategy.md) for the platform-wide test matrix and release gate.
- **Operating Spectra?** See [Operations](operations.md) for the canonical runbook index and [scripts/ops/README.md](../../scripts/ops/README.md) for the local script catalog.
- **Configuring settings?** See [Configuration](configuration.md) for all environment variables.
- **Adding a tool?** See [Plugins](plugins.md) for the JSON plugin schema.
- **Scaling out?** See [Scaling](scaling.md) for multi-server setup.
