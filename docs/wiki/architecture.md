# Architecture

[← Wiki Home](home.md) | [Configuration](configuration.md) | [Deployment](deployment.md) | [Plugins](plugins.md)

---

Technical deep-dive into Spectra's agent system, execution pipeline, and learning mechanisms.

## Agent System (MAKER Framework)

Spectra uses the **MAKER** framework: Maximal Agentic decomposition, K-threshold Error mitigation, and Red-flagging.

### Agent Roles (12 Agents)

| Agent | Role | Temperature | Description |
|-------|------|-------------|-------------|
| ScopeAgent | Scope | 0.1 | Parses targets (IPs, domains, CIDRs) from user input |
| ToolSelectorAgent | Tool Selection | 0.3 | Selects and configures the right security tool for each task |
| MissionController | Planning | 0.4 | Creates PTES-aligned mission plans, handles steering |
| ExploitCrafter | Exploitation | 0.7 | Selects exploits, configures payloads, iterative retry |
| ExploitVerifier | Verification | 0.2 | Verifies exploit results and chains |
| POCDeveloper | Code Gen | 0.2 | Writes custom exploit scripts (Python/Go/Bash) |
| VectorGenerator | Analysis | 0.3 | Generates attack vectors from discovered services |
| SafetySupervisor | Safety | 0.1 | Blocks dangerous commands via regex + LLM analysis |
| PostExploitation | Post-Exploit | 0.3 | Plans privilege escalation, persistence, lateral movement |
| ReporterAgent | Reporting | 0.3 | Generates PTES-standard assessment reports |
| DebriefAgent | Learning | 0.3 | Post-mission analysis: extracts lessons for memory |

### Consensus System (K-Threshold Voting)

Critical decisions pass through quality gates where multiple LLM instances vote:

| Gate | When | Voters | Threshold | Min Confidence |
|------|------|--------|-----------|----------------|
| PLAN | Mission planning | 3 | 2/3 | 70% |
| TOOL_SELECTION | Each tool pick | 2 | 2/2 | 50% |
| PAYLOAD | Exploit crafting | 3 | 2/3 | 70% |
| REPLAN | Plan changes | 3 | 2/3 | 60% |
| EXECUTION | High-risk actions | 3 | 3/3 | 80% |

---

## Context Management

The `ContextManager` (`app/services/ai/context.py`) prevents prompt explosion by budgeting tokens across context sections with priority-based allocation.

### Priority Levels

| Priority | Level | Examples |
|----------|-------|---------|
| CRITICAL (0) | Always included | System prompt, task instruction |
| HIGH (1) | Truncated to fit | Current target/findings, tool output |
| MEDIUM (2) | Included if budget allows | Memory lessons, playbook recommendations |
| LOW (3) | Dropped first | RAG context, methodology reference |
| OPTIONAL (4) | Best-effort | Historical stats |

- Default budget: **6000 tokens** per prompt
- Sections sorted by priority; lower-priority sections are truncated or dropped when budget is exceeded
- Tool output auto-truncated: **3000 chars stdout**, **500 chars stderr** for LLM context

---

## Credential Store

The `CredentialStore` (`app/services/mission/credentials.py`) captures discovered credentials during missions for reuse by subsequent tools.

- **Per-mission, in-memory** — credentials scoped to the mission lifecycle
- **Auto-extraction** — regex patterns extract credentials from tool output (Hydra, generic login patterns)
- **Deduplication** — same user/pass/host/service combo stored once
- **Capacity limit** — max 100 credentials per mission
- **Prompt injection** — `get_summary_for_prompt(host)` builds compact credential context for LLM
- **Attack surface export** — `to_dicts()` for inclusion in mission findings

---

## RAG (Retrieval-Augmented Generation)

PostgreSQL-backed semantic search engine (`app/services/ai/rag.py`).

### Components

| Component | File | Purpose |
|-----------|------|---------|
| `RAGService` | `rag.py` | Document storage, cosine similarity search |
| `EmbeddingService` | `embeddings.py` | Embeddings via API provider or local fastembed |

### How It Works

1. **Embedding** — Text is embedded via the configured embedding provider (local fastembed or any OpenAI-compatible API). Configure `EMBEDDING_MODEL` to select the model.
2. **Storage** — Embeddings stored as JSONB arrays in a `rag_documents` PostgreSQL table.
3. **Search** — Query embedded, cosine similarity computed in application code against stored vectors.

### Document Types

| Type | Source | Indexed When |
|------|--------|--------------|
| `finding` | Mission findings | Mission completes |
| `cve` | CVE intelligence data | CVE DB scripts |
| `tool_doc` | Tool documentation | Tool docs indexed |
| `knowledge` | Knowledge base articles | Manual ingestion |

### Configuration

```python
RAGConfig(
    embedding_model="text-embedding-3-small",  # OpenAI-compatible model key
    embedding_dim=1536,                         # Auto-adapts to actual dimension
    default_top_k=5,                            # Results per query
    min_score=0.5,                              # Cosine similarity threshold
    batch_size=500,                             # Indexing batch size
)
```

---

## Execution Pipeline

```text
User enters target + directive
        │
        ▼
  MissionController creates plan
        │ (validated at PLAN gate)
        ▼
  For each task in plan:
        │
        ├─ tool_selector → picks tool → ToolExecutionService
        │  (ContextManager assembles prompt with memory + RAG + credentials)
        │                                      │
        │                        ┌──────────────┘
        │                        ▼
        │              SafetySupervisor checks command
        │                        │
        │                  ┌─────┴─────┐
        │                SAFE        BLOCKED
        │                  │
        │                  ▼
        │         Sandbox worker executes tool via per-mission queue
        │                  │
        │                  ▼
        │         Output parsed → Findings → Attack Surface updated
        │         Credentials extracted → CredentialStore
        │                  │
        │                  ▼
        │         Memory records tool result + OS detection
        │
        ├─ exploit_crafter → iterative exploitation loop
        │         CVE intel → Memory → RAG → Credential Store → Exploit selection
        │         Retry with different payloads/strategies
        │         On success: record chain to memory + playbook
        │
        ├─ reporter → generates PTES report
        │
        ▼
  Mission complete → post-mission learning
        │
        ├─ DebriefAgent extracts lessons → MissionMemory
        ├─ PlaybookEngine exploit patterns → persisted to disk
        ├─ RAG indexes mission findings
        ├─ False positive detection (repeated info findings)
        └─ OS profile update
```

---

## Learning System (3 Layers)

### Layer 1: Persistent Memory (`memory.py`)

Stored as JSON files in `data/cache/`:

- **tool_lessons.json** — which tools produced findings for which services
- **exploit_lessons.json** — successful exploit chains with CVEs
- **target_profiles.json** — effective/ineffective tools per OS family
- **false_positives.json** — noisy template IDs to skip

Debrief lessons are auto-saved after every mission by the `DebriefAgent`.

### Layer 2: Playbook Engine (`playbook.py`)

Deterministic service-to-tool mapping (no LLM needed):

- HTTP → nmap → nuclei → nikto → gobuster → sqlmap
- SSH → nmap with scripts → hydra (default creds only) → searchsploit
- SMB → nmap with smb-vuln scripts → metasploit ms17-010
- FTP → nmap with ftp-anon → hydra
- WordPress → wpscan → nuclei wordpress templates

Exploit patterns learned during missions are persisted to disk and loaded on restart.

### Layer 3: RAG Indexing

Mission outcomes (findings, tools used, successful strategies) are indexed into the RAG store. Future missions query this for relevant prior knowledge.

### CVE Intelligence (`cve_intel.py`)

Built-in database of 25+ commonly exploited CVEs. Correlates discovered service versions to known exploits:

```text
nmap finds Apache 2.4.49
    → cve_intel returns CVE-2021-41773 (path traversal, CRITICAL, VERSION MATCH)
    → exploit_crafter uses this as primary candidate
```

### Grounding Framework (`grounding.py`)

Anti-hallucination mechanisms:

- Tool output validation (signature pattern matching)
- Evidence extraction (meaningful lines only, not full output)
- Confidence tracking with decay
- Agents must cite concrete evidence in reasoning

---

## Service Architecture

Spectra uses a **ServiceRegistry** pattern (`app/services/gateway/service_registry.py`) to transparently route between in-process and remote implementations. When a gateway URL is configured, the registry instantiates an HTTP client adapter; otherwise it creates the local implementation.

### Extractable Services

| Service | Config Setting | Local Implementation | Protocol |
|---------|---------------|---------------------|----------|
| Sandbox Orchestrator | `SANDBOX_ORCHESTRATOR_URL` | `SandboxPool` (`app/services/tools/sandbox/`) | HTTP `/containers/*` |

### What Stays In-Process

| Component | Reason |
|-----------|--------|
| PostgreSQL | Single `DATABASE_URL` is sufficient; use managed DB for HA |
| Embeddings | Handled by local fastembed or API provider — no separate service |
| RAG / Vector Search | Runs on the same PostgreSQL DB (pgvector) |
| Agent orchestration | Core logic, not a hot path for scaling |

### ServiceRegistry Pattern

```python
from app.services.gateway import get_service_registry

registry = get_service_registry()
pool = await registry.get_sandbox_orchestrator()  # Remote or local Docker
```

The registry uses lazy initialization with async locks (double-checked locking). Services are created on first access and cached. Call `registry.invalidate("sandbox")` to force re-creation after config changes.

### Server Pool Management

For scaling across multiple servers, see the [Scaling Guide](scaling.md). Spectra includes a `ServerPoolManager` that tracks server nodes with weighted least-connections load balancing. Service types include `sandbox_worker`, `db`, and `storage`.

---

## LLM Routing (`router.py`)

TensorZero-powered smart routing. See [Configuration](configuration.md) for all LLM settings.

### Task Tiers

| Tier | Tasks | Recommended Model |
|------|-------|-------------------|
| 1 (Simple) | Scope, tool selection, safety | qwen2.5:3b, gpt-4o-mini |
| 2 (Moderate) | Planning, consensus, reporting | gpt-4o-mini, claude-3-haiku |
| 3 (Complex) | Exploit crafting, POC generation | gpt-4o, claude-3.5-sonnet |

### Fallback Chain

```text
Primary provider → Fallback provider(s) → Mock (testing)
```

---

## Safety Mechanisms

1. **SafetySupervisor** — regex blocklist + LLM analysis of every command
2. **Anti-brute-force** — blocks rockyou.txt, large wordlists, file-based credential lists
3. **Plugin signing** — Ed25519 signatures required in production (see [Plugins](plugins.md))
4. **Consensus voting** — multi-model validation for high-risk actions
5. **Container isolation** — all tools run in per-mission [sandboxes](sandboxes.md)
6. **Scope enforcement** — agents only target authorized hosts

For full security details, see the [Security Guide](security.md).
