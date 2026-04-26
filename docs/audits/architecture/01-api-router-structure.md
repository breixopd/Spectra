# Architecture Audit: API Router Structure

Status: loop 1 draft
Scope: `app/api/routers`, API schemas, route tests, server-side enforcement.

## Findings

- `app/api/routers/ui.py` mixes HTML rendering, direct database reads, and plan checks. UI route handlers should delegate entitlement logic to shared billing/permission services.
- `app/api/routers/pentest_sessions.py` still contains storage, encryption, path rules, and HTTP routing in one module despite schema extraction. Persistence should move into a service/store layer.
- `app/api/routers/tools.py` remains a large mixed-surface router covering registry, admin plugin operations, tool tests, and AI-facing tool data.
- `app/api/routers/admin/servers.py` still carries multiple provisioning/server-pool concerns in one router after schema extraction.
- Inline Pydantic models remain in newer router modules such as findings and mission artifacts. The emerging schema extraction pattern should be standardized.
- `enforce_api_rate_limit` appears to exist but is not broadly attached to routers, so plan API quotas may not be enforced consistently.

## Recommended Refactor

- Create router subpackages by domain and concern:
  - `app/api/routers/tools/public.py`
  - `app/api/routers/tools/admin.py`
  - `app/api/routers/tools/schemas.py`
  - `app/api/routers/pentest_sessions/routes.py`
  - `app/api/routers/pentest_sessions/schemas.py`
  - `app/api/routers/pentest_sessions/store.py` or service-layer equivalent
  - `app/api/routers/admin/servers/verification.py`
  - `app/api/routers/admin/servers/provisioning.py`
  - `app/api/routers/admin/servers/nodes.py`
- Move business logic into services. Routers should parse input, call service/dependency functions, and return responses.
- Add a central API quota dependency applied at router include time for authenticated API namespaces.
- Add 1:1 router test modules for missions, tools, wordlists, mission artifacts, and manual helpers.

## Verification Targets

- Every route has a clear permission, feature, owner, and quota policy.
- Every large router has a package-level split or an accepted reason to remain monolithic.
- Every route group has unit API coverage plus at least one E2E/UI coverage path when user-facing.
