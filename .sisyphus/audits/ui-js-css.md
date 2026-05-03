# UI JavaScript & CSS Audit — 2026-05-03

## DESIGN TOKENS (CRITICAL)

Create single source of truth `css/tokens.css`:
```css
:root {
  --color-bg: #0a0e1a;
  --color-bg-elevated: #020617;
  --color-border: rgba(255,255,255,0.1);
  --color-primary: #8b5cf6;
  --color-primary-hover: #7c3aed;
  --color-success: #00ff88;
  --color-warning: #fbbf24;
  --color-error: #f87171;
  --color-text: #e2e8f0;
  --color-text-muted: #64748b;
  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --spacing-xs: 0.25rem;
  --spacing-sm: 0.5rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
}
```

## JAVASCRIPT

### HIGH — Duplicate Logic
- api.js:16-22 & shared-utils.js — debounce defined twice → consolidate
- base.html:413-421 & shared-utils.js:47-54 — escapeAttr duplicated → use one
- base.html:157-163 & api.js:42-46 — clearSpectraLocalStorage duplicated → consolidate

### MEDIUM — Hardcoded API URLs
- login.html: `/api/v1/auth/mfa/cancel`, `/api/v1/auth/mfa/verify`
- login.html: `/api/v1/auth/token`
- base.html: `/api/v1/auth/logout`, `/api/v1/system/status/quick`
- Create `js/constants/api.js` with API_ENDPOINTS

### MEDIUM — Missing Error Handling
- login.html:199-240 — no try/catch around fetch
- Dashboard — some async operations lack error handling
- Profile — many API calls lack error states

## CSS

### HIGH — Duplicate Styles
- base.css & landing.css — cookie consent banner IDENTICAL
- dark-theme-tokens.css — duplicate `:root` with landing.css
- landing.css:669-685 — skip link should be in base.css

### MEDIUM — Missing Responsive
- landing.css:722-728 — pricing table mobile
- dashboard — panels lack mobile stacking
- profile — sidebar mobile collapse

### LOW — Unused CSS
- output.css — Tailwind output needs purge
- base.css — legacy styles may be unused
