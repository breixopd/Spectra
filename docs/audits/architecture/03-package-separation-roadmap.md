# Package separation and separation of concerns (roadmap)

This document tracks incremental moves away from “flat” module roots toward clearer package boundaries, without big-bang rewrites.

## Principles

- **Incremental**: one vertical slice at a time (e.g. one router package, or one `app/services/*` subpackage at a time).
- **Test gate**: after each move, `ruff`, unit tests, and the relevant integration slice must pass in Docker.
- **No “compat” shims in app code**: prefer a single import path; update tests and call sites in the same change set.
- **Config stays central**: `app/core/config.py` remains the source of truth; feature packages read settings, they do not define parallel env var stories.

## Suggested order

1. **API routers** — already partially organized under `app/api/routers/`; continue grouping by domain (missions, billing, admin) with `__init__` re-exports only where the app factory expects a stable surface.
2. **Services** — group mission pipeline pieces under `app/services/mission/` (existing), keep `app/services/ai/` for LLM/RAG/embeddings only, and avoid new top-level “god” modules in `app/services/`.
3. **Constants and entitlements** — consolidate plan limits and feature flags in one module (e.g. extend `app/core/constants.py` or add `app/core/entitlements.py`) and import from UI/API layers instead of string literals.
4. **UI templates / static** — keep HTMX partials colocated by feature directory under `app/templates/` to match router names.

## Env and secrets

- **`.env.test`**: local-only, gitignored. Use **`.env.test.example`** in CI and on fresh clones; add real keys only on developer machines or CI secrets (never in git).
- **Embeddings**: with `EMBEDDING_API_KEY` empty and default `EMBEDDING_MODEL=local/...`, embeddings use local fastembed; API path is optional.

## E2E test support code

- Prefer **`tests/e2e/ui/harness/`** (and similar feature-local helpers under `tests/e2e/`) for DB/browser setup, instead of duplicating asyncpg + thread glue in every test file.

## Review cadence

Revisit this file when a new domain (e.g. reporting, compliance exports) would otherwise add more root-level files.
