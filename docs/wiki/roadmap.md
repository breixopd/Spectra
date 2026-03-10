# Roadmap

[← Wiki Home](home.md) | [Architecture](architecture.md)

---

Future improvements plan. Items prioritized by impact and complexity.

---

## Completed

### ✅ Per-Mission Ephemeral Sandbox Containers

**Status**: Core implementation complete.

- `SandboxPool` service — creates/destroys/monitors per-mission Docker containers
- Per-mission queue routing via PostgreSQL job queues
- `Sandbox` ORM model + Alembic migration
- Lifespan hooks — pool init at startup, orphan cleanup
- Mission lifecycle integration
- Security hardening — `CAP_DROP ALL`, PID limits, tmpfs, no Docker socket in sandboxes

See [Sandboxes](sandboxes.md) for full documentation.

### ✅ S3-Compatible Object Storage

**Status**: Implemented.

- MinIO/S3 integration for mission artifacts, sessions, knowledge base, and backups
- Local filesystem fallback when `S3_ENDPOINT_URL` is empty
- Four dedicated buckets: missions, sessions, knowledge, backups

See [Configuration](configuration.md) for S3 settings.

### ✅ Server Pool Management

**Status**: Implemented.

- `ServerPoolManager` with weighted least-connections load balancing
- `ServerNode` model tracking service type, health, capacity, and weight
- Admin API for CRUD operations on server nodes
- SSH auto-provisioning for remote servers
- Health monitoring with periodic checks

See [Scaling](scaling.md) for usage guide.

---

## Planned

### 1. MCP Server with API Key Auth

**Goal**: Expose Spectra functionality as a Model Context Protocol (MCP) server so external AI agents can trigger assessments, query findings, and retrieve reports.

**Scope**:

- MCP server endpoint (SSE or stdio transport) behind API key authentication
- Tools exposed: `start_mission`, `get_findings`, `get_report`, `list_targets`, `search_rag`
- Resources exposed: mission status, target inventory, knowledge base
- Per-key rate limiting and audit logging
- Admin UI page to create/revoke API keys with granular permissions

**Complexity**: Medium | **Impact**: High

### 2. Automatic Dataset Generation from Mission Data

**Goal**: Generate structured datasets from completed missions for fine-tuning custom security models.

**Scope**:

- Post-mission pipeline extracting instruction/response pairs
- Dataset formats: JSONL, CSV, HuggingFace Dataset
- Training data types: tool selection, finding classification, exploitation planning, report generation
- Quality filters: only confirmed findings, exclude false positives
- Privacy filter: strip IPs, credentials, PII before export

**Complexity**: Medium | **Impact**: High

### 3. Sandbox Enhancements (Remaining Work)

- Warm pool (pre-warmed idle containers for faster mission start)
- Per-sandbox Docker networks for full network isolation between missions
- Tiered resource profiles from plugin JSON (`resources.tier`)
- OOM-based automatic escalation (exit 137 → recreate at next tier)
- Golden image builder — rebuild image when plugins change
- Priority queue with per-user sandbox limits
- Container image scanning (Trivy/Grype on rebuild)

### 4. Infrastructure Scaling

- UI "Infrastructure" area for registering and managing remote nodes
- Add server by hostname/IP + SSH credentials + role selection
- Docker installation checks, image rollout, health checks, safe removal
- DB read replicas
- App instance replicas behind Caddy

---

## Ideas (Lower Priority)

| Idea | Description |
| ------ | ------------- |
| **Distributed Job Plane** | Separate mission execution from indexing, report generation, and enrichment |
| **Private Image Registry** | Harbor or GHCR for distributing golden `spectra-tools` image |
| **Coordinator Split** | Move scheduling and worker assignment into a dedicated coordinator service |
| **Custom Model Fine-Tuning** | In-app LoRA adapter fine-tuning + A/B testing |
| **Multi-User Missions** | Team assignments, role-based views, real-time collaboration |
| **Compliance Templates** | PCI-DSS, HIPAA, SOC2, ISO 27001 report templates |
| **Plugin Marketplace** | Community plugin repository with signed submissions |
| **Notification Integrations** | Slack, Discord, Teams, PagerDuty webhooks |
