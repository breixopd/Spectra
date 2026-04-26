# UI Audit: Dashboard, Landing, Marketing

Status: loop 1 draft  
Scope: `app/templates/landing.html`, `app/templates/dashboard.html` (or equivalent), shared stats/CTA components, public vs authenticated shell.

## What Looks Good

- Landing and app shell are separated; public marketing content does not require auth.
- Dashboard “getting started” and primary actions are discoverable from existing e2e coverage.

## Findings

- **Component reuse:** hero, stat grids, and feature cards are largely inline; extracting macros/partials would reduce drift between landing and in-app “empty states.”
- **Entitlement CTAs:** upgrade paths should be consistent (copy, `href`, analytics) wherever a feature is teased on marketing vs locked in-app.
- **Performance:** large inline SVG/icon usage and animation classes should be audited for LCP; consider lazy-loading below-the-fold sections.
- **Accessibility:** verify heading order, focus order for cookie banner, and color contrast on gradient backgrounds.

## Research Notes

- Marketing pages convert better with a single primary CTA per viewport; secondary actions as text links.
- B2B security products benefit from “proof” blocks: compliance posture, deployment model, and data handling without cluttering the hero.

## Recommended Work

- Introduce shared partials: `components/hero.html`, `components/stat_grid.html`, `components/feature_card.html` (Jinja includes).
- Add visual regression or Playwright snapshot checks for landing above-the-fold (optional, if flakiness is controlled).
- Map every landing CTA to a tracked event name for later analytics.

## Verification Targets

- Playwright: landing pricing/FAQ, auth paths, mobile layout (existing); extend with keyboard focus smoke for primary CTA.
- No broken links to `/docs`, `/register`, `/login` from landing footer.
