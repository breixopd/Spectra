# UI Audit: Admin, Billing, Plan Editor

Status: loop 1 draft
Scope: `app/templates/admin.html`, `app/templates/admin/_*.html`, `app/static/js/pages/admin*.js`, plan APIs and tests.

## What Looks Good

- Admin sections are split into partial templates, which is a good direction for page organization.
- Plan editing is backed by server-side admin permissions and unit/UI coverage exists for basic plan management.
- Recent fixes improved role badge mapping, admin tab handlers, services auto-refresh, and scaling controls.

## Findings

- The plan editor hardcodes the visible feature toggles while also allowing arbitrary JSON feature flags. This is flexible, but it makes plan capabilities hard to discover, validate, document, and test.
- Admin JS is split by section, but several files still rely on globals (`allPlans`, shared helper functions, shared modal functions). This makes section isolation and targeted testing harder.
- The plan editor does not clearly explain limits, units, and consequences. Examples: `0` means unlimited for some fields, `1` minimum for others, and sandbox/resource tiers do not explain operational impact.
- No reusable "danger action" component exists for destructive admin actions. Deactivate plan, server actions, user actions, and data clearing should share confirmation language and audit context.
- The admin dashboard is still entity-heavy. It should move toward task/action queues: pending users, failing services, degraded workers, expiring secrets, failed jobs, suspicious missions, and quota pressure.

## Research Notes

- Enterprise admin UX should be task-centric instead of table/entity-centric. Operators need "what requires attention", "what action is available", and "what changed".
- Role/permission systems should document objects, operations, scopes, and recovery paths. Plan features should be treated as a product catalog, not free-form UI strings.

## Recommended Work

- Add a central feature catalog module:
  - feature key, display name, description, default tier, category, API guard, UI surfaces, upgrade copy.
- Generate plan editor feature toggles from that catalog instead of hardcoding checkboxes.
- Add field-level help text and validation copy for plan limits, including unlimited semantics.
- Split admin JS into modules with explicit exports/imports or a single page controller that registers section controllers.
- Add Playwright coverage for:
  - Create/edit/deactivate/reactivate plan.
  - Feature toggle persistence.
  - Invalid JSON and invalid limits.
  - Staff/user denial for admin APIs and UI.
  - Locked feature state for users assigned plans without specific capabilities.

## Verification Targets

- Every feature in the server-side entitlement code appears in the feature catalog.
- Every plan limit has both UI validation and API validation tests.
- Admin actions emit audit logs and display success/failure states.
