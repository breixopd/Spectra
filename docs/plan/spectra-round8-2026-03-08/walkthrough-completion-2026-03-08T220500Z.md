# Round 8 Completion

## Overview

Round 8 aligned Spectra with the clarified LLM architecture: runtime LLM configuration stays DB-managed, non-Ollama cloud execution now uses one LiteLLM-backed concept, and the setup/settings/operator docs were updated to match that model.

## Completed Work

- Unified legacy `api` inputs and runtime normalization into LiteLLM-backed cloud semantics while keeping `ollama` and `mock` distinct.
- Kept `SystemConfig` authoritative for runtime LLM behavior and preserved compatibility reads for legacy values.
- Updated setup, settings, status, and test-connection flows so the UI no longer presents separate `api` and `litellm` cloud choices.
- Stabilized Docker-backed browser tests and cleaned up the UI bootstrap/auth fixture path.
- Expanded the future roadmap to describe a single-node-first deployment path, then staged movement of tools, RAG, and other services to separate nodes managed from the UI.
- Fixed remaining actionable workflow, Alembic, router, and UI-test diagnostics tied to this round of work.

## Validation

- `docker compose -f docker/docker-compose.test.yml run --rm settings-test-runner`
  Result: 50 passed
- `./tests/run_ui_tests.sh`
  Result: 14 passed

## Outcomes

- The product now models one LiteLLM-backed cloud provider path instead of parallel `api` and `litellm` semantics.
- First-run setup and post-setup settings are aligned with DB-managed runtime LLM state.
- The operator roadmap now documents the intended progression from one server to UI-managed split-node infrastructure.

## Residual Notes

- `.github/workflows/release.yml` still shows local validator warnings for secret names such as `DEPLOY_HOST`; those are schema/tooling warnings about unknown repository secrets rather than broken workflow syntax.