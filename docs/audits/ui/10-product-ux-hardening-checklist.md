# Product UX & security hardening (public, customer-facing)

Checklist for releases when the product is exposed to paying customers. Use alongside per-area audit files (01–09).

## Entitlements

- [ ] Every premium surface has either access or a clear “upgrade” path (sidebar pattern in `base.html` / `confirm.js`).
- [ ] API returns **403/402** (as appropriate) when feature flags deny — UI must not be the only enforcement.
- [ ] Admins and staff expectations documented (bypass gating, operator limits).

## Security

- [ ] No secrets in client bundles; no API keys in templates.
- [ ] Admin routes not listed in API docs for non-admin API-key users.
- [ ] Session idle / lockout / rate limits verified under load (see `tests/run_load_tests.sh`).

## UX

- [ ] Public onboarding: setup, register, legal, a11y (see `04-public-onboarding-legal-accessibility.md`).
- [ ] Error pages: consistent layout, no stack traces in production.
- [ ] Mobile nav and critical flows (see `test_mobile_layout.py`).

## Observability

- [ ] Correlation between UI actions and audit log events for admin operations.
- [ ] Health and dependency panels accurate for operators.

**Animations:** keep subtle; respect `prefers-reduced-motion` where custom motion exists (audit incremental).
