# Pre-release gate

Use this checklist before tagging a release or deploying production images. All items should pass or have a written exception signed off by the release owner.

## Automated (must pass)

1. **CI parity** — Docker gate aligned with CI **`static-analysis`** + **`test`** (use `all` to add **`integration-test`**-style integration):

   ```bash
   ./scripts/runbooks/ci-parity.sh all
   ```

   Minimum for a hotfix branch if integration time is blocked: `./scripts/runbooks/ci-parity.sh ci`. This does **not** by itself replace **`deps`** (`pip-audit`), **`docker-build`** (Trivy), or PR/main-merge **`compose-smoke`** — run those separately when needed (see `.github/workflows/ci.yml`).

2. **Compose files valid** (matches CI `docker-build` compose step):

   ```bash
   ENV_FILE=../../.env.example docker compose --env-file .env.example -f deploy/docker/compose.yaml --profile app --profile test --profile targets config --quiet
   docker compose --env-file .env.example -f deploy/docker/docker-compose.swarm.yml config --quiet
   ```

3. **Security scan on app** (Bandit is already in CI **static-analysis**; re-run locally if you skipped it):

   ```bash
   docker build -f deploy/docker/Dockerfile.test -t spectra-test-ci .
   docker run --rm spectra-test-ci bandit -r packages/ services/ -c pyproject.toml --severity-level high --confidence-level high
   ```

4. **Dependency audit** (matches CI `deps` exactly; audit the frozen workspace lock):

   ```bash
   uv export --frozen --all-packages --no-emit-workspace --format requirements.txt -o /tmp/spectra-uv-lock-export.txt
   uvx pip-audit --strict --require-hashes -r /tmp/spectra-uv-lock-export.txt
   ```

## Staging / smoke (strongly recommended)

- **Compose smoke** (pull requests and `main` pushes in CI; run manually before major releases): see [compose-smoke-ci.md](compose-smoke-ci.md).
- **Health**: `./scripts/health_check.sh https://<staging-host>/api/healthz` followed by the public platform check at `/api/v1/health?scope=public`.
- **Browser smoke**: `./tests/run_ui_tests.sh` against staging URL if configured.

## Operational readiness

- Backups and restore path documented under [Operations](../wiki/operations.md).
- Migrations reviewed; rollback plan noted in change log or deploy ticket.

## Customer experience

- No known P0/P1 bugs open for the release scope.
- Rate limits, auth, and billing flows exercised in staging where payment modes are enabled.
