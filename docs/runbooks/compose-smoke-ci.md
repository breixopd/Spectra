# Compose smoke (CI `compose-smoke` job)

The GitHub Actions job **compose-smoke** runs for pull requests targeting `main`/`dev` and for pushes to the protected `main` branch. It brings up a large Compose stack, bootstraps Garage, verifies the explicit expected service set, then runs live API, health, and performance tests inside `test-runner`.

Use this when you need **maximum** confidence before launch—not for every commit.

## Preconditions

- Same as [CI parity](ci-parity-local.md): Docker, `.env.test`, repo root.
- Enough disk and RAM for app + targets + test profiles.

## Steps (mirror workflow)

```bash
test -f .env.test || cp .env.test.example .env.test
export ENCRYPTION_KEY=test-encryption-key
export ENV_FILE=../../.env.test

docker compose -f deploy/docker/compose.yaml --profile app --profile targets --profile test up -d --build

GARAGE_CONTAINER="$(docker compose -f deploy/docker/compose.yaml ps -q garage)" \
  GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}" \
  GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}" \
  GARAGE_PRINT_CREDENTIALS=0 \
  bash deploy/docker/garage-init.sh
```

Wait until each expected long-running service is running and healthy (or has no healthcheck): `db`, `redis`, `garage`, `registry`, `clickhouse`, `tensorzero`, `app`, `app-replica`, `ai-svc`, `scheduler`, `tools`, `worker`, and `caddy`. The workflow fails closed on a missing or unhealthy expected service; test-runner containers and vulnerable targets are intentionally not counted as long-running platform services.

Then:

```bash
docker compose -f deploy/docker/compose.yaml --profile app --profile targets --profile test run --rm \
  -e APP_BASE_URL=http://app:5000 \
  test-runner \
  "python -m pytest tests/e2e/test_api_live.py -v --tb=short --timeout=120"

docker compose -f deploy/docker/compose.yaml --profile app --profile targets --profile test run --rm \
  -e APP_BASE_URL=http://app:5000 \
  test-runner \
  "python -m pytest tests/integration/test_api_health_live.py -v --tb=short --timeout=120"

docker compose -f deploy/docker/compose.yaml --profile app --profile targets --profile test run --rm \
  -e LOAD_TEST_APP_URL=http://app:5000 \
  test-runner \
  "python -m pytest tests/performance/test_api_latency.py -v --tb=short --timeout=120"
```

## Teardown

```bash
docker compose -f deploy/docker/compose.yaml --profile app --profile targets --profile test down -v --remove-orphans
```

On failure, collect logs from containers with `label=spectra.managed=true` (see CI job `Collect logs on failure`).
