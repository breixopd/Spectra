# Verification — audit claims vs tree (2026-05-01)

## Confirmed in tree

| Audit claim | Evidence |
|-------------|----------|
| Core API `SERVICE_MODE` fail-closed for unknown router policy | `services/api/src/spectra_api/routing.py` — only `""` / `all` / `api` mount full API; else health-only + error log. |
| Duplicate `/api/health` vs `/api/v1/health` | Same `health.router` included under `api_v1` and again with `prefix="/api"`, `include_in_schema=False` in `routing.py` (intentional probe path). |
| CI unit job `--cov=spectra_api` | Aligned with `pyproject`; extended to `--cov=spectra_ai` (aggregate still ≥70%). |
| Ruff beyond `spectra_platform/` + `tests/` | CI lint job includes `services/` and `packages/` (ruff clean as of this run). |

## Semantic code search (`code_research`)

- **health_check**: tooling reported healthy when last checked (2026-05).
- **`code_research`** on health duplication once returned analysis referencing **`spectra_platform/main.py`** and legacy **`SERVICE_MODE`** branches (`ai` / `worker` / `scheduler` / `tools` router modes). That does **not** match current **`spectra_api/routing.py`** (split ASGI apps; fail-closed). Treat that narrative as **index lag** until the indexed repo is refreshed (re-run ingestion on the host that feeds the index). See [`research/03-code-search-index-freshness.md`](../research/03-code-search-index-freshness.md).

## Subagent follow-ups — status

| Area | Action this pass |
|------|------------------|
| **Security — shell** | Documented `run_command_safe` str contract; `CommandBuilder` already `shlex.quote`s targets; parametrized regression tests for metachar targets (`tests/unit/services/test_command_builder.py`). Deeper fuzzing of worker `timeout … {command}` end-to-end remains optional. |
| **Architecture — health** | Verified intentional dual mount; no refactor (would break probes). Shared `packages/` vs monolith kernel: unchanged (strategic). |
| **CI** | Ruff scope expanded; `spectra_ai` in PR coverage gate. **`spectra_scheduler`** not added to aggregate `--cov` (drops total **<70%** with current tests). |
| **Swarm / autoscaling** | Comment block on `docker/docker-compose.swarm.yml` points to external controller pattern + [`research/02-swarm-self-healing-agents.md`](../research/02-swarm-self-healing-agents.md). |

## Commands re-run

```bash
docker compose -f docker/compose.yaml --profile test run --rm unit-test-runner \
  "python -m pytest tests/unit/services/test_command_builder.py -q --override-ini=addopts="
docker compose -f docker/compose.yaml --profile test build unit-test-runner
docker compose -f docker/compose.yaml --profile test run --rm unit-test-runner \
  "python -m pytest tests/unit/ -q --override-ini=addopts= --cov=spectra_platform --cov=spectra_api --cov=spectra_worker --cov=spectra_ai --cov-fail-under=70"
docker run --rm spectra-test-ci python -m ruff check spectra_platform/ tests/ services/ packages/
```

(Adjust image tags if your local `VERSION` differs.)
