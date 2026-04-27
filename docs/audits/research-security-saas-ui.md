# Security Platform UI/UX and Feature Gating Patterns Research Report

**Date**: 2026-04-27
**Context**: Spectra Security Platform Improvement Initiative

---

## 1. Security Platform UI Examples

### Major Platforms Analyzed

#### Cobalt.io (Crowdsourced Security Platform)
- Dashboard Style: Modern, clean interface with dark theme support
- Navigation: Left sidebar with clear iconography for Assets, Pentests, Findings, Integrations
- Key Patterns:
  - Single repository for all testing results
  - Organization-level dashboards with engagement filtering
  - Asset-centric view linking to pentests and findings
  - Role-based access control for organization owners managing access

#### HackerOne (Bug Bounty & Pentest Platform)
- Dashboard Style: Professional, data-dense interface
- Key Patterns:
  - Organizational-level dashboards
  - Engagement-based data filtering
  - Program management with flexible program options
  - Vulnerability triage and reward management

#### Cybersecurity Dashboard Design Patterns
From Design Monks analysis:

| Pattern | Description |
|---------|-------------|
| Dark Theme + Accent Colors | Industry standard for security tools |
| Card-Based Layout | Vulnerability metrics in organized cards |
| Risk Heat Maps | Visual representation of vulnerability data |
| Real-Time Updates | Live monitoring indicators |
| Sidebar Filters | Quick filtering by severity, status |

---

## 2. Feature Gating & Upselling UI Patterns

### A. Disabled Button with Tooltip Pattern
Show tooltips on disabled elements explaining why they are disabled.

### B. Upgrade Prompt Modal Pattern
Trigger upgrade prompts contextually when users hit limits.

### C. Usage-Based Banner Pattern
Show subtle banners when approaching plan limits.

### D. Feature Comparison Table Pattern
Clear plan differentiation with feature checkmarks/crosses.

### E. Contextual Upgrade Triggers
Notion/Linear pattern - show upgrade option precisely when user tries to use a premium feature.

### Upgrade UI Component Examples

| Company | Pattern Used |
|---------|-------------|
| Linear | Inline upgrade prompts |
| Notion | Usage-based triggers |
| Dropbox | Persistent slideout |
| Asana | Feature showcase |

---

## 3. RBAC UI Patterns

### Open Source RBAC Dashboard Examples
- satnaing/shadcn-admin: Built with Shadcn UI + Tailwind CSS + Vite + React
- rajeevkumar-nita/rbac-dashboard1: Full user/role/permission management
- ankki457/Role-Based-Access-Control-RBAC-UI: Secure role assignment interface

### RBAC Navigation Patterns

| Role | Navigation Items Visible | Actions Available |
|------|------------------------|-------------------|
| Admin | All menu items | Full CRUD on all resources |
| Manager | Dashboard, Scans, Reports | View all, Edit own team's scans |
| User | Dashboard, My Scans | View/Run own scans |

---

## 4. Dynamic UI Frameworks (HTMX, Alpine.js, Stimulus)

### Framework Comparison

| Framework | Size | Best For | Learning Curve |
|-----------|------|----------|----------------|
| HTMX | ~14kB | AJAX, DOM swapping | Low |
| Alpine.js | ~15kB | Client-side interactivity | Low |
| Stimulus | ~4kB | Progressive enhancement | Medium |

### HTMX in Python Web Apps
HTMX enables AJAX-like functionality with pure HTML attributes. No JavaScript required.

### Alpine.js in Python Web Apps
Lightweight reactivity for client-side state.

### When to Use Each

| Use Case | Recommended Tool |
|----------|------------------|
| Form submission without page reload | HTMX |
| Toggling UI state (modals, dropdowns) | Alpine.js |
| Inline editing | HTMX + Alpine.js |
| Real-time updates | HTMX + WebSockets |
| Simple interactivity | Alpine.js only |

---

## 5. Modern CSS Frameworks for Dashboards

### Framework Comparison

| Framework | Type | Dashboard Suitability | Learning Curve |
|-----------|------|----------------------|----------------|
| Tailwind CSS | Utility-first | Excellent | Medium |
| Bootstrap | Component-first | Good | Low |
| Bulma | Component-first | Moderate | Low |
| Shadcn/UI | Component library | Excellent | Medium |

### Tailwind CSS - Current Leader for Dashboards
Advantages:
1. Performance: 5-7x smaller bundles than Bootstrap
2. Flexibility: No pre-built components to fight against
3. Dark Mode: Built-in support
4. Modern ecosystem: Shadcn/UI, Headless UI
5. Mobile-first: True responsive design

---

## Recommendations for Spectra

1. **UI/UX Improvements**: Adopt Dark Theme with Accent Colors. Primary blue for links/actions, critical red/orange for vulnerabilities, warning yellow for medium severity, success green for resolved.

2. **Feature Gating Implementation**: Implement backend middleware for feature checks. Frontend feature gate component with disabled fallback.

3. **Recommended Stack**:
   - Backend: FastAPI + HTMX
   - Frontend JS: Alpine.js
   - CSS: Tailwind CSS + custom
   - Components: Custom Jinja2 macros + Alpine.js
   - RBAC: FastAPI dependencies with permission enums

4. **RBAC Implementation**:
   - Roles: admin, manager, user
   - Navigation visibility per role
   - Permission checks on every endpoint
