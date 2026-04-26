# Spectra UI/UX Audit Report

**Date**: 2026-04-27
**Auditor**: Automated Codebase Analysis

---

## 1. File Structure & Organisation

### Current Layout
```
static/
├── css/           # 10 CSS files (input.css, output.css, landing.css, base.css, auth.css, admin.css, dashboard.css, errors.css, legal.css, observability.css, dark-theme-tokens.css)
├── js/            # Root-level scripts (api.js, confirm.js, dashboard.js, landing.js, targets.js, settings.js, toolbox.js, cookie-consent.js)
│   ├── modules/   # Reusable JS (modal.js, toast.js, accordion.js, delegated-events.js, tabs.js, utils.js, severity.js)
│   └── pages/     # Page-specific JS (admin/, dashboard/, settings/, manual-tools/)
└── vendor/        # Third-party libraries

templates/
├── partials/      # _delete_mission_modal.html, _cookie_consent.html, head.html, shield_svg.html
├── macros/        # forms.html, layout.html
├── admin/         # _users.html, _plans.html, _dashboard.html, _services.html, _scaling.html, _sidebar.html
├── legal/         # privacy.html, terms.html, cookies.html
├── errors/        # 403.html, 404.html, 500.html
└── *.html         # Root-level page templates (base.html, landing.html, dashboard.html, etc.)

tests/e2e/ui/
├── conftest.py
├── harness/
│   ├── navigation.py
│   └── db_user.py
└── test_*.py      # ~20 Playwright test files
```

**Verdict:** Generally logical. Good separation of macros, partials, and page templates. JS modules and pages are well separated.

**Issues:**
- `landing.css` (747 lines) re-declares its own CSS custom properties rather than importing from `input.css`, creating token duplication.
- No `app/views/` directory (mentioned in task description but not found).
- CSS is somewhat scattered across 10+ files.

---

## 2. Component Reusability

**Positive:**
- `macros/forms.html` has reusable form components: `form_input`, `form_select`, `form_password`, `form_toggle`, `password_requirements`, `glass_panel`, `btn_primary`, `btn_secondary`, `btn_danger`, `stat_card`, `empty_state`, `status_badge`.
- `macros/layout.html` has `section_header`, `page_card`, `tab_nav`.
- `partials/_delete_mission_modal.html` is a reusable modal.
- `modules/severity.js` centralizes severity mapping (replacing 5+ duplicate mappings).
- `modules/toast.js` is a canonical toast notification system.
- `modules/modal.js` is a unified modal with focus trapping and keyboard handling.

**Issues:**
- Modal HTML is duplicated across templates: add-target modal in `targets.html`, delete modal in `history.html`, playbook modal in `dashboard.html`, finding-detail modal in `dashboard.html`.
- Inline styles in `landing.html`: 30+ `style=""` attributes on hero preview elements.
- `settings.html` (553 lines) is massive with forms for 7+ sections inlined.
- Target card in `targets.html` uses `<template>` element with inline JS — good pattern but could be a shared component.

---

## 3. Styling & Theming

**Positive:**
- Design tokens via CSS custom properties in `input.css` (severity colors, status colors, glass tokens, transition tokens).
- Tailwind CSS used as utility framework.
- `dark-theme-tokens.css` for standalone pages.
- `prefers-reduced-motion` respected in `input.css` and `landing.css`.
- Responsive design with mobile breakpoints.

**Issues:**
- Token duplication: `landing.css` declares its own tokens (`--bg: #0a0a0f`, `--accent: #00ff88`) that differ from `input.css` (`--surface-base: #020617`). Landing page and app shell have different dark backgrounds.
- No design token documentation — colors scattered across files.
- `output.css` is 54KB — no visible purge/tree-shaking.
- Inline Tailwind classes are verbose but maintainable.

---

## 4. JavaScript Logic

**Positive:**
- `api.js` (189 lines): Excellent centralized API client with auth token management, CSRF injection, 401 refresh-retry, rate limit handling, and debounce.
- `confirm.js` (130 lines): Global confirm/prompt dialogs with plan-gating logic for `data-entitlement-gate`.
- ES modules used in `modal.js`, `toast.js`, `tabs.js`, `severity.js`.
- Event delegation via `delegated-events.js`.
- Custom `ReconnectingWebSocket` with exponential backoff.

**Issues:**
- Global namespace pollution: `dashboard.js` exposes ~15 functions via `window.*` (toggleRequirements, togglePresetsDropdown, launchFromForm, etc.).
- `dashboard.js` is 515 lines — single large file coordinating all dashboard behavior.
- `findings.js` uses `var` declarations instead of `let`/`const`.
- No build step (no Webpack/Vite/Parcel) — vanilla JS with `<script type="module">` tags.
- Module loading order dependencies: sub-modules loaded via `<script>` tags before `dashboard.js`.
- `_spectraToast` stub pattern in `confirm.js` is functional but inelegant.

---

## 5. Accessibility (a11y)

**Positive:**
- Skip links in `landing.html` and `base.html` with proper `:focus` styling.
- ARIA labels on nav (`aria-label="Main navigation"`), dashboard (`aria-label="Mission control"`), login (`aria-required="true"`, `aria-describedby`, `aria-live="polite"`).
- Role attributes: `role="dialog"`, `role="tablist"`, `role="tab"`, `role="menu"`, `role="status"`.
- Modal accessibility: focus trapping and Escape key handling in `modal.js`.
- Keyboard accessible FAQ with `aria-expanded` and `aria-controls`.

**Issues:**
- `targets.html` line 91: `<form data-on-submit="handleAddTarget">` relies on delegated-events, no `onsubmit` handler.
- Pricing table `<th>` elements need `scope` attributes for screen readers.
- `settings.html`: many inputs lack explicit `<label>` associations, using `placeholder` instead.
- Color contrast: `landing.css` `--text-muted: #64748b` on `#0a0a0f` may fail WCAG AA (4.5:1).
- Some custom toggle switches use `peer-focus:ring-4` which may not be visible for all users.

---

## 6. Animations & Interactions

**Positive:**
- CSS transitions for all animations — no heavy JS animation libraries.
- Scroll reveal in `landing.js` uses `IntersectionObserver` (performance-conscious, unobserves after triggering).
- Staggered animations via `stagger-1`, `stagger-2` classes.
- Landing page hero has CSS keyframe animations (`preview-progress`, `preview-pulse`, etc.) with `aria-hidden="true"`.
- Button press effect: `button:active:not(:disabled) { transform: scale(0.97); }`.
- FAQ accordion uses CSS `max-height` transition.

**Issues:**
- Hero preview animations have no `prefers-reduced-motion` override.
- Toast dismissal uses `setTimeout` + CSS transition — rapid dismissal could feel abrupt.
- Scroll reveal uses `setTimeout` with `i * 60` stagger — many simultaneous timers if many elements in viewport.

---

## 7. Landing Page & Marketing

**Positive:**
- Professional, modern design with clear visual hierarchy.
- Clear CTAs: "Get Started Free" primary, "See How It Works" secondary.
- SEO optimized: Open Graph, Twitter Card, Schema.org structured data.
- Feature showcase: 4-card grid with icons.
- How It Works: 3-step visual process.
- Pricing table: dynamic server-side rendering from `plans` context.
- Social proof: stats bar with real metrics.
- Testimonials: dynamic from database.
- FAQ: 5-question accordion.
- Mobile responsive.
- Cookie consent banner (GDPR-compliant).

**Issues:**
- `og:image` references `/static/og-image.png` but actual file is `og-image.svg` — MISMATCH.
- Landing page `<html>` lacks `lang="en"`.
- Pricing table hidden if `plans` is empty — no "Contact for Enterprise" fallback.
- Sticky CTA on mobile mixes Tailwind classes with inline `style="display:none;"`.
- No trust signals (SOC2, ISO27001 badges, client logos).

---

## 8. Dynamic UI / Feature Gating

**Positive:**
- `data-entitlement-gate` attribute system in `base.html`.
- `confirm.js` reads user plan features from `/api/v1/auth/me`, adds `pointer-events-none opacity-40` to gated elements, sets `aria-disabled="true"`, and injects upgrade link.
- Tests in `test_entitlement_sidebar.py` verify gated links, upgrade visibility, and unlocked links.

**Issues:**
- Entitlement gate only works on `<a>` tags — non-link elements won't be properly gated.
- Upgrade link always goes to `/profile#plan` — profile page may not have plan section without JS.
- **No server-side gating** — all gating is client-side via JS. Users could inspect JS to find gated URLs.
- Manual Tools redirect: if `manual_mode` isn't seeded, user is redirected rather than shown an upgrade prompt.

---

## 9. Skipped / Flaky Tests

**Skipped Tests (6 total):**

| File | Line | Condition |
|------|------|-----------|
| `conftest.py` | 428 | `DATABASE_URL` not set |
| `conftest.py` | 446 | Manual mode seeding failed |
| `db_user.py` | 75 | `DATABASE_URL` not set |
| `db_user.py` | 118 | `DATABASE_URL` not set |
| `test_mobile_layout.py` | 110 | Non-admin user |

**Flakiness Indicators:**
- `test_bootstrap.py` only has 2 tests — very thin coverage.
- `test_page_coverage.py` tests 12 pages but only checks headings/presence, not functional behavior.
- Test pattern inconsistency: some use `logged_in_page`, others `fresh_authenticated_page`, others plain `page`.
- Thread-based timeout (`conftest.py` lines 19-30): `pytest.mark.timeout(method="thread")` — known flakiness potential.
- Auth suppression init script (`conftest.py` lines 45-73): mocks 401 responses to prevent redirect loops, suppressing real auth failures.

---

## 10. General UX

**Positive:**
- Toast notifications (`_spectraToast()`) used consistently.
- Loading states: skeleton loaders, spinner icons, `animate-spin`.
- Error states: `dashboard-error` element with retry button.
- Empty states: getting started card, `dash-empty` class, `empty-state` macro.
- Tooltips: `data-tooltip` system with 4 positions via CSS-only in `base.css`.
- Consistent navigation: sidebar on all authenticated pages, skip-to-content link.
- Keyboard shortcuts: Enter key on mission launch form.
- Mobile sidebar: hamburger menu with overlay.
- Confirmation dialogs: `_spectraConfirm()` for destructive actions.

**Issues:**
- `data-on-submit` in `targets.html` uses custom attribute instead of standard `onsubmit`.
- No breadcrumb on most pages (only `admin.html` and `settings.html` have them).
- `settings.html` is too long (553 lines) — could benefit from tab navigation.
- No persistent notification center — only ephemeral toasts.
- `admin.html` line 45: `max-height:calc(100vh - 10rem);` — hardcoded pixel offset.
- No loading indicator on form submit in `login.html` — uses raw `fetch` not `spectraApi`.

---

## Critical Issues Summary

| # | Category | File | Issue | Severity |
|---|----------|------|-------|----------|
| 1 | Theming | `landing.css` | Duplicate CSS tokens from `input.css`, different dark bg | Medium |
| 2 | Accessibility | `landing.css` | `#64748b` on `#0a0a0f` may fail WCAG AA | Medium |
| 3 | OG Image | `landing.html` | References `og-image.png` but file is `og-image.svg` | Low |
| 4 | JS Architecture | `dashboard.js` | 515-line file exposing 15+ globals | Medium |
| 5 | Feature Gating | `confirm.js` | Client-side only, no server-side enforcement | **High** |
| 6 | CSS Build | `output.css` | 54KB compiled Tailwind, no build optimization | Low |
| 7 | Test Skips | Multiple | 6 `pytest.skip()` calls | Medium |
| 8 | Accessibility | `settings.html` | Many inputs use placeholder instead of label | Medium |
| 9 | Animations | `landing.css` | Hero animations ignore `prefers-reduced-motion` | Low |
| 10 | Component Reuse | Templates | Modal HTML duplicated across 4+ templates | Medium |

---

## Recommended Refactorings (Priority Order)

### High Priority
1. **Server-side feature gating**: Implement backend redirects/404s for gated routes, not just client-side JS.
2. **Unify CSS tokens**: Create a single `tokens.css` imported by both `input.css` and `landing.css`.
3. **Extract reusable modal partial**: Create `partials/modal.html` macro with `id`, `title`, `size` parameters.

### Medium Priority
4. **Decompose `dashboard.js`**: Split into ES modules imported by a main module. Use `import`/`export` instead of `window.*` globals.
5. **Add `aria-label` on all inputs** in `settings.html` and replace placeholder-only labels with proper `<label for="...">`.
6. Fix `og-image.png` vs `og-image.svg` mismatch.
7. Add `prefers-reduced-motion` override for hero preview animations.
8. Reduce `output.css` bundle size (enable Tailwind purge in build).
9. Add breadcrumbs to `dashboard.html`, `targets.html`, `history.html`.
10. Document the `data-on-submit` and `data-action` delegation patterns.
