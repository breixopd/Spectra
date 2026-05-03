# UI Templates Audit — 2026-05-03

## HIGH PRIORITY

### 1. Extract Inline Scripts
- **base.html:156-383** — 227 lines: WebSocket, status polling, logout → `js/pages/dashboard/websocket.js`
- **base.html:385-405** — 20 lines: Sidebar toggle → `js/modules/sidebar.js`
- **base.html:412-426** — escapeHtml, escapeAttr, togglePasswordVisibility → `js/modules/dom-utils.js`
- **login.html:90-241** — 151 lines: Login form, MFA handling → `js/pages/auth/login.js`
- **landing.html:538-540** — Lucide icons init → `js/modules/icons.js`

### 2. Duplicate HTML Patterns
- Navigation items in base.html:64-115 repeated 13x → create `macros/navigation.html`
- Admin sidebar identical to profile sidebar → create reusable sidebar macro
- FAQ items on landing page repeat same structure → data-driven loop

### 3. Inline Styles
- landing.html:108-178 — Hero preview ~40 lines inline → CSS classes
- Multiple `style="margin-left:auto;margin-right:auto;"` → `.mx-auto`
- dashboard.html:200,341 — min-height styles → CSS classes

### 4. Missing Loading States
- Dashboard launch button (line 57-59)
- Profile save buttons (line 85-87)
- Settings save button (line 12-14)
- Login submit button (line 49-51)

## MEDIUM PRIORITY

### 5. Missing ARIA Attributes
- base.html:46-49: Hamburger missing aria-expanded
- dashboard.html:57: Launch button missing aria-disabled
- login.html:43: Password toggle missing aria-pressed

### 6. Hardcoded Values
- base.html:9: theme-color="#8b5cf6" → CSS variable
- base.html:30: bg-[#0a0e1a] → CSS variable
- landing.html:528: Copyright "2026" → dynamic year

### 7. Empty States
- Profile > API Keys → add empty state
- Profile > Activity → add empty state
- Admin > Users → add empty state
- Create reusable `macros/empty-state.html`

### 8. Error States
- Dashboard: no error toast on API failure
- Profile: save errors not shown
- Settings: form validation errors not displayed
- Create reusable error display pattern

## LOW PRIORITY

### 9. Commented-Out HTML
- Remove all dead HTML blocks

### 10. Non-Responsive Elements
- landing.html: pricing table mobile
- profile.html: sidebar mobile collapse
