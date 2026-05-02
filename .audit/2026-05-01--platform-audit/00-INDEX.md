# Platform audit — 2026-05-01

## Artifacts

| Doc | Purpose |
|-----|---------|
| [00-SCOPE.md](./00-SCOPE.md) | In/out, git context |
| [progress.md](./progress.md) | Checklist |
| [research/01-swarm-self-healing-agents.md](./research/01-swarm-self-healing-agents.md) | External links + Swarm/agent memory |
| [research/02-chunkhound-index.md](./research/02-chunkhound-index.md) | Chunkhound snapshot lag vs current routing |
| [plan/01-improvement-plan.md](./plan/01-improvement-plan.md) | Prioritised backlog |
| [verification/01-reconciliation.md](./verification/01-reconciliation.md) | Code vs audit claims + commands re-run |
| [subagents/01-notes.md](./subagents/01-notes.md) | Subagent summaries |

## Code / CI changes (this engagement)

- **Routing:** `SERVICE_MODE` unknown → health-only (fail closed); removed dead `ai`/`worker`/`scheduler`/`tools` router branches from `spectra_api` (split images use separate ASGI apps). See `20758ab` and related docs/wiki edits.
- **CI unit job:** `--cov=spectra_api` (earlier) + **`--cov=spectra_ai`**; lint **`ruff check spectra_platform/ tests/ services/ packages/`**.
- **Release workflow:** unit coverage flags aligned with CI (includes `spectra_ai`).
- **Local defaults:** `pyproject.toml` `addopts` + `[tool.coverage.run] source` include `spectra_ai`.
- **Swarm file:** header comment on autoscaling / health vs restart policy (see research/01).
- **Shell / builder:** executor docstring; parametrized `CommandBuilder` metachar target tests.

## OPEN

- Worker-level fuzz / property tests for full `timeout -k … {command}` strings (beyond `CommandBuilder`) — still optional; requires dependency/policy choice.
- **Nightly extended gate:** `.github/workflows/nightly-extended.yml` runs weekly + `workflow_dispatch` → `scripts/runbooks/ci-parity.sh all` (static + unit + settings + integration). Compose-smoke / Playwright remain on main/develop push path.
- **`spectra_scheduler` in aggregate `--cov`** only after tests raise line rate (gate stays ≥70%).
- Chunkhound **re-index** — operator action on Chunkhound project when indices drift from `main`.

## Re-run

After edits under `services/api/src/spectra_api/`, rebuild the test image so the container matches host (`docker compose ... build unit-test-runner`). Bind-mounting only `spectra_platform/` in compose does not refresh `spectra_api` in the default unit runner.

```bash
docker compose -f docker/compose.yaml --profile test build unit-test-runner
docker compose -f docker/compose.yaml --profile test run --rm unit-test-runner \
  "python -m pytest tests/unit/ -q --override-ini=addopts= --cov=spectra_platform --cov=spectra_api --cov=spectra_worker --cov=spectra_ai --cov-report=term-missing --cov-fail-under=70"
```
