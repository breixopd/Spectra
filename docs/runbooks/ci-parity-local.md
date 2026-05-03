# CI parity (local or VPS)

This runbook reproduces the **merge gate** from `.github/workflows/ci.yml` on any machine with Docker: **one static-analysis pass** (Ruff, import boundaries, Pyright, Bandit on a single `Dockerfile.test` build), **unit tests with coverage floor**, and **settings** runner. Optionally run **integration** tests the same way CI does.

For a **broader** scripted gate — parity integration plus load/performance/soak harnesses, Playwright UI tests, live target scans, and optionally full LLM live tests when `.env.test` has keys — run `./scripts/runbooks/full-test-matrix.sh` (see script header for `SKIP_*` flags).

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
| `./scripts/runbooks/ci-parity.sh static` | Full CI **static-analysis** job (build once → ruff, boundaries, pyright, bandit) |
| `./scripts/runbooks/ci-parity.sh lint` | Ruff + import boundaries only (builds test image) |
| `./scripts/runbooks/ci-parity.sh type` | Pyright only (builds test image) |
| `./scripts/runbooks/ci-parity.sh unit` | CI TensorZero parse + unit + coverage ≥70% |
| `./scripts/runbooks/ci-parity.sh settings` | CI settings-test-runner |
| `./scripts/runbooks/ci-parity.sh integration` | CI `integration-test` job |
| `./scripts/runbooks/ci-parity.sh ci` | static analysis + unit + settings |
| `./scripts/runbooks/ci-parity.sh all` | `ci` + integration |

`lint` and `type` are **local script slices** for faster iteration. GitHub Actions runs a single **`static-analysis`** job (one image build, then all steps in order).

Environment:

- `ENCRYPTION_KEY` — defaults to `test-encryption-key` (same idea as CI).
- `SKIP_PYRIGHT=1` — skip Pyright for a quicker loop.
- `SKIP_BANDIT=1` — skip Bandit.
- `COMPOSE_DOWN=1` — after `all`, tear down compose profiles (optional cleanup).

## Manual equivalents (copy from CI)

If you cannot use the script, these are the same steps as the workflow file.

**Static analysis (one image build — matches CI `static-analysis` job)**

```bash
docker build -f docker/Dockerfile.test -t spectra-test-ci .
  docker run --rm spectra-test-ci python -m ruff check packages/platform/src/spectra_platform tests/ services/ packages/
docker run --rm spectra-test-ci python scripts/check_import_boundaries.py
docker run --rm spectra-test-ci sh -c "pip install --no-cache-dir pyright && pyright"
  docker run --rm spectra-test-ci bandit -r packages/platform/src/spectra_platform -c pyproject.toml --severity-level high --confidence-level high
```

**Unit + coverage + settings**

```bash
test -f .env.test || cp .env.test.example .env.test
export ENCRYPTION_KEY=test-encryption-key
docker compose -f docker/compose.yaml --profile test build unit-test-runner
docker compose -f docker/compose.yaml --profile test run --rm --no-deps unit-test-runner \
  "python -c \"import tomllib; tomllib.load(open('config/tensorzero.toml', 'rb')); print('tensorzero.toml: valid')\""
docker compose -f docker/compose.yaml --profile test run --rm unit-test-runner \
  "python -m pytest tests/unit/ -q --override-ini=addopts= --cov=spectra_platform --cov=spectra_api --cov=spectra_worker --cov=spectra_ai --cov=spectra_scheduler --cov-report=term-missing --cov-fail-under=70"
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

GitHub Actions also runs a **weekly** extended job — `.github/workflows/nightly-extended.yml` — that executes `scripts/runbooks/ci-parity.sh all` (static + unit + settings + integration). Use `workflow_dispatch` on that workflow for an on-demand full parity run.

## VPS

After `git pull` on the server, run the same script from the repo root so verification matches CI (see also `scripts/ops/vps-verify-tests.sh` for a slimmer unit-only path).

**Full extended matrix on the VPS** (same as local `full-test-matrix.sh`): from a machine with SSH access,

```bash
VPS=root@your.host ./scripts/runbooks/vps-full-test-matrix.sh
# long run in background on server, log at /tmp/spectra-matrix-vps.log:
VPS_BACKGROUND=1 VPS=root@your.host ./scripts/runbooks/vps-full-test-matrix.sh
```

**Resource snapshot** (CPU/RAM per container): `VPS=root@your.host ./scripts/runbooks/vps-docker-stats.sh`

### When `git fetch` fails (HTTPS origin, no GitHub token on the server)

From a machine that **has** the commits (your laptop):

```bash
cd /path/to/Spectra
git bundle create /tmp/spectra-vps-sync.bundle chore/desloppify-quality   # or main
scp /tmp/spectra-vps-sync.bundle user@vps:/tmp/
```

On the VPS:

```bash
cd /root/Spectra   # or your clone path
git fetch /tmp/spectra-vps-sync.bundle chore/desloppify-quality
git checkout chore/desloppify-quality && git reset --hard FETCH_HEAD
rm -f /tmp/spectra-vps-sync.bundle
```

Images like `spectra-app:dev` are **built on the host** (not pulled from Docker Hub). After updating the tree:

```bash
docker compose -f docker/compose.yaml --profile app up -d --build
```

Then hit `http://<VPS_IP>:5000/api/health` (compose publishes **5000** on `0.0.0.0` when using the default `app` service ports).
