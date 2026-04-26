# Release-Candidate Gap Register

Status values:

- `closed`: implemented and verified enough for current release-candidate scope.
- `partial`: meaningful implementation exists, but verification, UX, docs, or edge cases remain.
- `blocker`: must be fixed before calling the product release-candidate ready.
- `decision`: needs product/security approval before implementation can safely proceed.

## P0 Blockers

| ID | Area | Status | Gap | Required release-candidate outcome |
| --- | --- | --- | --- | --- |
| RC-BE-001 | Backend security | blocker | Production can still auto-generate critical shared secrets in some paths. | Production mode must fail fast unless shared `JWT_SECRET_KEY`, `SECRET_KEY`, `SERVICE_AUTH_SECRET`, and encryption material are explicitly configured. |
| RC-BE-002 | Backend security | blocker | Stripe webhook processing lacks explicit event-id idempotency. | Store and reject duplicate webhook event IDs before reconciliation side effects. |
| RC-BE-003 | MCP/RAG security | blocker | `search_knowledge_base` is not forced through the same server-bound user scoping as other MCP tools. | Bind all user-data MCP tools to server-side user identity and test tenant isolation. |
| RC-UI-001 | Browser QA | blocker | Playwright coverage is admin-heavy and misses setup, reset/verify email, entitlements, shell, billing, and role-negative flows. | Add browser coverage for primary public, customer, staff, admin, entitlement, mobile, error, and session-expiry flows. |
| RC-CI-001 | Release gates | blocker | Release workflow is weaker than CI and does not run Playwright/full stack E2E. | Release gates must run at least unit, integration, security, dependency, Docker image, Swarm config, and browser smoke checks. |
| RC-DEP-001 | Swarm deployment | blocker | Swarm secret bootstrap does not cover every external secret declared by the stack. | `swarm_deploy.sh --secrets` and docs must match `docker-compose.swarm.yml`. |
| RC-DEP-002 | Swarm scaling | blocker | Admin-managed server pool is split between Swarm node scaling and standalone SSH-provisioned workers. | Pick one production story and make scripts, UI, docs, and health checks consistent. Default: secure script-driven Swarm bootstrap plus Admin UI visibility. |
| RC-COMP-001 | Authorized use | blocker | Authorization confirmation exists, but target ownership proof and trust tiers are not implemented. | Add target verification state, conservative defaults for new tenants, and high-risk action gates. |
| RC-MIS-001 | Mission durability | blocker | Mission creation fails closed now, but running missions are not fully resumable or explicitly marked interrupted after restart. | Persist lifecycle checkpoints and mark active missions interrupted on app startup if they cannot be resumed. |

## P1 High Priority

| ID | Area | Status | Gap | Required release-candidate outcome |
| --- | --- | --- | --- | --- |
| RC-SEC-001 | Roles | partial | Staff permissions include sensitive management rights that need product sign-off. | Tighten staff role or document/approve staff as a trusted operator role. |
| RC-SEC-002 | Service auth | partial | Internal service auth comparisons need constant-time checks in sensitive paths. | Use constant-time comparison for service/API shared secret validation. |
| RC-AI-001 | TensorZero feedback | partial | `send_exploit_feedback` and `send_quality_score` exist but are not wired into mission/report paths. | Record exploit success/failure and report quality feedback. |
| RC-AI-002 | Provider health | partial | Free provider quota and model volatility can stall long missions. | Gate long mission planning on provider health and expose actionable admin status. |
| RC-TEST-001 | Coverage policy | partial | Coverage thresholds differ between `pyproject.toml`, CI, release, and local scripts. | Use one documented threshold and runner behavior. |
| RC-TEST-002 | Skipped E2E | partial | Several integration/E2E suites are excluded from CI or skipped. | Promote a deterministic subset into CI/scheduled release gates and document true live-only tests. |
| RC-DEP-003 | Rate-limit Redis | partial | Swarm app defaults risk unauthenticated Redis rate-limit storage while Redis uses auth. | Use passworded shared Redis URL in production/Swarm configuration. |
| RC-DEP-004 | Preflight | partial | Swarm preflight checks app/db but not every role required by placement constraints. | Preflight all labels, external secrets, volumes, and manager-only Docker socket assumptions. |
| RC-IMG-001 | Image hardening | partial | API image still carries Grype and some images use floating tags. | Move scanners out of hot runtime where practical and pin production images/tags. |
| RC-PENT-001 | Mission parallel safety | partial | Parallel task/tool completions mutate shared mission state without a lock/actor. | Serialize mission mutations before increasing concurrency. |
| RC-PENT-002 | Evidence quality | partial | Findings can be reported without a strong reproducible artifact requirement. | Require evidence artifacts for severity escalation or report trust. |

## P2 Product Completeness

| ID | Area | Status | Gap | Required release-candidate outcome |
| --- | --- | --- | --- | --- |
| RC-PENT-003 | Artifact workspace | decision | Per-mission artifact workspace is listed but not productized. | Implement guarded workspace or explicitly defer from release scope. |
| RC-PENT-004 | File server/listeners | decision | Ephemeral file server and listener/callback manager are absent. | Implement with strict scope, TTL, audit, and approval gates, or keep disabled for release. |
| RC-PENT-005 | Payload generation | decision | Payload generation is high-risk and not release-ready as a general feature. | Gate behind enterprise/admin approval or defer. USER - Fix it then and improve as needed |
| RC-PENT-006 | AD/cloud modules | decision | BloodHound/SharpHound and cloud audit modules are not complete product flows. | Add as roadmap/plugins with clear support status or implement tested workflows. |
| RC-DOC-001 | Enterprise docs | partial | DPA, subprocessors, retention matrix, incident response SLA, security whitepaper, and vulnerability disclosure policy are missing. | Add release-ready customer trust docs or mark as pre-enterprise limitation. |
| RC-DOC-002 | Roadmap accuracy | partial | Some docs understate or overstate current implementation, including warm pool and deployment wording. | Make docs match shipped capabilities exactly. |

## Closed In Current Branch

| ID | Area | Status | Notes |
| --- | --- | --- | --- |
| RC-PLUG-001 | Plugin install routing | closed | Tool jobs route to dedicated queue in split test deployments. |
| RC-PLUG-002 | Startup auto-install | closed | Blocking bulk startup install is opt-in; installs happen on request/execution. |
| RC-PLUG-003 | Stale plugin status | closed | Execution verifies binaries before trusting cached ready state. |
| RC-PLUG-004 | Web fuzzer dependencies | closed | `ffuf` and `gobuster` install and verify `seclists`. |
| RC-PLUG-005 | Tool flags | closed | Free-form flags are split and quoted per token. |
| RC-MNT-001 | Scheduler cleanup import | closed | Cleanup lives under `app.services` and scheduler skips S3 cleanup if deps are absent. |
| RC-LIVE-001 | Live smoke quota handling | closed | LLM provider 5xx/quota is warning by default and strict with `STRICT_LLM_SMOKE=1`. |
| RC-COMP-002 | Baseline authorization assertion | closed | Mission launch requires `authorization_confirmed` and logs it. |
| RC-CI-002 | Initial image scanning | closed | CI scans API/worker images for critical CVEs. |

## Verification Required Before RC Sign-Off

- Full Playwright run against the Docker test stack and live VPS UI.
- Browser pass without auth-failure suppression for session expiry and permission failures.
- Full unit and integration tests with aligned coverage.
- Stack E2E for tools, mission lifecycle, reports, and admin server pool.
- Live smoke through Caddy after every deployment change.
- Bounded vulnerable-target mission with terminal-state polling, findings, report generation, and logs.
- Swarm config validation, secret preflight, and at least one multi-node scale/update/rollback test.
- Service logs reviewed for app, app-replica, scheduler, worker/tools, AI service, TensorZero, ClickHouse, Redis, Postgres, Garage, and Caddy.
