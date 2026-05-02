# Full codebase audit — index

**Run:** `.audit/2026-05-01--full-codebase-audit/`  
**Date:** 2026-05-01  
**Git ref (local):** `chore/desloppify-quality` @ `ea4ebff` + follow-up fixes on same branch (see `git log -5`)

## Phases

| Phase | Status |
|-------|--------|
| 0 Bootstrap | done |
| 1 Map + Chunkhound | done (`health_check` healthy; `code_research` duplication roadmap) |
| 2 Layer audits (parallel) | done → `ui/`, `api/`, `backend/`, `security/`, `tests/` |
| 3 Drill + fixes | RAG hit contract + AI `/health` `Response` fixed in-repo |
| 4 External research | light (prior run + skill); optional deeper pass later |
| 5 Synthesis | `plan/01-improvement-plan.md` |
| 6 Product completeness | partial — core UI smoke + docs; see `OPEN:` |
| 7 Verification | `verification/01-docker.md` |
| 8 Handoff | this file |

## Artifacts

| Path | Summary |
|------|---------|
| [00-SCOPE.md](./00-SCOPE.md) | In/out, recent commits |
| [progress.md](./progress.md) | Checklist |
| [ui/01-ui-audit.md](./ui/01-ui-audit.md) | Jinja/public pages, auth gating, UX issues |
| [api/01-api-audit.md](./api/01-api-audit.md) | Routing, SERVICE_MODE, rate limits, webhooks |
| [backend/01-backend-audit.md](./backend/01-backend-audit.md) | RAG patterns, gateway, scheduler/worker coupling |
| [security/01-security-audit.md](./security/01-security-audit.md) | Shell, secrets, CORS, RBAC/MFA notes |
| [tests/01-tests-ci-audit.md](./tests/01-tests-ci-audit.md) | CI jobs, markers, coverage gaps |
| [plan/01-improvement-plan.md](./plan/01-improvement-plan.md) | Prioritised backlog |
| [verification/01-docker.md](./verification/01-docker.md) | Commands + results |
| [subagents/01-notes.md](./subagents/01-notes.md) | Subagent mapping |
| [research/01-external-notes.md](./research/01-external-notes.md) | Pointers for deeper web pass |
| [memory.md](./memory.md) | Durable facts for next audit |

## Architecture verification (this run)

- **No** remaining `app.models.base` imports; canonical ORM base: `spectra_common.orm.base.Base`.
- **RAG:** Monolith uses `get_rag_service()` singleton; AI HTTP uses per-request `RAGService()`; scripts document direct construction.
- **Contract fix:** `AIGateway.rag_search` monolith fallback result dict **aligned** with `spectra_ai` `/api/v1/ai/rag` (`content`, `score`, `metadata`, `doc_type`).

## OPEN:

- Full UI category matrix (a11y, i18n) — spot fixes landed; exhaustive scoring still optional.
- **MCP / IDOR:** user-scoped MCP tools documented in `docs/wiki/security.md` (forced `MCP_USER_ID`); RAG MCP path remains a privileged shared surface — product decision.
- **`spectra_ai` coverage:** in `pyproject` + CI; see `tests/01-tests-ci-audit.md`.
- Scheduler `app.*` coupling vs extracted kernel (strategic — multi-PR).
- **Compose-smoke / harness:** perf→e2e→health, `--override-ini=addopts=`, `TestPassword123!` defaults — in CI + verified on VPS (2026-05).
- **Stripe webhook dedup** — Redis `SET NX` on event id before reconcile (2026-05).

## Re-run

```bash
docker compose -f docker/compose.yaml --profile test build unit-test-runner
docker compose -f docker/compose.yaml --profile test run --rm unit-test-runner \
  "python -m pytest tests/unit/ -q --override-ini=addopts= --cov=spectra_platform --cov=spectra_api --cov=spectra_worker --cov-fail-under=70"
```

Chunkhound: call `health_check` at audit start; optional `code_research` for follow-up themes.
