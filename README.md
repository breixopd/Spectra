# Spectra: AI-Driven Security Assessment Platform

Spectra is a next-generation **Multi-Agent System (MAS)** for automated security assessments. It leverages the **MAKER Framework** (Maximal Agentic decomposition, K-threshold Error mitigation, and Red-flagging) to orchestrate industry-standard security tools with human-level reasoning and machine-speed execution.

---

## Documentation

- **[Penetration Testing Workflow](docs/pentest.md)** - Complete guide to how Spectra executes pentests
- **[Plugin Configuration Guide](docs/plugins.md)** - Documentation for creating and configuring tool plugins
- **[Design System](docs/design_system.md)** - Architecture and component design
- **[API Reference](docs/api_reference.md)** - Detailed API documentation
- **[Deployment Guide](docs/deployment.md)** - Deployment and scaling instructions

---

## Core Architecture

### The MAKER Framework

Spectra decomposes complex security tasks into specialized agents:

1. **Recon Swarm:**
    - `ScopeAgent`: Defines strict assessment boundaries.
    - `ToolSelector`: Chooses the optimal tool for the specific context.
2. **Analysis Swarm:**
    - `VotingSystem`: Uses K-Threshold consensus (multiple models voting) to validate findings and reduce false positives.
    - `RiskScorer`: Contextual risk assessment.
3. **Exploitation Swarm:**
    - `ExploitCrafter`: Iterative exploitation with adaptive retry strategies.
    - `PayloadCrafter`: Generates tailored exploits using SearchSploit and CVE data.
    - `SafetySupervisor`: Intercepts and blocks dangerous commands (e.g., `rm -rf`).
4. **Strategic Swarm:**
    - `MissionController`: High-level planning and steering.
    - `PostExploitation`: Plans privilege escalation, persistence, and lateral movement.

### Quality Gates (Consensus Validation)

Spectra validates decisions at **5 quality gates** to ensure high-quality autonomous operation:

| Gate | Trigger | Validation Level |
|------|---------|------------------|
| **PLAN** | Initial mission planning | 3 voters, need 2, 70% confidence |
| **TOOL_SELECTION** | Each tool selection | 2 voters, need both, 50% confidence |
| **PAYLOAD** | Exploit/payload crafting | 3 voters, need 2, 70% confidence |
| **REPLAN** | Plan changes due to errors | 3 voters, need 2, 60% confidence |
| **EXECUTION** | High-risk tool execution | 3 voters, need all 3, 80% confidence |

This ensures even low-risk decisions that could derail the mission are validated.

### Technology Stack

- **Backend:** Python 3.11+, FastAPI, Arq (Redis Queue).
- **AI:** Ollama (Local Inference), OpenAI (Cloud Fallback), LangChain (Orchestration).
- **Data:** PostgreSQL (Persistence), Redis (Vector Store & Cache).
- **Frontend:** Modern Web UI with WebSockets for real-time feedback.
- **Infrastructure:** Docker Compose (Microservices).

---

## Tool Integration

Spectra uses a **Dynamic Plugin System** to integrate tools. Tools are defined in JSON configuration files (`plugins/*.json`) and executed via a generic adapter.

**Plugin Safety:**
All plugins are cryptographically signed using Ed25519. The system enforces signature verification in production to prevent tampering.

- **Safe Mode:** Enabled by default. Only signed plugins can be loaded.
- **Hot Loading:** Drop a new `.json` file into `plugins/` to instantly register a new tool.

**Default Tools:**

| Category        | Tools                                      |
| --------------- | ------------------------------------------ |
| **Discovery**   | Nmap, Naabu, Amass                         |
| **Enumeration** | Ffuf, Gobuster                             |
| **Web**         | Nikto, WPScan                              |
| **Vulnerability** | Nuclei                                   |
| **Exploitation** | SearchSploit, Metasploit, SQLMap, Hydra  |

---

## Setup & Installation

1. **Environment Setup:**
    Copy the example environment file and configure it:

    ```bash
    cp .env.example .env
    # Edit .env with your configuration
    ```

    **Note:** `.env.test` is only for running tests and already contains test configurations.

2. **Start Services:**

    ```bash
    cd docker
    docker compose up -d
    ```

    For development with hot-reloading:

    ```bash
    docker compose up --watch
    ```

3. **Access Points:**
    - **Web UI:** `http://localhost:5000/dashboard`
    - **API Docs:** `http://localhost:5000/docs`
    - **Redis Insight:** `http://localhost:8001/`

---

## Configuration

Configuration is managed via environment variables. Copy `.env.example` to `.env` and customize the following:

### Required Settings

- **`DATABASE_URL`**: PostgreSQL connection string
  - Default: `postgresql+asyncpg://spectra:spectra_dev@db:5432/spectra`
- **`REDIS_PASSWORD`**: Redis password (change in production!)
  - Default: `changeme`
- **`JWT_SECRET_KEY`**: Secret for authentication tokens (change in production!)
  - Default: `change-me-in-production`

### AI Configuration

- **`AI_PROVIDER`**: AI backend to use
  - Options: `ollama` (local) or `api` (cloud/remote)
  - Default: `ollama`

**For Local AI (Ollama):**

- **`OLLAMA_HOST`**: Ollama server URL
  - Default: `http://ai:11434`
- **`OLLAMA_MODEL`**: Model to use
  - Default: `qwen2.5:3b`

**For Cloud API (OpenAI, OpenRouter, vLLM, LocalAI, etc.):**

- **`LLM_API_KEY`**: Your API key (required if using `api` provider)
- **`LLM_API_BASE_URL`**: API endpoint (optional)
  - Use for OpenRouter, vLLM, LocalAI, etc.
  - Example: `https://openrouter.ai/api/v1`
- **`LLM_MODEL`**: Model to use
  - Default: `gpt-4o-mini`
  - OpenRouter example: `qwen/qwen-2.5-coder-7b-instruct:free`

### Optional Settings

- **`LOG_LEVEL`**: Logging verbosity (`DEBUG`, `INFO`, `WARNING`)
- **`DEBUG`**: Enable debug mode (`true`/`false`)
- **`PLUGIN_SAFE_MODE`**: Block dangerous tool commands (`true`/`false`)

---

## Development

### Running Tests

Tests are run inside the Docker container to ensure environment consistency.

```bash
cd docker

# Run all tests (221+ tests)
docker compose run --rm app pytest

# Run E2E tests (mission workflow, steering, safety)
docker compose run --rm app pytest tests/e2e/ -v

# Run UI tests
docker compose run --rm -e BASE_URL=http://app:5000 app pytest tests/e2e/test_ui_flow.py

# Run Plugin Safety tests
docker compose run --rm app pytest tests/unit/test_plugin_safety.py

# Run live target tests (requires docker-compose.test.yml)
docker compose -f docker-compose.test.yml run --rm test-runner
```

### Test Coverage

| Category | Tests | Description |
|----------|-------|-------------|
| **Unit Tests** | 140+ | Individual component testing |
| **E2E Tests** | 60+ | End-to-end workflow testing |
| **Integration** | 15+ | Container and plugin integration |

### Project Structure

- `app/`: Main application code (FastAPI).
- `docker/`: Docker configuration files.
- `docs/`: Documentation.
- `plugins/`: Tool configuration files (JSON).
- `tests/`: Unit and integration tests.
- `alembic/`: Database migrations.

---

## Security

Spectra is a powerful security tool. **Use responsibly.**

- **Authorization:** Only scan targets you own or have explicit permission to test.
- **Safety:** The `SafetySupervisor` agent is enabled by default to prevent accidental damage.
- **Sandboxing:** Tools run in an isolated container.

---

## UI Features

### Global Status Bar

The UI includes a status bar that shows system initialization progress:

- **Tool Installation:** Progress of installing security tools
- **Embedding Loading:** AI model loading status
- **Database/Redis Health:** Connection status

### Settings Page

The settings page (`/settings`) includes:

- **AI Configuration:** Configure Ollama or Cloud API providers
- **Data Management:**
  - Clear tool statistics
  - Clear mission history (with confirmation)
  - Clear Redis cache
  - Reinstall all tools
- **System Status:** Real-time component health monitoring

### Plugin Creator

Create custom tool plugins at `/toolbox` → "Create New Plugin":

- **Visual Editor:** Form-based plugin configuration
- **JSON Preview:** Real-time config preview
- **Plugin Signing:**
  - Server key signing (DEBUG mode only)
  - Custom key upload for official/dev signing
  - Save unsigned (when safe_mode disabled)

---

## API Features

### System Status API

```
GET /api/system/status
```

Returns comprehensive system status including:

- Database and Redis health
- Tool installation progress
- Ongoing operations
- Overall system readiness

### Data Management APIs

```
POST /api/system/clear/tools     # Clear tool statistics
POST /api/system/clear/missions  # Clear missions (requires ?confirm=true)
POST /api/system/clear/cache     # Clear Redis cache
```

All require superuser authentication.
