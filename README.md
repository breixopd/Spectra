# Spectra

**Autonomous AI-powered penetration testing platform.**

Spectra runs full security assessments against targets using LLM-orchestrated security tools. Point it at a target, give it a directive, and watch it scan, enumerate, exploit, and report — following real pentesting methodology (PTES).

It learns from every engagement via a 3-layer learning system (MissionMemory → PlaybookEngine → RAG), adapts to different system types, and gets better over time.

---

## Quick Start

1. **Clone and configure:**

   ```bash
   git clone <repo-url> && cd spectra
   cp .env.example .env
   # Edit .env — at minimum set JWT_SECRET_KEY to a secure random value
   ```

2. **Start services:**

   **Development** (direct access on port 5000):

   ```bash
   cd docker
   docker compose up -d
   ```

   **Production** (Caddy reverse proxy on port 443/5050):

   ```bash
   cd docker
   docker compose -f docker-compose.prod.yml up -d
   ```

3. **Open the web UI:**
   - **Dev:** <http://localhost:5000>
   - **Prod:** <https://localhost> (or your configured domain)
   - Create your admin account on the setup page
   - Configure your AI provider (LiteLLM-backed cloud/API gateway for hosted models, Ollama for local GPU)

> **Port conflict?** Set `SPECTRA_PORT=8080` in your `.env` file.

That's it. The tools container auto-installs security tools on first boot.

---

## What It Does

1. **You provide a target** (IP, domain, URL) and a directive ("full security assessment")
2. **12 AI agents plan the pentest** following PTES phases: Scope → Discovery → Enumeration → Vulnerability Analysis → Exploitation → Post-Exploitation → Reporting
3. **Tools execute autonomously** in a sandboxed Kali container via an Arq worker queue
4. **Consensus voting** validates critical decisions (planning, exploitation, payload crafting)
5. **Findings are parsed and tracked** in a live attack surface model
6. **Discovered credentials are stored** per-mission and reused by subsequent tools
7. **RAG indexes mission results** for semantic search in future engagements
8. **A report is generated** with findings, severity ratings, and remediation steps

### Live-Tested Results

| Target               | Findings | Critical | Tools Used                                     |
| -------------------- | -------- | -------- | ---------------------------------------------- |
| DVWA (web app)       | 31       | 3        | nmap, nuclei, nikto, searchsploit, gobuster    |
| Juice Shop (Node.js) | 50       | 4        | nmap, nuclei, sqlmap, searchsploit             |
| SSH Server           | 5+       | —        | nmap, hydra (default creds only), searchsploit |

---

## Features

### Autonomous Pentesting

- Multi-agent AI system (12 agents) orchestrates 18 security tools
- PTES methodology enforced in all planning and execution
- Mid-mission plan adaptation when new findings emerge
- CVE correlation: discovered service versions matched to known exploits
- Custom exploit (POC) generation when standard tools fail
- **Context window management** — priority-based token budgeting prevents prompt explosion
- **Credential reuse** — discovered credentials stored per-mission and fed to subsequent tools

### RAG Semantic Search

- Mission results automatically indexed into PostgreSQL-backed RAG store
- LiteLLM embeddings API (OpenAI, DashScope, etc.) — no local PyTorch needed
- Semantic search across past findings, CVEs, and tool documentation
- Fallback to SHA256 hashing when no embedding API is configured

### Manual Mode

- Run any tool directly from the UI without AI orchestration
- Visual pipeline editor: chain tools together (output of one → input of next)
- Dynamic argument forms built from each plugin's configuration

### Learning System (3 Layers)

1. **MissionMemory** — persistent JSON on disk: tool lessons, exploit chains, target profiles, false positives. Debrief lessons auto-saved after every mission.
2. **PlaybookEngine** — deterministic service-to-tool mappings. Exploit patterns persisted to disk across restarts.
3. **RAG** — mission outcomes indexed for semantic retrieval in future engagements.

- Auto-detects OS from tool output (Linux/Windows/macOS/FreeBSD/embedded)
- False positive detection (repeated low-value findings auto-flagged)
- Agents get richer context with each mission

### Plugin System

- Drop a JSON file into `plugins/` to add a new tool
- Auto-installs in the tools container on next boot
- Ed25519 cryptographic signing for production safety
- 18 tools included: nmap, nuclei, nikto, gobuster, ffuf, hydra, sqlmap, metasploit, searchsploit, wpscan, amass, naabu, whatweb, dirsearch, subfinder, feroxbuster, httpx, testssl

### Smart Routing (LiteLLM)

- Routes to any LLM provider: Ollama, OpenAI, Anthropic, Groq, Azure, DashScope, etc.
- Automatic fallbacks: local model fails → cloud takes over
- Per-task model selection: cheap models for simple tasks, capable models for exploit crafting
- 100+ models supported through unified interface

### Safety

- SafetySupervisor blocks dangerous commands (rm -rf, fork bombs, etc.)
- Anti-brute-force policy: blocks large wordlists, only allows default credential testing
- Consensus voting at 5 quality gates before critical actions
- All tools run in isolated Docker container

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│          Caddy Reverse Proxy (TLS, headers)     │
│          Port 443/5050 (prod) or 5000 (dev)     │
├─────────────────────────────────────────────────┤
│  Web UI (Jinja2 + Tailwind + WebSockets)        │
├─────────────────────────────────────────────────┤
│  FastAPI App Container                          │
│  ├── 12 AI Agents (scope → reporting)           │
│  ├── Context Manager (token budgeting)          │
│  ├── Credential Store (per-mission reuse)       │
│  ├── LiteLLM Router (model routing)             │
│  ├── RAG Engine (semantic search)               │
│  ├── Memory + Playbooks (learning)              │
│  └── CVE Intelligence (version correlation)     │
├──────────────┬──────────────────────────────────┤
│  PostgreSQL (data, cache, queues, RAG store)    │
├──────────────────────────────────────────────────┤
│  Tools Container (Kali Linux)                   │
│  ├── Arq Worker (job execution)                 │
│  ├── 18 security tools (auto-installed)         │
│  └── Plugin system (JSON configs)               │
└─────────────────────────────────────────────────┘
```

---

## Configuration

Copy `.env.example` to `.env` and set:

| Variable            | Required   | Description                                                |
| ------------------- | ---------- | ---------------------------------------------------------- |
| `AI_PROVIDER`       | Yes        | `litellm` (cloud/API gateway) or `ollama` (local GPU)      |
| `OLLAMA_HOST`       | If ollama  | Ollama server URL (default: `http://ai:11434`)             |
| `OLLAMA_MODEL`      | If ollama  | Model name (default: `qwen2.5:3b`)                         |
| `LLM_API_KEY`       | If litellm | API key for the LiteLLM-backed cloud provider              |
| `LLM_API_BASE_URL`  | If litellm | Custom base URL (for OpenRouter, vLLM, DashScope, etc.)    |
| `LLM_MODEL`         | If litellm | Model name or provider route (default: `gpt-4o-mini`)      |
| `POSTGRES_PASSWORD` | No         | PostgreSQL password (default: `spectra_dev`)               |
| `SPECTRA_PORT`      | No         | Port override (default: `443` prod / `5000` dev)           |
| `SPECTRA_DOMAIN`    | No         | Domain for Caddy TLS (default: `localhost`)                |
| `JWT_SECRET_KEY`    | Yes        | Secret key for JWT tokens (change from default!)           |

Everything else has sensible defaults. See `.env.example` for the full list.

---

## Testing

```bash
# Targeted settings/router/setup validation
docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner

# Live integration tests
./tests/run_live_tests.sh

# UI tests
./tests/run_ui_tests.sh

# Lint
ruff check app/
```

The settings flow validation path is intentionally narrow and container-only. It runs:
`test_runtime_settings.py`, `test_system_setup.py`, `test_smart_router.py`, `test_settings_runtime_api.py`, and `test_settings_templates.py`.

If the shared Compose test stack hits a local network or subnet conflict, use this containerized fallback instead of host-local pytest:

```bash
docker build -f docker/Dockerfile.tools -t spectra-tools-test .
docker run --rm \
   -e DATABASE_URL=sqlite+aiosqlite:///test.db \
   -e AI_PROVIDER=mock \
   -e JWT_SECRET_KEY=test-secret-key \
   -e FULLY_AUTOMATED=true \
   -e PLUGIN_SAFE_MODE=false \
   -v "$PWD/app:/app/app:ro" \
   -v "$PWD/tests:/app/tests:ro" \
   -v "$PWD/pytest.ini:/app/pytest.ini:ro" \
   -v "$PWD/.env.test:/app/.env.test:ro" \
   -v "$PWD/alembic:/app/alembic:ro" \
   -v "$PWD/alembic.ini:/app/alembic.ini:ro" \
   -v "$PWD/plugins:/app/plugins:ro" \
   -v "$PWD/reports:/app/reports" \
   --entrypoint sh spectra-tools-test \
   -c "pip install -q pytest pytest-asyncio pytest-dotenv aiosqlite aiohttp httpx && python3 -m pytest tests/unit/test_runtime_settings.py tests/unit/test_system_setup.py tests/unit/test_smart_router.py tests/unit/test_settings_runtime_api.py tests/unit/test_settings_templates.py -q --override-ini=addopts="
```

### Test Targets

Custom vulnerable containers are included for live testing:

```bash
cd docker/targets
docker compose -f docker-compose.targets.yml up -d
```

| Target        | Difficulty | Services              | Key Vulns                                 |
| ------------- | ---------- | --------------------- | ----------------------------------------- |
| Easy Web      | Easy       | HTTP, SSH             | Default creds, phpinfo, directory listing |
| Medium Multi  | Medium     | HTTP, FTP, MySQL, SSH | FTP anon, LFI, weak DB creds              |
| Hard Hardened | Hard       | HTTPS API, SSH        | CORS, SSRF, hidden endpoints, weak JWT    |
| DVWA          | Easy       | HTTP                  | Classic web vulns (SQLi, XSS, etc.)       |
| Juice Shop    | Medium     | HTTP                  | OWASP Top 10                              |

---

## Versioning & Releases

Spectra uses **CalVer**: `YYYY.MM.DD[.patch]` (e.g., `2026.03.07`, `2026.03.07.1`).

Releases are automated via GitHub Actions (`release.yml`):

1. Manual dispatch (`gh workflow run release`) or push a tag matching `v*`
2. CI runs tests + security scan (bandit)
3. Docker images built and pushed to GHCR with version + `latest` tags
4. GitHub Release created with auto-generated changelog
5. SSH deploy to production with health check

See [CHANGELOG.md](CHANGELOG.md) for release history.

---

## Documentation

| Document                                            | Description                                     |
| --------------------------------------------------- | ----------------------------------------------- |
| **[Penetration Testing Workflow](docs/pentest.md)** | How Spectra executes pentests phase by phase    |
| **[Plugin Guide](docs/plugins.md)**                 | Creating, configuring, and signing tool plugins |
| **[Architecture](docs/architecture.md)**            | Technical deep-dive into the agent system       |
| **[API Reference](docs/api_reference.md)**          | REST API endpoints                              |
| **[Deployment](docs/deployment.md)**                | Production deployment, Caddy, and CI/CD         |
| **[CHANGELOG](CHANGELOG.md)**                       | Release history (CalVer)                        |

---

## Project Structure

```
app/
├── api/              # FastAPI routes and schemas
├── core/             # Config, database, security, WebSocket, events
├── models/           # SQLAlchemy database models
├── services/
│   ├── ai/           # LLM clients, agents, consensus, memory, playbooks
│   │   ├── agents/   # 12 specialized agents (scope → reporting)
│   │   ├── context.py # Context window management (token budgeting)
│   │   ├── rag.py    # PostgreSQL-backed RAG engine
│   │   ├── embeddings.py # LiteLLM embedding service
│   │   ├── router.py # LiteLLM smart routing
│   │   ├── memory.py # Persistent cross-mission learning
│   │   ├── playbook.py # Deterministic attack playbooks
│   │   ├── grounding.py # Anti-hallucination framework
│   │   └── cve_intel.py # CVE correlation database
│   ├── mission/      # Mission lifecycle, execution, exploitation
│   │   └── credentials.py # Per-mission credential store
│   ├── tools/        # Tool registry, adapter, parser, installer
│   └── shell/        # Reverse shell session management
├── templates/        # Jinja2 HTML templates
└── static/           # JavaScript and CSS
docker/
├── docker-compose.yml       # Dev stack (app, db, tools)
├── docker-compose.prod.yml  # Prod stack (+ Caddy reverse proxy)
├── Caddyfile.prod           # Production Caddy config
├── targets/                 # Vulnerable test containers
├── Dockerfile.app           # FastAPI app image
└── Dockerfile.tools         # Kali tools worker image
plugins/                     # Tool plugin JSON configs (18 included)
tests/                       # 1589 unit tests
docs/                        # Documentation
```

---

## Legal

**Use responsibly.** Only scan targets you own or have explicit written permission to test. Spectra includes safety mechanisms but ultimately you are responsible for how you use it.

---

## Troubleshooting

| Issue                         | Solution                                                                      |
| ----------------------------- | ----------------------------------------------------------------------------- |
| Port 5000 already in use      | Set `SPECTRA_PORT=8080` in `.env`                                             |
| Database connection fails     | Check `POSTGRES_PASSWORD` matches in `.env` and `docker-compose.yml`          |
| "Container unhealthy"         | Wait 30s for DB init, then check `docker logs spectra-app`                    |
| Migrations fail               | Ensure `DATABASE_URL` matches your `POSTGRES_PASSWORD`                        |
| Ollama not connecting         | Use `http://ai:11434` in Docker, or `http://localhost:11434` for host install |
| Setup page not loading        | Check `docker logs spectra-app` for startup errors                            |
| PDF export not working        | PDF export requires `xhtml2pdf` which is optional                             |
| Caddy not starting (prod)     | Ensure port 443/80 are free; check `docker logs spectra-caddy`                |
| Caddy TLS errors              | Set `SPECTRA_DOMAIN` to your real domain; Caddy auto-provisions Let's Encrypt |
| RAG search returns no results | Verify `LLM_API_KEY` is set — RAG needs an embedding API to function          |
