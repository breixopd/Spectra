# Tests Performance Images Audit

## Critical / High

- Default `scripts/test.sh` path builds the API image and installs pytest dependencies at runtime. This is slow, version-loose, and network-dependent despite `docker/Dockerfile.test` existing.
- Coverage thresholds disagree between `pyproject.toml`, CI, and Docker test script behavior.
- API runtime image installs Grype. Runtime app image should not carry scanner binaries unless explicitly enabled by build target.
- Worker is Kali-based by design and large; `requirements/worker.txt` still pulls web framework deps due shared imports.
- Pytest/pytest-asyncio/Playwright version workarounds exist in CI and Dockerfiles. Needs one documented compatible pair.
- CI now builds and loads API/worker images, then runs Trivy with a critical-CVE failure policy. Extend this to AI, scheduler, Caddy, and release-published GHCR images before production release.
- `deploy.resources` limits in compose are Swarm-oriented. Plain `docker compose up` deployments may not enforce the documented CPU/memory limits unless equivalent `cpus`/`mem_limit` or orchestrator limits are added.
- `kali-rolling:latest` and third-party `latest` images drift over time. Pin digest or release tags for production images that must be reproducible.

## Benchmark Gaps

- Current performance tests are HTTP latency/error smoke, not microbenchmarks.
- No automated container RSS/CPU/image-size budget checks.
- Load harness still pip-installs dependencies in runner.

## VPS Resource Snapshot

- Idle-ish test stack memory: app ~147 MiB, app replica ~155 MiB, AI service ~56 MiB, scheduler ~103 MiB, worker ~96 MiB, tools ~662 MiB, ClickHouse ~663 MiB.
- Largest local images on VPS: Playwright UI runner ~3.8 GiB, Metasploitable ~2.3 GiB, app/app-replica ~1.16 GiB, worker/tools ~1.1 GiB, AI service ~860 MiB, test runners ~937 MiB.
- Docker disk usage on VPS after test stack: images ~56.4 GiB, build cache ~11.46 GiB, volumes ~5.15 GiB. Cleanup/prune policy matters for small hosts.

## First Fixes

- Keep `Dockerfile.test` as default test runner path.
- Move Grype to CI or a scan build target. The first CI slice now scans API/worker images with Trivy for critical CVEs.
- Add image-size/resource reporting to live-smoke or load reports.
- Split shared imports so worker can drop FastAPI/uvicorn where possible.
- Add Dependabot/Renovate for `requirements/*.txt` and GitHub Actions so dependency and action updates are routine.
