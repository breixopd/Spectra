# Spectra — Future Improvements Plan

Roadmap for post-stabilization enhancements. Items are prioritized by impact and complexity.

Infrastructure direction: start with one server running the full stack, then split tools, RAG, and other services onto additional nodes only when load or isolation requirements justify it. The UI should become the control plane for adding and managing those extra nodes; it is not a prerequisite for the first deployment.

---

## 1. MCP Server with API Key Auth

**Goal**: Expose Spectra functionality as a Model Context Protocol (MCP) server so external AI agents and tools can trigger assessments, query findings, and retrieve reports via a standardized protocol.

**Scope**:

- MCP server endpoint (SSE or stdio transport) behind API key authentication
- Tools exposed: `start_mission`, `get_findings`, `get_report`, `list_targets`, `search_rag`
- Resources exposed: mission status, target inventory, knowledge base
- Per-key rate limiting and audit logging
- Admin UI page to create/revoke API keys with granular permissions

**Implementation Notes**:

- Use `mcp` Python SDK (or `fastmcp`) for protocol compliance
- Mount as a sub-application on `/mcp/` with separate auth middleware
- API keys stored in `system_config` table with `is_secret=True`
- Keys can be scoped: read-only, execute, admin
- WebSocket transport for real-time mission status subscriptions

**Complexity**: Medium | **Impact**: High

---

## 2. Automatic Dataset Generation from Mission Data

**Goal**: Automatically generate structured datasets from completed missions for fine-tuning and training custom security models.

**Scope**:

- Post-mission pipeline that extracts structured instruction/response pairs
- Dataset formats: JSONL (for fine-tuning), CSV (for analysis), HuggingFace Dataset format
- Types of training data:
  - Tool selection: given target context → correct tool + arguments
  - Finding classification: given tool output → structured finding
  - Exploitation planning: given reconnaissance data → attack plan
  - Report generation: given findings → professional report text
- Quality filters: only from missions with confirmed findings, exclude false positives
- Export UI in the reports section + scheduled background generation
- Optional: push directly to HuggingFace Hub or S3-compatible storage

**Implementation Notes**:

- New service: `app/services/dataset/generator.py`
- Template-based extraction with Jinja2 for different training formats
- Deduplication using RAG embeddings (semantic similarity check)
- Privacy filter: strip IP addresses, credentials, and PII before export
- Admin setting to opt-in/out of dataset generation per mission

**Complexity**: Medium | **Impact**: High

---

## 3. Tool Container Scaling for Concurrent Missions

**Goal**: Support running multiple missions simultaneously without tool container bottlenecks.

**Scope**:

- Tool container pool: maintain N ready containers, scale up on demand
- Container assignment: each mission gets a dedicated container (isolation)
- Resource limits: per-container CPU/memory caps configurable in settings
- Container lifecycle: auto-cleanup after mission completion + grace period
- Queue management: if all containers busy, queue missions with priority
- Dashboard indicator: show container pool status (available/busy/queued)

**Implementation Notes**:

- New service: `app/services/tools/container_pool.py`
- Uses Docker SDK to create/destroy containers from the `spectra-tools` image
- Pool configuration: min_containers, max_containers, idle_timeout
- Health checks per container; auto-replace unhealthy ones
- Shared plugin volume mount (read-only) across all containers
- Each container gets a unique network alias for the mission's tool adapter

**Complexity**: High | **Impact**: High

---

## 4. Single-Node First Infrastructure Roadmap

**Goal**: Keep the first deployment simple by running everything on one server, then expand to UI-managed remote nodes only when scale, latency, or isolation makes it necessary.

**Supported progression**:

1. Single host first: run `app`, `db`, `tools`, and local RAG workloads together via Docker Compose on one machine.
2. Remote tool workers next: move tool execution to one or more dedicated hosts when concurrent missions, isolation boundaries, or tool startup times justify it.
3. Remote RAG and background services after that: split ingestion, embeddings, and retrieval when knowledge workloads begin competing with API responsiveness.
4. Broader multi-node deployment last: add app replicas, coordinators, replicas, and other specialized services only after the first three phases are stable.

**UI control-plane expectations**:

- The UI should eventually expose an "Infrastructure" area for registering and managing extra nodes.
- Operators should be able to add a server by entering hostname/IP, SSH port, and credentials, then selecting a role such as `tool-worker`, `rag-worker`, `db-replica`, or `app-instance`.
- The UI-managed flow should handle Docker installation checks, image rollout, shared secret registration, health checks, and safe removal workflows.
- None of that UI-driven automation should be required for the initial single-node deployment.

**Scale triggers**:

- Keep everything on one server while mission volume is low and operational simplicity matters more than horizontal scale.
- Move tools first when execution isolation or queue depth becomes the bottleneck.
- Move RAG next when indexing, embeddings, or semantic retrieval consume enough CPU or RAM to affect the web/API path.
- Move database replicas or app instances only when read load, HA needs, or geographic placement become real requirements.

**Implementation Notes**:

- New service: `app/services/infra/server_manager.py`
- SSH automation via `paramiko` or `asyncssh`
- Deployment playbooks as shell scripts generated per role
- Registration uses a shared secret for mutual authentication
- Server status stored in DB table `infrastructure_nodes`
- Caddy upstream config auto-updated when app instances change
- Safety: require confirmation for destructive actions, audit all SSH commands

**Security Considerations**:

- SSH keys stored encrypted in DB (use existing `encryption.py`)
- Strict input validation on hostnames/IPs to prevent command injection
- Network segmentation for tool and RAG workers
- Audit log for all infrastructure changes

**Complexity**: Very High | **Impact**: Medium (needed at scale)

---

## 5. Dedicated RAG / Knowledge Service

**Goal**: Move embeddings, document ingestion, vector indexing, semantic retrieval, and re-ranking into a dedicated service so the main app is not bottlenecked by RAG workloads.

**Why this matters**:

- Local embedding generation and indexing are CPU/RAM intensive.
- Large ingestion jobs compete directly with API latency.
- Retrieval workloads can scale very differently from mission orchestration.
- It should be possible to start with all containers on one machine, then move RAG to another host later without changing the app contract.

**Scope**:

- Standalone `rag-worker` or `knowledge-service` container
- API or gRPC contract for:
  - `index_documents`
  - `delete_documents`
  - `semantic_search`
  - `rebuild_index`
  - `get_rag_health`
- Separate ingestion workers for chunking, embedding, and index maintenance
- Optional dedicated vector storage host separate from the primary app DB
- Backpressure and concurrency limits for reindexing and bulk ingestion
- Cache warmup for frequently used searches and KB slices

**Implementation Notes**:

- Phase 1: run app + db + tools + rag on one host via Docker Compose
- Phase 2: move the RAG service to a second host with the same API contract, ideally added and monitored through the Infrastructure UI
- Phase 3: dedicated vector host plus multiple RAG workers behind a load balancer
- Start with pgvector for simplicity, then keep a migration path to Qdrant, Weaviate, or OpenSearch if scale demands it
- Batch embeddings and re-ranking work to reduce per-request overhead
- Add a write queue so uploads do not block request threads

**Complexity**: High | **Impact**: High

---

## 6. Additional Ideas (Lower Priority)

### 6.1 Distributed Ingestion and Background Job Plane

- Separate mission execution from indexing, report generation, CVE ingestion, and long-running enrichment
- Dedicated worker pools with queues per workload class
- Keeps app servers responsive while heavy background work scales horizontally

### 6.2 Shared Object Storage Layer

- Move reports, artifacts, uploaded files, and generated datasets into S3-compatible object storage
- Makes app, tool, and RAG workers easier to move across hosts
- Simplifies retention policies and cross-node artifact access

### 6.3 Coordinator / Control Plane Split

- Keep the web/API app focused on auth, UI, orchestration, and policy
- Move scheduling, queue arbitration, worker assignment, and cluster health into a coordinator service
- Simplifies multi-node expansion later

### 6.4 Custom Model Fine-Tuning Pipeline

- In-app workflow to fine-tune LoRA adapters on generated datasets
- Upload to Ollama or vLLM for immediate deployment
- A/B testing: compare fine-tuned vs base model on same targets

### 6.5 Collaborative Multi-User Missions

- Team assignments: multiple operators on same mission
- Role-based views: analyst sees findings, operator controls tools
- Real-time collaboration via WebSocket presence

### 6.6 Compliance Report Templates

- Pre-built templates for PCI-DSS, HIPAA, SOC2, ISO 27001
- Auto-mapping of findings to compliance controls
- Executive summary generation with risk scoring

### 6.7 Plugin Marketplace

- Community plugin repository with signed submissions
- One-click install from UI
- Rating and review system

### 6.8 Notification Integrations

- Slack, Discord, Teams webhooks for mission events
- Email notifications with configurable triggers
- PagerDuty/OpsGenie for critical findings

---

## Priority Matrix

| Item | Complexity | Impact | Dependencies | Suggested Order |
| ------ | ----------- | -------- | -------------- | ---------------- |
| MCP Server | Medium | High | None | 1st |
| Dataset Generation | Medium | High | RAG system | 2nd |
| Tool Container Pool | High | High | Docker SDK | 3rd |
| Dedicated RAG Service | High | High | Queueing, vector storage contract | 4th |
| Multi-Server Deploy | Very High | Medium | Container Pool, RAG service | 5th |
| Fine-Tuning Pipeline | High | Medium | Dataset Gen | 6th |
