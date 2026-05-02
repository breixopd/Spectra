## Summary

UI is **Jinja2** under `services/api/templates/` (app shell via `base.html`, public `landing.html`, auth via `auth_layout.html`). Styling: `services/api/static/css/` (incl. compiled `output.css`). **No HTMX**—no `hx-` usage; interactivity is **vanilla JS** (`/static/js/api.js`, `data-action` / `data-on-input` patterns). Routers: `spectra_api/ui/pages.py` (dashboard, settings, shell, etc.), `spectra_api/ui/public.py` (landing, legal, register, changelog), `spectra_api/api/routers/admin/users.py` (`GET /admin`). **Auth** uses cookie/JWT + `get_ui_user` redirects, `require_feature` for `/manual` and `/docs/api`, role/permission checks for observability, **admin/superuser** for the admin HTML page.

## Resolved in-tree (2026-05)

- **Password toggle** — `macros/forms.html` uses `aria-label="Show password"` on the visibility control.
- **Mission target / directive** — `dashboard.html` inputs have `aria-label` (and test ids).
- **Shell missing session** — `pages.py` `shell_page` returns themed `errors/404.html` with detail.
- **Verify email branding** — `verify_email.html` title uses `{{ app_name }}`.
- **Modal dialog name** — `partials/modal.html` gains optional `aria_label` and default `aria-label="Dialog"` when no title/`title_id`.
- **Dashboard selects / requirements** — `aria-label` on VPN config, adversary playbook, and mission requirements textarea.

## Suspected / future

- `manual_tools.html` and other dense tool pages: spot-check labels / `aria-*` (high surface area).
- `data-tooltip` custom UI vs accessible descriptions — verify `static/js` behaviour.
- Full `services/api/static/js/**` focus management, live regions, keyboard traps.
- Line-by-line pass over all `admin/_*.html`, `plugin_creator.html`, `overseer.html`, `observability.html` body content.

## Recommendations (prioritized)

1. WCAG-oriented pass on long forms (`manual_tools.html` et al.).
2. Document the “fetch + templates” contributor pattern (no HTMX) in `docs/wiki/frontend-patterns.md` if not already centralised there.
