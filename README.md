<div align="center">

# Spectra

**AI-Driven Security Assessment Platform**

[📖 Documentation Wiki](docs/wiki/home.md) · [🚀 Quick Start](#quick-start) · [📡 API Reference](docs/wiki/api-reference.md)

</div>

---

Spectra is a Multi-Agent System for automated security assessments. It coordinates 12 specialized AI agents to perform end-to-end penetration testing — from reconnaissance to reporting — with human oversight at every step.

## Features

- **Autonomous Pentesting** — AI agents plan and execute security assessments following PTES methodology
- **Multi-Agent Consensus** — 5 quality gates ensure decisions are validated before execution
- **Plugin System** — 25+ security tools (Nmap, Nuclei, SQLMap, etc.) with JSON-defined configurations
- **RAG Knowledge Base** — Contextual retrieval from CVE databases, tool documentation, and past assessments
- **Per-Mission Sandboxes** — Isolated Docker containers with resource limits and network isolation
- **S3-Compatible Storage** — Mission data stored in MinIO/S3 with local filesystem fallback
- **Multi-Server Scaling** — Server pool management with health monitoring and load balancing
- **Web Dashboard** — Real-time mission monitoring, tool management, and admin controls

## Quick Start

```bash
# Clone and configure
git clone https://github.com/breixopd14/spectra.git
cd spectra
cp .env.example .env  # Edit with your settings

# Start all services
docker compose -f docker/docker-compose.yml up -d

# Access the dashboard
open http://localhost:5000  # Redirects to /setup on first run
```

See [Getting Started](docs/wiki/development.md#getting-started) for detailed setup instructions.

## Architecture

| Service | Container | Purpose |
|---------|-----------|---------|
| **db** | PostgreSQL + pgvector | Primary data store, RAG vector search |
| **app** | FastAPI | API server + Web UI (port 5000, proxied via Caddy) |
| **tools** | Kali Linux worker | Security tool execution |
| **minio** | MinIO | S3-compatible object storage |
| **caddy** | Caddy | Reverse proxy, TLS termination |

For detailed architecture, see the [Architecture Guide](docs/wiki/architecture.md).

## Documentation

All documentation is in the [Wiki](docs/wiki/home.md):

- [Architecture](docs/wiki/architecture.md) — System design, agents, services
- [Configuration](docs/wiki/configuration.md) — All settings and environment variables
- [Deployment](docs/wiki/deployment.md) — Production deployment, Docker, CI/CD
- [Scaling](docs/wiki/scaling.md) — Multi-server setup, S3 storage, server pools
- [API Reference](docs/wiki/api-reference.md) — REST API endpoints
- [Plugins](docs/wiki/plugins.md) — Tool plugin system
- [Pentest Workflow](docs/wiki/pentest-workflow.md) — PTES methodology, quality gates
- [Sandboxes](docs/wiki/sandboxes.md) — Per-mission isolation
- [Security](docs/wiki/security.md) — Authentication, encryption, audit
- [Development](docs/wiki/development.md) — Local setup, testing, contributing
- [Roadmap](docs/wiki/roadmap.md) — Future improvements

## License

Private — All rights reserved.
