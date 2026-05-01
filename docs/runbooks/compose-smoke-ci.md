# Compose smoke (CI `compose-smoke` job)

The GitHub Actions job **compose-smoke** (on `push` to configured branches) brings up a large Compose stack, bootstraps Garage, waits for managed containers, then runs live API, health, and performance tests inside `test-runner`.

Use this when you need **maximum** confidence before launch—not for every commit.

## Preconditions

- Same as [CI parity](ci-parity-local.md): Docker, `.env.test`, repo root.
- Enough disk and RAM for app + targets + test profiles.

## Steps (mirror workflow)

```bash
test -f .env.test || cp .env.test.example .env.test
export ENCRYPTION_KEY=test-encryption-key
export ENV_FILE=../.env.test

docker compose -f docker/compose.yaml --profile app --profile targets --profile test up -d --build

GARAGE_CONTAINER="$(docker compose -f docker/compose.yaml ps -q garage)" \
  GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GK0123456789abcdef01234567}" \
  GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}" \
  GARAGE_PRINT_CREDENTIALS=0 \
  bash docker/garage-init.sh
```

Wait until managed `spectra` containers are healthy (same loop as CI: check `label=spectra.managed=true`, no `health=unhealthy`, at least 10 running—or adjust for your profile set).

Then:

```bash
docker compose -f docker/compose.yaml --profile app --profile targets --profile test run --rm \
  -e APP_BASE_URL=http://app:5000 \
  test-runner \
  "python -m pytest tests/e2e/test_api_live.py -v --tb=short --timeout=120"

docker compose -f docker/compose.yaml --profile app --profile targets --profile test run --rm \
  -e APP_BASE_URL=http://app:5000 \
  test-runner \
  "python -m pytest tests/integration/test_api_health_live.py -v --tb=short --timeout=120"

docker compose -f docker/compose.yaml --profile app --profile targets --profile test run --rm \
  -e LOAD_TEST_APP_URL=http://app:5000 \
  test-runner \
  "python -m pytest tests/performance/test_api_latency.py -v --tb=short --timeout=120"
```

## Teardown

```bash
docker compose -f docker/compose.yaml --profile app --profile targets --profile test down -v --remove-orphans
```

On failure, collect logs from containers with `label=spectra.managed=true` (see CI job `Collect logs on failure`).
