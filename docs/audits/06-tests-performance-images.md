# Tests Performance Images Audit

## Critical / High

- Default `scripts/test.sh` path builds the API image and installs pytest dependencies at runtime. This is slow, version-loose, and network-dependent despite `docker/Dockerfile.test` existing.
- Coverage thresholds disagree between `pyproject.toml`, CI, and Docker test script behavior.
- API runtime image installs Grype. Runtime app image should not carry scanner binaries unless explicitly enabled by build target.
- Worker is Kali-based by design and large; `requirements/worker.txt` still pulls web framework deps due shared imports.
- Pytest/pytest-asyncio/Playwright version workarounds exist in CI and Dockerfiles. Needs one documented compatible pair.

## Benchmark Gaps

- Current performance tests are HTTP latency/error smoke, not microbenchmarks.
- No automated container RSS/CPU/image-size budget checks.
- Load harness still pip-installs dependencies in runner.

## First Fixes

- Keep `Dockerfile.test` as default test runner path.
- Move Grype to CI or a scan build target.
- Add image-size/resource reporting to live-smoke or load reports.
- Split shared imports so worker can drop FastAPI/uvicorn where possible.
