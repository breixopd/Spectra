# Frontend Patterns

[← Wiki Home](home.md) | [Architecture](architecture.md) | [Design Tokens](design-tokens.md) | [Development](development.md)

---

Spectra's frontend uses CSP-safe event delegation, Jinja2 macros, and consistent test attribute conventions. This page documents the patterns used across all templates and JavaScript modules.

## Event Delegation

All interactive elements use data-attribute delegation instead of inline event handlers (`onclick`, `onsubmit`). This is required for Content Security Policy (CSP) compliance, since inline handlers are blocked under a strict nonce-based CSP.

The delegation module lives at `services/api/static/js/modules/delegated-events.js` and is loaded on every page.

### `data-action` — Click Delegation

Any clickable element can use `data-action` to bind a click handler to a global function:

```html
<button data-action="deleteMission">Delete</button>
<button data-action="filterShells" data-value="reverse">Reverse Shells</button>
```

**How it works:**

1. A single `click` listener on `document` finds the closest `[data-action]` element.
2. It looks up `window[action]` where `action` is the `data-action` value.
3. If `data-value` is present, the handler receives `(value, element, event)`.
4. If `data-value` is absent, the handler receives `(element, event)`.

```javascript
// Handler definition (in a page module or inline script)
window.deleteMission = function (el, e) {
    const id = el.dataset.missionId;
    // ...
};

window.filterShells = function (value, el, e) {
    // value is the data-value string
};
```

**Convention:** Handler names are camelCase and match the `data-action` value exactly. On `localhost`, missing handlers produce a console warning.

### `data-on-submit` — Form Delegation

Forms use `data-on-submit` to bind a submit handler that automatically calls `preventDefault()`:

```html
<form data-on-submit="handleLogin">
    <input type="text" name="username">
    <input type="password" name="password">
    <button type="submit">Log In</button>
</form>
```

```javascript
window.handleLogin = function (e) {
    // e.preventDefault() is called automatically
    const form = e.target;
    const data = new FormData(form);
    // ...
};
```

**How it works:**

1. A single `submit` listener on `document` finds the closest `[data-on-submit]` form.
2. It calls `e.preventDefault()` automatically.
3. It looks up `window[action]` and calls it with the event object.

### `data-on-change` — Change Delegation

Select elements and other inputs use `data-on-change`:

```html
<select data-on-change="refreshMetrics">
    <option value="24h">Last 24 hours</option>
    <option value="7d">Last 7 days</option>
</select>
```

```javascript
window.refreshMetrics = function (el, e) {
    const period = el.value;
    // ...
};
```

### `data-on-input` — Input Delegation

Text inputs and textareas use `data-on-input` for live filtering:

```html
<input type="text" data-on-input="filterTable">
```

```javascript
window.filterTable = function (el, e) {
    const query = el.value.toLowerCase();
    // ...
};
```

### Built-in Global Handlers

The delegation module provides these global helpers:

| Function | Purpose |
|----------|---------|
| `window.reloadPage()` | Reload the current page |
| `window.goBack()` | Navigate to the previous page |
| `window.clipCopy(value)` | Copy a string to the clipboard |
| `window.clipCopyStop(value, el, e)` | Copy + stop event propagation |
| `window.clipCopyCode(el)` | Copy text content from a sibling `<code>` element |
| `window.closeSpectraModal()` | Remove the dynamic modal from the DOM |

---

## Test Attributes (`data-testid`)

Playwright E2E tests use `data-testid` attributes for stable, implementation-agnostic selectors. These are the canonical way to select elements in tests.

### Convention

- Use `data-testid` on interactive elements and key containers.
- Values use kebab-case, describing the element's role: `data-testid="launch-btn"`, `data-testid="sidebar"`, `data-testid="mission-target"`.
- Do not use CSS classes or element IDs as primary selectors in tests; prefer `data-testid`.

### Current Test IDs

| Element | Location | `data-testid` |
|---------|----------|---------------|
| Sidebar | `services/api/templates/base.html` | `sidebar` |
| Admin nav link | `services/api/templates/base.html` | `admin-nav-link` |
| Mission target input | `services/api/templates/dashboard.html` | `mission-target` |
| Mission directive input | `services/api/templates/dashboard.html` | `mission-directive` |
| Launch button | `services/api/templates/dashboard.html` | `launch-btn` |
| Getting started panel | `services/api/templates/dashboard.html` | `getting-started` |
| API docs search | `services/api/templates/docs.html` | `api-docs-search` |

### Adding New Test IDs

When adding new interactive elements to templates, include a `data-testid` attribute:

```html
<button data-action="saveSettings" data-testid="save-settings-btn">Save</button>
```

In Playwright tests:

```javascript
await page.getByTestId('save-settings-btn').click();
```

---

## Modal Macro

The modal macro (`services/api/templates/partials/modal.html`) provides a consistent, accessible modal component.

### Usage

```html+jinja
{% from "partials/modal.html" import modal %}

{% call modal(id='confirm-delete', title='Delete Mission', size='md', icon='trash-2') %}
    <p class="text-slate-300 mb-4">Are you sure you want to delete this mission?</p>
    <div class="flex justify-end gap-3">
        <button data-action="closeSpectraModal" class="btn-cancel">Cancel</button>
        <button data-action="confirmDelete" class="btn-danger">Delete</button>
    </div>
{% endcall %}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | string | required | Unique DOM ID for the modal container |
| `title` | string | `''` | Modal heading text. If empty, the heading is omitted. |
| `size` | string | `'md'` | Width class: `sm`, `md`, `lg`, `xl`, `full` |
| `icon` | string | `''` | Lucide icon name (e.g., `'trash-2'`, `'shield'`) |
| `backdrop_close_action` | string | `''` | If set, clicking the backdrop calls this `data-action` handler |
| `title_id` | string | `''` | Custom ID for the title element (for `aria-labelledby`) |

### Size Classes

| Size | CSS Class | Approximate Width |
|------|-----------|-------------------|
| `sm` | `max-w-sm` | ~384px |
| `md` | `max-w-md` | ~448px |
| `lg` | `max-w-lg` | ~512px |
| `xl` | `max-w-2xl` | ~672px |
| `full` | `max-w-full mx-4` | Full width with margin |

### Accessibility

The modal includes `role="dialog"` and `aria-modal="true"`. When a `title` is provided, `aria-labelledby` points to the heading element. Use `title_id` for custom heading IDs when needed.

---

## Feature Gate Macro

The feature gate macro (`services/api/templates/macros/feature_gate.html`) provides server-side feature gating based on the user's plan.

### Usage

```html+jinja
{% from "macros/feature_gate.html" import feature_gate %}

{% call feature_gate('advanced_reporting', 'Professional') %}
    <div class="advanced-report-content">
        <!-- Content only visible to users with the feature -->
    </div>
{% endcall %}
```

### How It Works

1. The route handler passes `user_features=dict(feature_name=True|False)` in the template context.
2. If `user_features` is absent, the macro renders content by default (graceful degradation).
3. If the feature is disabled, a locked placeholder is shown with the plan name and an upgrade link.

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `feature_name` | string | Key in `user_features` dict (e.g., `'advanced_reporting'`) |
| `plan_required` | string | Display name of the required plan (e.g., `'Professional'`) |

### Locked State Appearance

When a feature is gated, the macro renders:

```html
<div class="glass-panel rounded-xl p-6 text-center border border-white/5 opacity-60">
    <i data-lucide="lock" class="w-6 h-6 inline-block text-slate-500 mb-3"></i>
    <p class="text-sm text-slate-400">This feature requires the <strong class="text-white">Professional</strong> plan.</p>
    <a href="/profile#plan" class="mt-4 inline-block px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm font-medium transition-colors">Upgrade Plan</a>
</div>
```

---

## Related Pages

- [Design Tokens](design-tokens.md) — CSS custom properties, color palette, typography, spacing
- [Architecture](architecture.md) — Service architecture, caching, communication patterns
- [Development](development.md) — Local setup, testing, contributing