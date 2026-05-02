# Scope — full codebase audit (2026-05-01)

## In scope

- Post-migration architecture: `spectra_common.orm.Base`, RAG singleton vs microservice, `RAGRequest` / gateway paths.
- API (`spectra_api`), UI (Jinja/static), backend services, worker/scheduler coupling, security hot spots, CI/tests.
- Verification via Docker (project standard).

## Recent changes (anchor)

`git log --oneline -15` — highlights: `ea4ebff` (RAG tenant + Alembic backfill + ORM Base move), gateway/SERVICE_MODE/CI coverage commits on same branch.

## Out of scope (this run)

- Production data inspection; live exploit scans; full Playwright UI run; every Alembic revision line-by-line.
- Legal/compliance sign-off.

## Product intent assumptions

- Multi-tenant RAG scoping is desired where `user_id` is present.
- CVE/global knowledge may remain unscoped alongside tenant exploit history.
