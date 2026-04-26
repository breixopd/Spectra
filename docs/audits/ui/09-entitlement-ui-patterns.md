# UI Audit: Entitlement gates (sidebar, upgrade affordances)

Status: 2026-04 loop — research + test coverage

## How it works (code)

- `app/templates/base.html` marks gated nav items with `data-entitlement-gate="<feature_key>"` (e.g. `api_access`, `manual_mode`).
- `app/static/js/confirm.js` (after `/api/v1/auth/me` or equivalent user payload): reads `user.plan.features`, toggles `pointer-events-none` / `opacity-40`, strips `href`, sets `aria-disabled="true"`, and injects an **Upgrade** link to `/profile#plan` (unless user is admin — admins bypass gating).
- **Accessibility:** gated links become non-navigable with a `title` explaining the requirement.

## Research (industry)

- Gating with **aria-disabled** + a visible **upgrade** path is preferable to silent hidden links (users understand why a control is inert).
- **Playwright:** assert on **post-hydration** state — wait for sidebar user label or a stable client-side condition before reading attributes (avoids flakiness vs `networkidle`).

## Test coverage

- `tests/e2e/ui/test_entitlement_sidebar.py` — gated/ungated matrix for `api_access` and `manual_mode` plus admin bypass.
- `tests/e2e/ui/test_release_candidate_flows.py` — 403/redirect paths for API docs and manual without entitlement.
- DB helpers: `tests/e2e/ui/harness/db_user.py` for reproducible plan features.

## Follow-ups

- Add `data-testid` on gated link wrappers if CSS selectors need to tighten further.
- Consider a single `FeatureKey` constant module shared with backend feature checks (reduces string drift).
