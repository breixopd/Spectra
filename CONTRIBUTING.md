# Contributing to Spectra

Thank you for your interest in contributing to Spectra! This guide covers everything you need to get started.

## Table of Contents

- [Development Setup](#development-setup)
- [Architecture Overview](#architecture-overview)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Project Conventions](#project-conventions)

## Development Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Git

### Quick Start

```bash
# Clone the repository
git clone https://github.com/breixopd14/spectra.git
cd spectra

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements-app.txt

# Copy environment file
cp .env.example .env
# Edit .env with your local settings (DATABASE_URL, AI_PROVIDER, etc.)
```

### Running with Docker (recommended)

```bash
# Start all services
docker compose -f docker/docker-compose.yml up -d

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
uvicorn app.main:app --reload --port 5000
```

## Architecture Overview

Spectra follows a layered architecture:

```
app/
├── api/            # HTTP layer — FastAPI routers, Pydantic schemas
│   ├── routers/    # One module per domain (auth, missions, tools, admin/, ...)
│   ├── schemas.py  # Request/response models
│   └── dependencies.py  # FastAPI dependency injection
├── core/           # Infrastructure — config, DB, security, cache, events
├── models/         # Data layer — SQLAlchemy ORM models
├── repositories/   # Data access — Repository pattern CRUD operations
├── services/       # Business logic
│   ├── ai/         # LLM clients, agents (scope, tool_selector, safety, ...)
│   ├── mission/    # Mission lifecycle, execution, steering
│   ├── tools/      # Tool registry, adapters, sandboxes
│   └── ...         # billing, email, gateway, storage, scaling
├── templates/      # Jinja2 HTML templates
├── static/         # CSS, JS, images
└── worker/         # Tools container job queue worker
```

### Key patterns

- **Repository pattern**: All database access goes through `app/repositories/`. Routers and services never query the DB directly (except legacy admin endpoints being migrated).
- **Service layer**: Business logic lives in `app/services/`. Routers are thin — they validate input, call services, and format output.
- **Dependency injection**: FastAPI's `Depends()` for database sessions, auth, and permissions.
- **Plugin system**: Security tools are defined as JSON files in `plugins/`. The registry loads, validates, and manages them.
- **Event-driven**: `app/core/events.py` provides pub/sub for decoupled communication.

## Code Style

### Python

- **Target**: Python 3.11+
- **Linter**: [Ruff](https://docs.astral.sh/ruff/) — run `ruff check app/` before submitting
- **Line length**: 120 characters
- **Formatter**: Ruff formatter or Black (120 line length)
- **Type hints**: Use them for function signatures. `from __future__ import annotations` at the top of new files.
- **Imports**: Use absolute imports (`from app.services.ai import ...`), not relative, except within a package's own submodules.

### Naming conventions

- **Files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions/methods**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE` (defined in `app/core/constants.py`)
- **Route handlers**: Named after their HTTP action (`list_users`, `create_plan`, `get_mission`)

### Commit messages

Use clear, imperative-mood messages:

```
Add sandbox heartbeat monitoring
Fix race condition in mission steering
Refactor admin router into submodules
```

## Testing

### Test structure

```
tests/
├── unit/           # Fast, isolated tests (no DB, no network)
├── integration/    # Tests requiring live services (PostgreSQL, etc.)
├── e2e/            # End-to-end tests (full stack)
├── mocks/          # Shared mock objects
└── conftest.py     # Shared fixtures
```

### Running tests

```bash
# Recommended: containerized unit tests
docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner

# Local unit tests
pytest tests/unit/ -q

# Integration tests (requires running services)
./tests/run_live_tests.sh

# UI tests (requires Playwright)
./tests/run_ui_tests.sh
```

### Test guidelines

- **pytest-asyncio**: Mode is `strict` — all async tests need `@pytest.mark.asyncio`
- **Environment**: Tests load `.env.test` via `pytest-dotenv`. It sets `DATABASE_URL` to SQLite, `AI_PROVIDER=mock`, and `FULLY_AUTOMATED=true`.
- Write tests for behavior, not implementation details
- Don't test what the type system already guarantees
- Unit tests should not require Docker, databases, or network access
- Use fixtures from `conftest.py` for common setup

### Test environment variables

Key variables in `.env.test`:

| Variable | Value | Purpose |
|----------|-------|---------|
| `DATABASE_URL` | `sqlite+aiosqlite:///test.db` | In-memory test database |
| `AI_PROVIDER` | `mock` | Avoids real LLM calls |
| `FULLY_AUTOMATED` | `true` | Skips human approval prompts |
| `JWT_SECRET_KEY` | `test-secret-key` | Deterministic JWT signing |

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

### PR checklist

- [ ] Code follows the project's style guidelines
- [ ] Tests pass locally
- [ ] New functionality includes tests
- [ ] `ruff check app/` reports no errors
- [ ] Documentation updated if needed (wiki, docstrings, README)
- [ ] No hardcoded values — constants go in `app/core/constants.py`
- [ ] No secrets or credentials in code

## Project Conventions

### Adding a new API endpoint

1. Add the route handler in the appropriate router under `app/api/routers/`
2. Define request/response schemas in `app/api/schemas.py`
3. Implement business logic in the relevant service
4. Add database access through a repository if needed
5. Add permission checks via `require_permission()`

### Adding a new security tool plugin

1. Create a JSON file in `plugins/` following the existing schema
2. The tool will auto-load on next restart
3. Optionally sign it with `python scripts/sign_plugin.py`
4. See [Plugin docs](docs/wiki/plugins.md) for the full schema

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
