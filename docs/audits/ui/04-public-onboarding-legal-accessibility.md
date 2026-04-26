# UI Audit: Public, Onboarding, Legal, Accessibility

Status: loop 1 draft
Scope: landing, login/register/setup, password reset, legal pages, cookie consent, error pages, mobile/accessibility.

## What Looks Good

- Public pages have SEO metadata, Open Graph metadata, cookie consent tests, and legal page coverage.
- Login/register/reset/setup flows are represented in E2E tests.
- Error pages are present for common HTTP states and are covered at a basic level.

## Findings

- `landing.html` is very large and includes inline preview markup/styles that should be split into reusable sections or landing partials.
- The landing page copy is still broad. For enterprise buyers, it should speak more directly to validated exploit proof, CTEM, evidence, worker isolation, compliance exports, and remediation verification.
- Accessibility coverage is mostly implicit through locator usage. There is no automated axe-style accessibility scan or keyboard-flow suite.
- Signup/onboarding should be plan-aware. If self-service signup assigns a default plan, the user should see exactly what is enabled, what is locked, and how to upgrade.
- Error pages should include recovery actions by context: login again, request access, contact admin, retry, view status, or open docs.

## Research Notes

- Enterprise UX should use progressive disclosure and just-in-time onboarding rather than large static tours.
- Security UX should add "graceful friction": explain timeouts, consent, authorization checks, and denials without making users lose work.
- Empty states should tell users why a surface is empty, what to do next, and what it will look like when populated.

## Recommended Work

- Split public pages into partials:
  - nav
  - hero
  - stats/social proof
  - capability cards
  - workflow
  - pricing
  - FAQ
  - footer
- Add accessibility test coverage:
  - keyboard navigation for landing/login/admin/dashboard.
  - visible focus states.
  - labelled inputs and buttons.
  - dialog focus trap checks.
  - color/contrast audit with an axe-compatible tool in Docker.
- Add onboarding states per plan and role after first login.
- Add upgrade prompts that are informative but not blocking inside critical workflows.

## Verification Targets

- Public pages pass accessibility smoke checks.
- Cookie, privacy, deletion, processing restriction, and export flows are tested as user-visible compliance workflows.
- Every onboarding CTA goes to a working route for the current role and plan.
