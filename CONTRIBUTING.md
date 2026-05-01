# Contributing to Spectra

Thank you for your interest in contributing to Spectra! This guide covers everything you need to get started.

## Table of Contents

- [Development Setup](#development-setup)
- [Architecture Overview](#architecture-overview)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [PR Review Checklist](#pr-review-checklist)
- [Security](#security)
- [Project Conventions](#project-conventions)

## Development Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose v2+
- Git

### Quick Start

```bash
# Clone the repository
git clone https://github.com/breixopd14/spectra.git
cd spectra

# Copy environment file
cp .env.example .env
# Edit .env with your local settings (DATABASE_URL, TENSORZERO_GATEWAY_URL, etc.)
```

### Using the Makefile

The project includes a Makefile with common developer targets. Run `make help` to see all options:

```bash
make help            # Show all available targets
make test            # Run unit tests (default target)
make test-unit       # Run unit tests in Docker
make test-integration # Run integration tests
make test-performance # Run performance smoke harness
make test-load       # Run load/rate-limit harness
make test-soak       # Run soak/stability harness
make test-live-smoke # Run live API/UI/LLM smoke tests
make test-coverage   # Run unit tests with coverage report
make lint            # Run import boundary check + ruff linter
make format          # Format code with ruff
make check           # Run lint + import boundaries + unit tests
make clean           # Remove caches and build artifacts
make css-build       # Build Tailwind CSS (minified)
make css-build-prod  # Build CSS with PostCSS pipeline (autoprefixer + cssnano)
make css-watch       # Watch and rebuild CSS on changes
make docker-build    # Build Docker images
make docker-up       # Start all services via Docker Compose
make docker-down     # Stop all services
make import-boundaries # Check import boundary enforcement
```

### Pre-commit Hooks

After cloning, install pre-commit hooks to catch issues before pushing:

```bash
pip install pre-commit
pre-commit install
```

The hooks (configured in `.pre-commit-config.yaml`) run on every commit:

| Hook | What it does |
|------|-------------|
| `trailing-whitespace` | Removes trailing whitespace |
| `end-of-file-fixer` | Ensures files end with a newline |
| `check-yaml` | Validates YAML syntax |
| `check-added-large-files` | Prevents large files from being committed |
| `ruff` | Lints and auto-fixes Python code |
| `ruff-format` | Formats Python code |
| `check-import-boundaries` | Enforces shared/service import boundaries |

To run all hooks manually:

```bash
pre-commit run --all-files
```

### Running with Docker (recommended)

```bash
# Start all services
docker compose -f docker/compose.yaml up -d

# The app is at http://localhost:5000
# First run redirects to /setup for admin account creation
```

### Running locally (without Docker)

```bash
# Start PostgreSQL (must have pgvector extension)
# Update DATABASE_URL in .env to point to your local DB

# Run migrations
alembic upgrade head

# Start the dev server
uvicorn spectra_api.main:app --reload --port 5000
```

## Architecture Overview

Spectra follows a layered architecture with **four deployable services**. Each
image sets `SERVICE_MODE` for shared settings (`app.core.config`); the Core API
process (`spectra_api`) additionally uses it for router mounting — see
`docs/wiki/microservices-split.md`.

```text
app/
├── _meta/            # App metadata (version, build info)
├── api/              # HTTP layer — FastAPI routers, Pydantic schemas
│   ├── routers/      # One module per domain (auth, missions, tools, admin/, ...)
│   ├── schemas/      # Request/response models
│   └── dependencies.py  # FastAPI dependency injection
├── core/             # Infrastructure — config, DB, security, cache, events, redis
├── models/           # Data layer — SQLAlchemy ORM models
├── repositories/     # Data access — Repository pattern CRUD operations
├── services/
│   ├── ai/           # LLM clients, agents, RAG (shared by API + worker)
│   ├── mission/      # Mission lifecycle, execution, steering
│   ├── tools/        # Tool registry, adapters, sandboxes
│   └── ...           # billing, email, gateway, scaling, storage, etc.
└── utils/            # Shared utilities

packages/
├── common/           # spectra_common shared primitives
├── domain/           # spectra_domain integration contracts
└── tools-core/       # spectra_tools_core registry contracts

services/
├── api/              # `spectra_api` package + API-owned UI assets/templates
├── ai/               # spectra_ai HTTP service entry point
├── scheduler/        # spectra_scheduler background service entry point
└── worker/           # spectra_worker job queue consumer

plugins/              # Tool plugin JSON configs
config/               # Build configs (tailwind, postcss)
docker/               # Docker Compose files, Dockerfiles, Caddyfile
scripts/              # Ops scripts, test runners
tests/                # Unit, integration, e2e, load tests
```

### Key patterns

- **Repository pattern**: All database access goes through `app/repositories/`. Routers and services never query the DB directly.
- **Service layer**: Business logic lives in `app/services/`. Routers are thin — they validate input, call services, and format output.
- **Dependency injection**: FastAPI's `Depends()` for database sessions, auth, and permissions.
- **Plugin system**: Security tools are defined as JSON files in `plugins/`. The registry loads, validates, and manages them.
- **Event-driven**: `app/core/events.py` provides pub/sub for decoupled communication.

### Architecture Boundaries

Spectra runs as four microservices; `SERVICE_MODE` labels each container for shared config. Import boundaries between shared and service-specific code are enforced.

**Shared packages** (used by all services — must NOT import service-specific code):
- `app/core/` — config, database, security, cache, events, redis
- `app/models/` — SQLAlchemy ORM models
- `app/repositories/` — data access layer
- `packages/common/src/spectra_common/` — shared primitives
- `packages/domain/src/spectra_domain/` — integration contracts and DTOs
- `packages/tools-core/src/spectra_tools_core/` — tool registry contracts

**Service-specific packages** (only loaded by their respective service):
- `services/api/src/spectra_api/` — routers, schemas, bootstrap, UI, API-owned settings/setup services
- `services/worker/src/spectra_worker/` — job queue consumer (Worker package; image CMD `uvicorn spectra_worker.main:app`)
- `services/ai/src/spectra_ai/main.py` — AI service entry point (image: `uvicorn spectra_ai.main:app`)
- `services/scheduler/src/spectra_scheduler/main.py` — Scheduler entry point (image: `uvicorn spectra_scheduler.main:app`)
- `services/worker/src/spectra_worker/__main__.py` — Worker HTTP + queue loops

**Verify boundaries before submitting a PR:**

```bash
python3 scripts/check_import_boundaries.py
```

This checks that `app/core/` and `app/models/` have no top-level imports of service-specific modules (`spectra_api.api`, `spectra_worker`, `spectra_ai`, `spectra_scheduler`, etc.). Lazy imports inside functions are allowed.

The pre-commit hook also runs this check automatically on every commit (see [Pre-commit Hooks](#pre-commit-hooks)).

### Per-Service Requirements

When adding a dependency, add it to the correct requirements file:

| File | Service | When to Edit |
|------|---------|--------------|
| `requirements/base.txt` | All services | Core deps (SQLAlchemy, asyncpg, pydantic) |
| `requirements/app.txt` | API | Web UI, reports, full API stack |
| `requirements/ai.txt` | AI Service | LLM providers, embeddings, fastembed |
| `requirements/scheduler.txt` | Scheduler | Scheduling, lightweight background tasks |
| `requirements/worker.txt` | Worker | Tool execution, Docker SDK, parsing |
| `requirements/dev.txt` | Development | pytest, ruff, dev-only tools |

## Code Style

### Python

- **Target**: Python 3.11+
- **Linter**: [Ruff](https://docs.astral.sh/ruff/) — the single source of truth for linting and formatting
- **Line length**: 120 characters
- **Formatter**: `ruff format` (120 line length)
- **Type hints**: Use them for function signatures. `from __future__ import annotations` at the top of new files.
- **Imports**: Use absolute imports from concrete modules (for example `from app.services.ai.agents.base import AgentContext`), not relative, except within a package's own submodules. Prefer specific subpackages (`agents`, `consensus`, `memory`, …) rather than importing from `app.services.ai` as a catch-all umbrella.

### Running the linter

```bash
# Check for lint errors
ruff check app/

# Auto-fix what ruff can fix
ruff check app/ --fix

# Format code
ruff format app/ tests/

# Or use the Makefile shortcuts
make lint     # ruff check + import boundary check
make format   # ruff format app/ tests/
```

### CSS and Frontend

When modifying CSS or templates, rebuild the Tailwind output:

```bash
# Development: watch for changes
make css-watch

# Production: full PostCSS pipeline (autoprefixer + cssnano)
make css-build-prod

# Quick build (Tailwind only, minified)
make css-build
```

The source file is `services/api/static/css/input.css`. Custom properties (design tokens) are defined in `:root`. Component classes use `@layer components`. See [Design Tokens](docs/wiki/design-tokens.md) for the full token reference.

### Naming conventions

- **Files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions/methods**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE` (defined in `app/core/constants.py`)
- **Route handlers**: Named after their HTTP action (`list_users`, `create_plan`, `get_mission`)

### Commit messages

Use clear, imperative-mood messages:

```text
Add sandbox heartbeat monitoring
Fix race condition in mission steering
Refactor admin router into submodules
```

## Testing

### Test structure

```text
tests/
├── unit/           # Fast, isolated tests (no DB, no network)
├── integration/    # Tests requiring live services (PostgreSQL, etc.)
├── e2e/            # End-to-end tests (full stack, Playwright)
├── mocks/          # Shared mock objects
└── conftest.py     # Shared fixtures
```

### Test categories

| Category | Command | What it covers |
|----------|---------|---------------|
| **Unit** | `make test-unit` or `./scripts/test.sh unit` | Fast, isolated tests with no external dependencies |
| **Integration** | `make test-integration` or `./scripts/test.sh integration` | Tests requiring live PostgreSQL, Redis, etc. |
| **E2E** | `./tests/run_ui_tests.sh` | Playwright browser tests against running app |
| **Performance** | `make test-performance` or `./tests/run_load_tests.sh performance` | Performance smoke harness |
| **Load** | `make test-load` or `./tests/run_load_tests.sh load` | Burst/load and rate-limit harness |
| **Soak** | `make test-soak` or `./tests/run_load_tests.sh soak` | Mixed-traffic soak/stability harness |
| **Live smoke** | `make test-live-smoke` or `START_STACK=1 ./scripts/test.sh live-smoke` | API/UI/LLM smoke tests against running stack |

### Running tests

```bash
# --- Unit tests (fast, no services needed) ---

# Via Makefile (recommended)
make test                            # Runs unit tests in Docker

# Run a specific test file
./scripts/test.sh file tests/unit/test_middleware_stack.py

# --- Integration tests (requires running PostgreSQL, etc.) ---
./tests/run_live_tests.sh

# --- Containerized test runner via docker-compose ---
docker compose -f docker/compose.yaml --profile test run --rm settings-test-runner

# --- UI tests (requires Playwright) ---
./tests/run_ui_tests.sh

# --- Coverage report ---
make test-coverage
```

### Test guidelines

- **pytest-asyncio**: Mode is `strict` — all async tests need `@pytest.mark.asyncio`
- **Environment**: Create `.env.test` with `cp .env.test.example .env.test` (add optional API keys locally). The file is **gitignored**; CI copies the example when needed. Tests load the same file for `DATABASE_URL`, `TENSORZERO_GATEWAY_URL`, etc. Mission approval behavior uses per-user defaults and per-launch payloads; integration tests rarely need this. Unit tests patch `settings.REQUIRE_APPROVAL` only when exercising the env kill-switch path.
- Write tests for behavior, not implementation details
- Don't test what the type system already guarantees
- Unit tests should not require Docker, databases, or network access
- Use fixtures from `conftest.py` for common setup

### Test environment variables

Do not commit `.env.test`. Track **`.env.test.example`** only; add secrets on your machine or in CI from the environment.

Key variables in `.env.test`:

| Variable                 | Value                                                                   | Purpose                           |
| ------------------------ | ----------------------------------------------------------------------- | --------------------------------- |
| `DATABASE_URL`           | `postgresql+asyncpg://spectra:spectra_test@localhost:5433/spectra_test` | Shared PostgreSQL test database   |
| `TENSORZERO_GATEWAY_URL` | `http://tensorzero:3000`                                                | TensorZero gateway for AI routing |
| `JWT_SECRET_KEY`         | `test-secret-key`                                                       | Deterministic JWT signing         |
| `OPENAI_API_KEY`         | *(empty or your key)*                                                   | Live LLM tests (e.g. OpenRouter)  |
| `EMBEDDING_API_KEY`      | *(empty for local fastembed)*                                           | RAG/embedding tests               |

## Pull Request Process

1. **Branch**: Create a feature branch from `main` (`feature/your-feature` or `fix/your-fix`)
2. **Implement**: Make your changes following the code style guidelines
3. **Test**: Ensure all existing tests pass and add tests for new functionality
4. **Lint**: Run `ruff check app/` and fix any issues
5. **Commit**: Use clear commit messages
6. **PR**: Open a pull request against `main` with:
   - A clear description of what changed and why
   - Link to any related issues
   - Screenshots for UI changes
7. **Review**: Address review feedback promptly

### PR Review Checklist

Use this checklist when reviewing pull requests:

- [ ] **Code quality**: Follows project style, clear naming, no dead code
- [ ] **Tests**: New functionality has tests; all existing tests pass
- [ ] **Lint clean**: `ruff check app/` reports no errors
- [ ] **Import boundaries**: `python3 scripts/check_import_boundaries.py` passes
- [ ] **Security**: No hardcoded secrets, no SQL injection, no XSS vectors
- [ ] **Constants**: No magic numbers — constants go in `app/core/constants.py`
- [ ] **Type hints**: Function signatures include type hints
- [ ] **Documentation**: Docstrings for public APIs; wiki updated if needed
- [ ] **Migrations**: Schema changes have an Alembic migration
- [ ] **Backwards compatibility**: API changes are backwards-compatible or versioned
- [ ] **Error handling**: Appropriate error responses for user-facing endpoints
- [ ] **CSS rebuilt**: If templates or `input.css` changed, run `make css-build-prod`
- [ ] **Pre-commit**: `pre-commit run --all-files` passes

## Security

### Reporting Vulnerabilities

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, report security issues by emailing the maintainers directly. Include:

1. Description of the vulnerability
2. Steps to reproduce
3. Potential impact assessment
4. Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a timeline for resolution.

### Security Guidelines for Contributors

- Never commit secrets, API keys, or credentials to the repository
- Use `SecretStr` from Pydantic for sensitive config values
- All user input must be validated at API boundaries (Pydantic schemas)
- Use parameterized queries — never concatenate user input into SQL
- Follow the OWASP Top 10 guidelines
- Run `ruff check app/` to catch common security anti-patterns
- Test authentication/authorization paths in your changes

## Project Conventions

### Adding a new API endpoint

1. Add the route handler in the appropriate router under `services/api/src/spectra_api/api/routers/`
2. Define request/response schemas under `services/api/src/spectra_api/api/schemas/` (or the router-local `schemas` module)
3. Implement business logic in the relevant service
4. Add database access through a repository if needed
5. Add permission checks via `require_permission()`

### Adding a new security tool plugin

1. Create a JSON file in `plugins/` following the existing schema
2. The tool will auto-load on next restart
3. See [Plugin docs](docs/wiki/plugins.md) for the full schema

### Database migrations

```bash
# Create a new migration after modifying models
alembic revision --autogenerate -m "description of change"

# Apply migrations
alembic upgrade head
```

### Environment variables

- All configuration goes through `app/core/config.py` (the `settings` object)
- Never hardcode configuration values
- New settings need a default value and documentation in the wiki

## Getting Help

- Check the [Documentation Wiki](docs/wiki/home.md) for detailed guides
- Look at existing code for patterns and conventions
- Open an issue for bugs or feature requests
