# Live LLM Smoke Notes

## What Ran

- `START_STACK=1 ./scripts/test.sh live-smoke`
- Internal direct AI smoke from the app container to `http://ai-svc:5010`
- Direct OpenRouter model availability probes using `.env.test` without printing secrets

## Results

- Public/Caddy smoke passed.
- Setup/login smoke passed.
- Canonical public and full health checks passed, including latency checks.
- TensorZero gateway health/test endpoint passed.
- Direct AI service chat passed after fixes.

## Issues Found

- TensorZero had no outbound DNS/egress because it was attached only to the internal backend network. It needs outbound provider access while keeping no published ports. Fix: attach TensorZero to the non-internal frontend network in Compose/Swarm.
- Previous free model IDs were stale or currently unavailable. OpenRouter returned `404` for `qwen/qwen3-30b-a3b:free`, and `429` for several larger free Gemma/Qwen models. Fix: configure currently working free models: `google/gemma-3-4b-it:free`, `qwen/qwen3-coder:free`, and `cognitivecomputations/dolphin-mistral-24b-venice-edition:free`.
- Manual compose operations must use `--env-file .env.test`; otherwise recreated services can fall back to default `SERVICE_AUTH_SECRET` and break service auth.
- AI container warned that `defusedxml` was missing, leaving XML parsing vulnerable to XXE. Fix: add `defusedxml` to AI and worker service requirements.

## Residual Risk

- Free OpenRouter models are rate-limited and can change availability. Production should support admin-managed model routing, BYOK provider keys, and health-aware provider fallback instead of depending on fixed free model IDs.
