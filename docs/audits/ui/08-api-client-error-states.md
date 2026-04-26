# UI Audit: API Docs, Client Error States, Toasts

Status: loop 1 draft  
Scope: API docs page, `spectraApi` client, global toasts, rate-limit and session expiry handling, WebSocket disconnect surfacing.

## What Looks Good

- Central API client and auth suppression in Playwright `conftest` reduce redirect races during e2e.
- Docs route exists and is covered by e2e navigation tests.

## Findings

- **Error taxonomy:** user-visible errors should map to: network, auth (401), rate limit (429), validation (4xx), server (5xx), with **non-spammy** toasts; retries should backoff for 429.
- **Session expiry:** single source of truth for “re-auth required” to avoid half-broken pages with silent 401 loops.
- **OpenAPI display:** ensure admin-only routes are filtered for non-admin API users (server + UI already partially addressed—keep parity tests).

## Research Notes

- Public docs for B2B products often separate “quickstart” from raw OpenAPI; both need stable anchors for support links.
- `Retry-After` header support improves UX under rate limits.

## Recommended Work

- Add Playwright cases for: 401 recovery, 429 message (where test env can simulate), and docs search.
- Add `data-testid` on docs search input and first operation row for less flaky selectors.

## Verification Targets

- No infinite retry loop on 401; WebSocket 4001 still redirects to login in a single navigation.
