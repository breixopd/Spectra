# Spectra Documentation Wiki

[Architecture](architecture.md) | [Configuration](configuration.md) | [Deployment](deployment.md) | [Scaling](scaling.md) | [API Reference](api-reference.md) | [Development](development.md)

---

Welcome to the Spectra documentation wiki. Spectra is a Multi-Agent System (MAS) for automated security assessments built with FastAPI, PostgreSQL, and Docker.

## Contents

| Page | Description |
|------|-------------|
| [Architecture](architecture.md) | System design — 12 AI agents, MAKER framework, execution pipeline, learning system |
| [Configuration](configuration.md) | All environment variables and settings organized by section |
| [Deployment Guide](deployment-guide.md) | **Start here** — Docker Compose, Cloudflare, Docker Swarm, Caddy, backups, monitoring |
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
| [Access Control](access-control.md) | Roles, permissions, admin boundaries, approval flows |
| [Authentication](authentication.md) | JWT tokens, password reset, API keys, anti-enumeration controls |
| [Private Registry Setup](private-registry-setup.md) | GHCR/private registry authentication and deployment setup |
| [Shell Sessions](shell-sessions.md) | Interactive shell session handling and audit trail |
| [Plan Tiers](plan-tiers.md) | Subscription plan limits, quotas, and feature gating |
| [Roadmap](roadmap.md) | Future improvements and completed milestones |

## Quick Links

- **First time?** Start with [Development](development.md) for local setup, or [Deployment Guide](deployment-guide.md) for production.
- **Operating Spectra?** See [Deployment Guide](deployment-guide.md) for runbooks, backups, incident response, and the `scripts/ops/*` toolkit.
- **Configuring settings?** See [Configuration](configuration.md) for all environment variables.
- **Adding a tool?** See [Plugins](plugins.md) for the JSON plugin schema.
- **Scaling out?** See [Scaling](scaling.md) for multi-server setup.
