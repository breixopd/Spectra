# Pytest / integration skip inventory

Why **not** every test runs in the default `lint` + `test` + `integration-test` CI jobs: time, credentials, host tools, and network.

## Design (recommended)

| Layer        | What runs by default        | Prerequisite                          |
|-------------|-----------------------------|----------------------------------------|
| Unit        | `tests/unit/`                | None                                   |
| Integration | `not live and not e2e`       | Postgres stack in Docker job           |
| UI E2E      | `ui-e2e` workflow, path-scoped | Full test stack, Playwright         |
| Live        | `workflow_dispatch` / local | `OPENAI_API_KEY`, `AI_PROVIDER`, etc. |
| Soak/Load   | `run_load_tests.sh`        | Redis, app, optional websockets        |

## Common skip reasons in-repo

| Area | Reason | Unskip by |
|------|--------|-----------|
| `test_agents_integration.py` | Entire module skipped: mock provider story incomplete | Implement mock LLM for agents or re-enable with real stack |
| `test_rag_integration` | `fastembed` or pgvector | Install optional deps; provision pgvector job |
| `test_live_*` / `test_live_scan` | Real LLM or live targets | `live` job + network + API keys + `--profile targets` |
| `test_tool_execution` | nmap/nuclei not installed, or non-root | Tool images / root in runner |
| `test_queue` | DB fixture preconditions | Fix env / ordering |
| `e2e` without `DATABASE_URL` | Seeding in Playwright | Run inside `ui-test-runner` (provides DSN) |
| `importorskip(websockets)` | Optional package | `pip install websockets` in runner image |

## Seeing all skip reasons

```bash
python -m pytest -ra tests/
```

Treating “run **every** test in one job” as default will mix **minutes-long** network tests with **sub-second** unit tests and is discouraged; use **markers** and **layered workflows** (see `05-test-coverage-flakiness-benchmarks.md`).
