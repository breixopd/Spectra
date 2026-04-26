# Running live mission / target tests (local, optional)

These tests call **real** LLM providers (e.g. OpenRouter via `OPENAI_BASE_URL` + `OPENAI_API_KEY` in `.env.test`) and may hit **vulnerable lab containers** when the test stack is up with the `targets` profile.

## Prereqs

- `.env.test` (copy from `.env.test.example`) with **non-committed** API keys.
- `AI_PROVIDER` not set to `mock` where a test requires a real model (see `test_live_targets.py` skip message).
- Docker test stack: `docker compose -f docker/docker-compose.test.yml` with services healthy; for target hosts, add `--profile targets` as documented in the compose file.

## Commands (examples)

```bash
# List skip reasons for integration / live
python -m pytest tests/integration/ -ra -q --co -k "live" 2>/dev/null | head -50

# Run a single live file (from the same environment the integration runner uses)
docker compose -f docker/docker-compose.test.yml run --rm test-runner \
  "python -m pytest tests/integration/test_live_scan.py -v --tb=short -m live"
```

**Rate limits:** OpenRouter and other free tiers can throttle; fail fast and retry off-peak. Do not rely on live tests in the default PR gate.
