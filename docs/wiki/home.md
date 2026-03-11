# Spectra Documentation Wiki

[Architecture](architecture.md) | [Configuration](configuration.md) | [Deployment](deployment.md) | [Scaling](scaling.md) | [API Reference](api-reference.md)

---

Welcome to the Spectra documentation wiki. Spectra is a Multi-Agent System (MAS) for automated security assessments built with FastAPI, PostgreSQL, and Docker.

## Contents

| Page | Description |
|------|-------------|
| [Architecture](architecture.md) | System design — 12 AI agents, MAKER framework, execution pipeline, learning system |
| [Configuration](configuration.md) | All environment variables and settings organized by section |
| [Deployment](deployment.md) | Docker Compose setup, production deployment with Caddy, CI/CD pipeline |
| [Scaling](scaling.md) | Multi-server scaling — server pools, S3 storage, sandbox workers |
| [API Reference](api-reference.md) | REST API endpoints — missions, findings, tools, admin |
| [Plugins](plugins.md) | Tool plugin system — JSON schema, signing, installation methods |
| [Pentest Workflow](pentest-workflow.md) | PTES methodology, quality gates, exploitation strategy |
| [Sandboxes](sandboxes.md) | Per-mission ephemeral containers, isolation, resource tiers |
| [Security](security.md) | Authentication, RBAC, encryption, network isolation, audit logging |
| [Authentication](authentication.md) | JWT tokens, password reset, rate limiting, RBAC roles, API keys |
| [Worker System](worker-system.md) | Background jobs, dead-letter queue, cleanup, notifications, reports |
| [Deployment Guide](deployment-guide.md) | Production setup, SSL/TLS, backups, scaling considerations |
| [Development](development.md) | Local setup, testing, code structure, contributing |
| [Roadmap](roadmap.md) | Future improvements and completed milestones |

## Quick Links

- **First time?** Start with [Development](development.md) for local setup, or [Deployment](deployment.md) for production.
- **Configuring settings?** See [Configuration](configuration.md) for all environment variables.
- **Adding a tool?** See [Plugins](plugins.md) for the JSON plugin schema.
- **Scaling out?** See [Scaling](scaling.md) for multi-server setup.
