# Readability, modularity, and structure

This document is **Spectra-specific**: it ties general practice to our layout (`packages/platform/src/spectra_platform/`, `services/*/`, `packages/`) and to how we ship (Docker, Ruff, CI). It is not a second style guide — **Ruff + PEP 8** remain authoritative for formatting and many lint rules.

## Principles (short)

1. **Code is read more than it is written** — prefer boring, explicit names over clever abstractions ([PEP 8](https://peps.python.org/pep-0008/), Zen of Python).
2. **One obvious place** — a function or module should answer one question. If a file mixes unrelated HTTP concerns or unrelated domain workflows, split when you touch it (see “When to split” below).
3. **Shallow beats deep** — reduce nesting with early returns and small helpers. Four levels of `if` / `try` / `for` in one block is a smell.
4. **Interfaces, not glob imports** — import concrete modules (`from app.services.ai.agents.base import AgentContext`), as in [CONTRIBUTING.md](../../CONTRIBUTING.md#python).
5. **Dependencies flow inward** — shared `spectra_platform` (under `packages/platform/src/`) and `packages/*` must not import service-only code (`spectra_api.api.*`, worker entrypoints, etc.). Run `python scripts/check_import_boundaries.py`.

Modular organisation (independent files, clear boundaries, testable units) is summarised well in [A practical guide to writing modular Python code](https://derekarmstrong.dev/blog/a-practical-guide-to-writing-modular-python-code/) — use it as background reading, not an extra rule layer.

## Where code lives

| Layer | Location | Responsibility |
| --- | --- | --- |
| Domain, DB models, shared services | `packages/platform/src/spectra_platform/` (`import spectra_platform`) | Business logic, ORM; workers + API consume this |
| HTTP API + UI templates/static | `services/api/src/spectra_api/` | FastAPI app, routers, bootstrap, Jinja, JS |
| Other deployables | `services/{worker,ai,scheduler}/` | Thin service entrypoints; call into `spectra_platform` (Python) from `packages/platform` |
| Cross-repo primitives | `packages/common`, `packages/domain`, … | No imports from `app.services.*` upward |

**HTTP routers and API-only schemas** live under `spectra_api`, not under `spectra_platform/api/` (legacy layout is gone). When you add an endpoint, colocate it with the domain it serves; if a router file grows past roughly **600–800 lines** or mixes admin CRUD + infra + unrelated domains, split by **router include** (`APIRouter` per submodule) rather than growing one file.

## Async and performance (readability + correctness)

- **Async handlers** should not run long CPU work or blocking I/O on the event loop. Prefer `asyncio.to_thread()` or an async-native client when touching the filesystem, heavy parsing, or synchronous SDKs from `async def` routes.
- If a function is `async` only to `await` one call at the end, consider whether it should be sync — unnecessary `async` spreads confusion.

## When to split a module (practical thresholds)

Use judgment, not dogma:

- **Routers**: multiple unrelated URL prefixes or “admin servers + Swarm + images + rollback” in one file → split into sub-routers included from a thin `__init__.py`.
- **Services**: one public class or module-level API per file is easier to navigate than many unrelated helpers in one giant module.
- **Lifespan / factory**: keep startup linear and short; move each init step to a named `async def _init_foo(app)` in the same package or `bootstrap/` helpers.

Compat and cleanup backlog items are tracked in [Legacy cleanup backlog](../runbooks/legacy-cleanup-backlog.md).

## Tooling (already enforced)

- **Ruff** — format + lint (`ruff check`, `ruff format`). Line length **120** (see `pyproject.toml`).
- **CI** — `.github/workflows/ci.yml` **static-analysis** job builds `Dockerfile.test` once per run, then Ruff, import boundaries, Pyright, and Bandit (avoids three duplicate image builds on separate runners).
- **Pyright** — same job; add types on new public functions. Defaults in `pyproject.toml` (`[tool.pyright]`).
- **pip-audit** — see [Pre-release gate](../runbooks/pre-release-gate.md).

## What we avoid

- **Abstraction for its own sake** — no new base classes or “plugin architecture” unless several call sites need it.
- **Dual paths** — one way to do things after a migration (no internal legacy shims unless an external contract forces versioning).
- **Comments that repeat the code** — prefer a clearer name or a one-line docstring on *why*, not *what*.

## Related docs

- [CONTRIBUTING.md](../../CONTRIBUTING.md) — PR flow, testing, code style bullets
- [Development wiki](../wiki/development.md) — local setup
- [Testing strategy](../wiki/testing-strategy.md) — verification matrix
- [Runbooks: CI parity](../runbooks/ci-parity-local.md) — merge gate commands
