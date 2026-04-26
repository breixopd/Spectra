# UI Audit: Settings, Profile, API Keys, Integrations

Status: loop 1 draft  
Scope: `app/templates/settings.html`, `app/templates/profile.html`, billing/plan sections, BYOK and integration surfaces.

## What Looks Good

- Settings is split into logical sections; profile has tabbed or sectioned layout for account vs privacy.
- Plan-driven features (manual mode, API access) have server enforcement paths outside the UI.

## Findings

- **Gating consistency:** use one pattern for “locked” features: `data-entitlement-gate` + visible reason + link to `/profile#billing` or plan upgrade, with `aria-disabled` or `role="link"` for non-button affordances.
- **Secrets display:** API keys and webhooks should never log to client console; mask in UI and show rotation affordances.
- **Form recovery:** long settings forms need dirty-state warning and section-level save error surfacing.

## Research Notes

- Enterprise buyers expect **auditability** of who changed org settings; surface “last changed” where the API supports it.
- Profile “data rights” flows (export, restrict processing) should be test-id stable for compliance regression tests.

## Recommended Work

- Shared `locked_feature_button` / `locked_nav_link` macros with tooltip + upgrade link.
- Playwright: matrix for free vs paid plan on settings sections that are feature-gated; profile GDPR tab already covered—extend to “API access” and “BYOK” when plans differ.

## Verification Targets

- Every settings section that calls a privileged API has a matching API 403 test for unprivileged users.
- Webhook and API key UIs: invalid URL/scope errors are inline, not silent failures.
