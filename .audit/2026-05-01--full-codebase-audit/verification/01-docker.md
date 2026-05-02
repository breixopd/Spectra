# Verification (Docker)

## Commands run (2026-05-01)

```bash
docker compose -f docker/compose.yaml --profile test build unit-test-runner -q
docker compose -f docker/compose.yaml --profile test run --rm unit-test-runner \
  "python -m pytest tests/unit/services/test_ai_gateway.py -q --override-ini=addopts="
```

**Result:** `3 passed` (includes new `test_rag_search_monolith_hit_shape_matches_ai_service_contract`).

## Recommended full gate (before merge)

Full unit suite + CI coverage flags (as in `.github/workflows/ci.yml`).

## Architecture grep (host)

- `app.models.base`: **no matches** (migration complete).
- `spectra_common.orm.base`: canonical `Base`.
