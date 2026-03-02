# Spectra

**Autonomous AI-powered penetration testing platform.**

Spectra runs full security assessments against targets using LLM-orchestrated security tools. Point it at a target, give it a directive, and watch it scan, enumerate, exploit, and report — following real pentesting methodology (PTES).

It learns from every engagement, adapts to different system types, and gets better over time.

---

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — set AI_PROVIDER and API key (or use Ollama for local models)

# 2. Start everything
cd docker
docker compose up -d

# 3. Open the UI
# http://localhost:5000
# First visit → setup wizard for admin account + AI provider config
```

That's it. The tools container auto-installs security tools on first boot.

---

## What It Does

1. **You provide a target** (IP, domain, URL) and a directive ("full security assessment")
2. **AI agents plan the pentest** following PTES phases: Scope → Discovery → Enumeration → Vulnerability Analysis → Exploitation → Post-Exploitation → Reporting
3. **Tools execute autonomously** in a sandboxed Kali container via an Arq worker queue
4. **Consensus voting** validates critical decisions (planning, exploitation, payload crafting)
5. **Findings are parsed and tracked** in a live attack surface model
6. **A report is generated** with findings, severity ratings, and remediation steps

### Live-Tested Results

| Target | Findings | Critical | Tools Used |
|--------|----------|----------|------------|
| DVWA (web app) | 31 | 3 | nmap, nuclei, nikto, searchsploit, gobuster |
| Juice Shop (Node.js) | 50 | 4 | nmap, nuclei, sqlmap, searchsploit |
| SSH Server | 5+ | — | nmap, hydra (default creds only), searchsploit |

---

## Features

### Autonomous Pentesting
- Multi-agent AI system orchestrates 18 security tools
- PTES methodology enforced in all planning and execution
- Mid-mission plan adaptation when new findings emerge
- CVE correlation: discovered service versions matched to known exploits
- Custom exploit (POC) generation when standard tools fail

### Manual Mode
- Run any tool directly from the UI without AI orchestration
- Visual pipeline editor: chain tools together (output of one → input of next)
- Dynamic argument forms built from each plugin's configuration

### Learning System
- Persistent memory across missions (JSON on disk, no heavy dependencies)
- Records which tools work for which services, successful exploit chains, OS strategies
- Auto-detects OS from tool output (Linux/Windows/macOS/FreeBSD/embedded)
- False positive detection (repeated low-value findings auto-flagged)
- Agents get richer context with each mission

### Plugin System
- Drop a JSON file into `plugins/` to add a new tool
- Auto-installs in the tools container on next boot
- Ed25519 cryptographic signing for production safety
- 18 tools included: nmap, nuclei, nikto, gobuster, ffuf, hydra, sqlmap, metasploit, searchsploit, wpscan, amass, naabu, whatweb, dirsearch, subfinder, feroxbuster, httpx, testssl

### Smart Routing (LiteLLM)
- Routes to any LLM provider: Ollama, OpenAI, Anthropic, Groq, Azure, etc.
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
│  Web UI (Jinja2 + Tailwind + WebSockets)        │
├─────────────────────────────────────────────────┤
│  FastAPI App Container                          │
│  ├── Mission Manager (orchestration)            │
│  ├── AI Agents (scope, tool selector, exploit)  │
│  ├── LiteLLM Router (model routing)             │
│  ├── Memory System (learning)                   │
│  └── CVE Intelligence (version correlation)     │
├──────────────┬──────────────────────────────────┤
│  PostgreSQL  │  Redis Stack (queue + cache)     │
├──────────────┴──────────────────────────────────┤
│  Tools Container (Kali Linux)                   │
│  ├── Arq Worker (job execution)                 │
│  ├── 18 security tools (auto-installed)         │
│  └── Plugin system (JSON configs)               │
└─────────────────────────────────────────────────┘
```

---

## Configuration

Copy `.env.example` to `.env` and set:

| Variable | Required | Description |
|----------|----------|-------------|
| `AI_PROVIDER` | Yes | `ollama` (local) or `api` (cloud) |
| `OLLAMA_HOST` | If ollama | Ollama server URL (default: `http://ai:11434`) |
| `OLLAMA_MODEL` | If ollama | Model name (default: `qwen2.5:3b`) |
| `LLM_API_KEY` | If api | API key for cloud provider |
| `LLM_API_BASE_URL` | If api | Custom base URL (for OpenRouter, vLLM, etc.) |
| `LLM_MODEL` | If api | Model name (default: `gpt-4o-mini`) |
| `RAG_BACKEND` | No | RAG storage backend: `redis` (default) or `postgres` |

Everything else has sensible defaults. See `.env.example` for the full list.

---

## Testing

```bash
# Unit tests (781 tests, 76% coverage, no Docker needed)
python3 -m pytest tests/unit/ --no-cov

# With coverage
python3 -m pytest tests/unit/

# Lint
ruff check app/
```

### Test Targets

Custom vulnerable containers are included for live testing:

```bash
cd docker/targets
docker compose -f docker-compose.targets.yml up -d
```

| Target | Difficulty | Services | Key Vulns |
|--------|-----------|----------|-----------|
| Easy Web | Easy | HTTP, SSH | Default creds, phpinfo, directory listing |
| Medium Multi | Medium | HTTP, FTP, MySQL, SSH | FTP anon, LFI, weak DB creds |
| Hard Hardened | Hard | HTTPS API, SSH | CORS, SSRF, hidden endpoints, weak JWT |
| DVWA | Easy | HTTP | Classic web vulns (SQLi, XSS, etc.) |
| Juice Shop | Medium | HTTP | OWASP Top 10 |

---

## Documentation

| Document | Description |
|----------|-------------|
| **[Penetration Testing Workflow](docs/pentest.md)** | How Spectra executes pentests phase by phase |
| **[Plugin Guide](docs/plugins.md)** | Creating, configuring, and signing tool plugins |
| **[Architecture](docs/architecture.md)** | Technical deep-dive into the agent system |
| **[API Reference](docs/api_reference.md)** | REST API endpoints |
| **[Deployment](docs/deployment.md)** | Production deployment and scaling |
| **[Roadmap](docs/ROADMAP.md)** | Planned features and improvements |

---

## Project Structure

```
app/
├── api/              # FastAPI routes and schemas
├── core/             # Config, database, security, WebSocket, events
├── models/           # SQLAlchemy database models
├── services/
│   ├── ai/           # LLM clients, agents, consensus, memory, playbooks
│   │   ├── agents/   # Specialized agents (scope, tool_selector, exploit, etc.)
│   │   ├── router.py # LiteLLM smart routing
│   │   ├── memory.py # Persistent cross-mission learning
│   │   ├── playbook.py # Deterministic attack playbooks
│   │   ├── grounding.py # Anti-hallucination framework
│   │   └── cve_intel.py # CVE correlation database
│   ├── mission/      # Mission lifecycle, execution, exploitation
│   ├── tools/        # Tool registry, adapter, parser, installer
│   └── shell/        # Reverse shell session management
├── templates/        # Jinja2 HTML templates
└── static/           # JavaScript and CSS
docker/
├── docker-compose.yml    # Main stack (app, db, redis, tools)
├── targets/              # Vulnerable test containers
├── Dockerfile.app        # FastAPI app image
└── Dockerfile.tools      # Kali tools worker image
plugins/                  # Tool plugin JSON configs (18 included)
tests/                    # 781 unit tests, 76% coverage
docs/                     # Documentation wiki
```

---

## Legal

**Use responsibly.** Only scan targets you own or have explicit written permission to test. Spectra includes safety mechanisms but ultimately you are responsible for how you use it.
