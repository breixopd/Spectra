# Design Tokens

[← Wiki Home](home.md) | [Frontend Patterns](frontend-patterns.md) | [Architecture](architecture.md)

---

Spectra's visual design system is built on CSS custom properties defined in `services/api/static/css/input.css` and extended through Tailwind CSS configuration in `config/tailwind.config.js`. This page documents every token so UI changes stay consistent.

## Source Files

| File | Purpose |
|------|---------|
| `services/api/static/css/input.css` | CSS custom properties (`:root` variables), component classes, reduced-motion overrides |
| `config/tailwind.config.js` | Tailwind theme extensions (brand colors, fonts, animations) |
| `config/postcss.config.js` | PostCSS pipeline (autoprefixer + cssnano for production builds) |

---

## Color Palette

### Surfaces

| Token | Value | Usage |
|-------|-------|-------|
| `--surface-base` | `#020617` (slate-950) | Page background, darkest surface |
| `--surface-raised` | `rgba(15, 23, 42, 0.6)` | Card backgrounds, elevated panels |
| `--surface-overlay` | `rgba(2, 6, 23, 0.8)` | Sidebar, overlay backgrounds |

### Borders

| Token | Value | Usage |
|-------|-------|-------|
| `--border-subtle` | `rgba(255, 255, 255, 0.05)` | Default card/panel borders |
| `--border-hover` | `rgba(255, 255, 255, 0.08)` | Border color on hover |
| `--border-focus` | `rgba(139, 92, 246, 0.4)` | Focus ring (violet tint) |

### Text

| Token | Value | Usage |
|-------|-------|-------|
| `--text-primary` | `#ffffff` | Headings, primary content |
| `--text-secondary` | `#94a3b8` (slate-400) | Body text, descriptions |
| `--text-muted` | `#8896ab` | Muted labels, secondary info |
| `--text-disabled` | `#475569` (slate-600) | Disabled states |

### Brand

| Token | Value | Usage |
|-------|-------|-------|
| `--brand-primary` | `#8b5cf6` (violet-500) | Primary buttons, links, accents |
| `--brand-primary-hover` | `#a78bfa` (violet-400) | Hover state for brand elements |
| `--brand-primary-glow` | `rgba(139, 92, 246, 0.2)` | Glow/shadow for brand elements |

### Severity (Security Findings)

| Token | Value | Background Token |
|-------|-------|-------------------|
| `--severity-critical` | `#f43f5e` (rose-500) | `--severity-critical-bg`: `rgba(244, 63, 94, 0.15)` |
| `--severity-high` | `#f59e0b` (amber-500) | `--severity-high-bg`: `rgba(245, 158, 11, 0.15)` |
| `--severity-medium` | `#fbbf24` (amber-400) | `--severity-medium-bg`: `rgba(251, 191, 36, 0.15)` |
| `--severity-low` | `#34d399` (emerald-400) | `--severity-low-bg`: `rgba(52, 211, 153, 0.15)` |
| `--severity-info` | `#60a5fa` (blue-400) | `--severity-info-bg`: `rgba(96, 165, 250, 0.15)` |

### Status

| Token | Value | Usage |
|-------|-------|-------|
| `--status-success` | `#10b981` (emerald-500) | Success states, online indicators |
| `--status-warning` | `#f59e0b` (amber-500) | Warning states |
| `--status-error` | `#ef4444` (red-500) | Error states, destructive actions |
| `--status-running` | `#fbbf24` (amber-400) | In-progress indicators |

### Glass Effect

| Token | Value | Usage |
|-------|-------|-------|
| `--glass-bg` | `rgba(15, 23, 42, 0.6)` | Glass panel background |
| `--glass-blur` | `12px` | Backdrop blur radius |
| `--glass-sidebar-bg` | `rgba(2, 6, 23, 0.8)` | Sidebar glass background |
| `--glass-sidebar-blur` | `16px` | Sidebar backdrop blur radius |

### Tailwind Brand Colors

Extended in `config/tailwind.config.js`:

| Name | Shade 400 | Shade 500 | Usage |
|------|-----------|-----------|-------|
| `slate` | — | — | `slate-950` (`#020617`) added as darkest surface |
| `emerald` | `#34d399` | `#10b981` | Success, severity-low |
| `violet` | `#a78bfa` | `#8b5cf6` | Brand primary, buttons, links |
| `rose` | `#fb7185` | `#f43f5e` | Destructive actions, severity-critical |
| `amber` | `#fbbf24` | `#f59e0b` | Warnings, severity-high/medium |

---

## Typography

### Font Families

| Token | Value | Usage |
|-------|-------|-------|
| `font-sans` | `Inter, sans-serif` | Body text, UI elements |
| `font-mono` | `"JetBrains Mono", monospace` | Code blocks, terminal output, method badges |

### Font Loading

Inter and JetBrains Mono are loaded via CDN in `services/api/templates/base.html`. No local font files are bundled.

### Usage in Templates

```html
<p class="font-mono text-sm text-slate-400">Code-like text</p>
<span class="font-sans text-base text-white">Regular UI text</span>
```

---

## Spacing

Spectra uses Tailwind CSS default spacing scale. Common values:

| Token | Value | Usage |
|-------|-------|-------|
| `p-1` / `px-1` | 4px | Tight padding (badges, small buttons) |
| `p-2` / `px-2` | 8px | Compact padding (table cells, small inputs) |
| `p-3` / `px-3` | 12px | Default padding (buttons, cards) |
| `p-4` / `px-4` | 16px | Comfortable padding (card bodies, modals) |
| `p-6` | 24px | Spacious padding (page sections, modal bodies) |
| `gap-2` | 8px | Default flex gap |
| `gap-3` | 12px | Section gap |
| `gap-4` | 16px | Large section gap |
| `mb-1` | 4px | Tight bottom margin |
| `mb-4` | 16px | Standard bottom margin |
| `mb-6` | 24px | Section bottom margin |

---

## Motion

### Transition Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--transition-fast` | `0.15s ease` | Hover states, small interactions |
| `--transition-normal` | `0.3s ease` | Default transitions, panel reveals |
| `--transition-slow` | `0.5s ease` | Page transitions, large animations |

### Animation Tokens

| Name | Value | Usage |
|------|-------|-------|
| `animate-pulse-slow` | `pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite` | Status indicators, loading dots |

Defined in `config/tailwind.config.js`:

```javascript
animation: {
    'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
}
```

### Reduced Motion

`services/api/static/css/input.css` includes a `prefers-reduced-motion` media query that disables all animations and transitions for users who prefer reduced motion:

```css
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
```

---

## Component Classes

Defined in `services/api/static/css/input.css` under `@layer components`:

| Class | Purpose |
|-------|---------|
| `.btn-primary` | Primary action button (violet, shadow) |
| `.btn-danger` | Destructive action button (rose) |
| `.btn-cancel` | Cancel/secondary button (slate, bordered) |
| `.btn-sm` | Small button size modifier |
| `.glass-panel` | Glassmorphism card (blur, subtle border, hover effect) |
| `.form-input` | Dark input field with focus ring |
| `.form-label` | Form label (slate-400, small) |
| `.severity-critical` | Critical severity badge |
| `.severity-high` | High severity badge |
| `.severity-medium` | Medium severity badge |
| `.severity-low` | Low severity badge |
| `.severity-info` | Info severity badge |

---

## Building CSS

### Development

```bash
make css-watch    # Watch and rebuild on changes
make css-build    # One-time production build (Tailwind only)
```

### Production

```bash
make css-build-prod    # Full PostCSS pipeline: Tailwind + autoprefixer + cssnano
```

The production build uses `config/postcss.config.js` which runs autoprefixer for browser compatibility and cssnano for minification. Output goes to `services/api/static/css/output.css`.

---

## Related Pages

- [Frontend Patterns](frontend-patterns.md) — Event delegation, modals, feature gates
- [Architecture](architecture.md) — Service architecture, caching, communication
- [Development](development.md) — Local setup, testing, contributing