# CI parity (local or VPS)

This runbook reproduces the **merge gate** from `.github/workflows/ci.yml` on any machine with Docker: **lint**, **typecheck**, **unit tests with coverage floor**, and **settings** runner. Optionally run **integration** tests the same way CI does.

## Prerequisites

- Docker and Docker Compose v2
- Repository cloned; working directory = repo root
- `.env.test` present (the script creates it from `.env.test.example` if missing)

## Recommended: scripted gate

```bash
chmod +x ./scripts/runbooks/ci-parity.sh   # once per clone
./scripts/runbooks/ci-parity.sh ci
```

Modes:

| Command | Matches |
| --- | --- |
| `./scripts/runbooks/ci-parity.sh lint` | CI `lint` job (ruff + import boundaries) |
| `./scripts/runbooks/ci-parity.sh type` | CI `type-check` job (pyright) |
| `./scripts/runbooks/ci-parity.sh unit` | CI TensorZero parse + unit + coverage ≥70% |
| `./scripts/runbooks/ci-parity.sh settings` | CI settings-test-runner |
| `./scripts/runbooks/ci-parity.sh integration` | CI `integration-test` job |
| `./scripts/runbooks/ci-parity.sh ci` | lint + type + unit + settings |
| `./scripts/runbooks/ci-parity.sh all` | `ci` + integration |

Environment:

- `ENCRYPTION_KEY` — defaults to `test-encryption-key` (same idea as CI).
- `SKIP_PYRIGHT=1` — skip Pyright for a quicker loop.
- `COMPOSE_DOWN=1` — after `all`, tear down compose profiles (optional cleanup).

## Manual equivalents (copy from CI)

If you cannot use the script, these are the same steps as the workflow file.

**Lint image**

```bash
docker build -f docker/Dockerfile.test -t spectra-test-ci .
docker run --rm spectra-test-ci python -m ruff check app/ tests/ services/ packages/
docker run --rm spectra-test-ci python scripts/check_import_boundaries.py
```

**Pyright**

```bash
docker run --rm spectra-test-ci sh -c "pip install --no-cache-dir pyright && pyright"
```

**Unit + coverage + settings**

```bash
test -f .env.test || cp .env.test.example .env.test
export ENCRYPTION_KEY=test-encryption-key
docker compose -f docker/compose.yaml --profile test build unit-test-runner
docker compose -f docker/compose.yaml --profile test run --rm --no-deps unit-test-runner \
  "python -c \"import tomllib; tomllib.load(open('config/tensorzero.toml', 'rb')); print('tensorzero.toml: valid')\""
docker compose -f docker/compose.yaml --profile test run --rm unit-test-runner \
  "python -m pytest tests/unit/ -q --override-ini=addopts= --cov=app --cov=spectra_api --cov=spectra_worker --cov=spectra_ai --cov=spectra_scheduler --cov-report=term-missing --cov-fail-under=70"
docker compose -f docker/compose.yaml --profile test run --rm settings-test-runner
```

**Integration**

```bash
ENV_FILE=../.env.test docker compose -f docker/compose.yaml --profile app --profile test up -d garage
GARAGE_CONTAINER="$(docker compose -f docker/compose.yaml ps -q garage)" \
  GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}" \
  GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}" \
  GARAGE_PRINT_CREDENTIALS=0 bash docker/garage-init.sh
docker compose -f docker/compose.yaml --profile app --profile test run --rm test-runner \
  "python -m pytest tests/integration/ -v --tb=short --timeout=120 --override-ini=addopts= -k 'not live and not e2e'"
```

## VPS

After `git pull` on the server, run the same script from the repo root so verification matches CI (see also `scripts/ops/vps-verify-tests.sh` for a slimmer unit-only path).
