# Backend API Security Audit

## Critical / High

- `ENCRYPTION_KEY` handling used a new random key even when `ENCRYPTION_KEY` existed in env. Fixed to use env value.
- Auto-generated `JWT_SECRET_KEY`, `SECRET_KEY`, and `SERVICE_AUTH_SECRET` are risky in production because replicas/restarts can disagree. Production should fail fast unless these are explicit shared secrets.
- MCP RAG tool scoping needs review. User-scoped tools bind to `MCP_USER_ID`, but `search_knowledge_base` does not appear in the user-scoped set.
- Stripe webhook handling lacks explicit event-id idempotency. Retries can re-run reconciliation logic.
- Staff role currently has `MANAGE_USERS`; product/security sign-off needed before release.

## Medium

- Request body middleware crashed on malformed `Content-Length`. Fixed to return `400`.
- Admin IP allowlist depends on trusted proxy headers/client IP plumbing.
- Billing portal catches fewer provider failures than checkout.
- Internal service auth comparisons should use constant-time compare in sensitive paths.

## First Fixes

- Fixed env encryption-key branch.
- Fixed malformed content length handling.
- Ran `pip-audit` per service requirements. Upgraded vulnerable direct and transitive dependency parents; audit is clean for `requirements/app.txt`, `requirements/ai.txt`, `requirements/worker.txt`, and `requirements/scheduler.txt`.
- Leave production secret fail-fast, webhook idempotency, MCP RAG scoping, and staff permission tightening for next backend pass with tests.
