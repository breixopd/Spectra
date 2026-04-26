# UI Audit: Navigation, RBAC, Entitlements

Status: loop 1 draft
Scope: `app/templates/base.html`, shared auth/nav scripts, UI role tests, plan/feature gating.

## What Looks Good

- Server-side route checks exist for admin-only surfaces such as `/admin`, `/observability`, and `/toolbox/create`.
- The sidebar admin link is hidden by default and shown only after `/api/v1/auth/me` returns privileged user data.
- Existing Playwright tests cover admin/user/staff visibility and direct-route denial for several critical routes.

## Findings

- Feature gating is still too ad hoc on the client. `confirm.js` now uses `data-entitlement-gate` for gated navigation, but pages do not consistently use a shared gated component contract with reason text, upgrade link, and server-confirmed entitlement.
- Navigation is mostly page/file driven rather than permission driven. The UI would be easier to keep correct if a single navigation manifest defined path, label, icon, required permission, required feature, and locked-state copy.
- Current role tests cover important admin/staff/user paths, but do not yet exercise a complete role x plan matrix across every nav item and primary action.
- The admin link depended on client-side async auth state; rate limits and background requests can leave the UI in a stale hidden state unless server-rendered privilege hints or resilient hydration are used.
- Direct disabled states need consistent accessible messaging. Bare disabled buttons should expose `aria-disabled`, a disabled reason, and a visible tooltip or inline hint.

## Research Notes

- Current B2B SaaS UX guidance recommends shared layouts with role-based content layers, not separate product forks per role.
- Disabled controls without a reason read as broken product. Use "Available on Pro", "Request access", "Contact admin", or "Upgrade plan" recovery paths.
- Track permission-denied and upgrade-prompt events so enterprise buyers can audit access friction.

## Recommended Work

- Introduce a shared UI entitlement manifest consumed by templates and JS:
  - `id`, `label`, `href`, `icon`, `required_permission`, `required_feature`, `locked_reason`, `upgrade_href`.
- Add reusable locked feature markup/macro for links, buttons, tabs, and cards.
- Add Playwright matrix tests for admin, staff, user, free, professional, enterprise, and restricted-processing states.
- Add direct-route tests for every route linked from sidebar and every admin section tab.
- Add server-rendered nav state where practical, then hydrate with `/auth/me` as a verification layer rather than the only source of visibility.

## Loop 1 Fixes Applied

- Sidebar docs link now targets `/docs/api`, the canonical customer API documentation route.
- Sidebar manual tools link now targets `/manual`, matching the implemented route.
- Client plan gating now uses `data-entitlement-gate` to avoid colliding with plan-editor `data-feature` checkboxes.
- Upgrade links now target `/profile#plan`.

## Verification Targets

- Every navigation item has a positive and negative role/plan test.
- Every hidden/disabled component has a server-side API or route denial test.
- No test depends on shared mutable auth state or fragile CSS selectors when a role/name/test id selector can be used.
