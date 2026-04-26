# Research Report: Best Practices for Modern Web Platform Development

## Spectra Platform Improvement Initiative

---

## 1. Python Project Structure Best Practices

### Recommended Architecture: Domain-Based Structure

The consensus from FastAPI community conventions ([zhanymkanov/fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices), 17k stars) and official templates ([tiangolo/full-stack-fastapi-template](https://github.com/tiangolo/full-stack-fastapi-template), 42.9k stars) favors **domain-based** organization over file-type-based, especially for medium-to-large apps.

**Key Structure Pattern:**

```
fastapi-project/
├── alembic/                    # Database migrations
├── src/
│   ├── auth/                   # Domain module (self-contained)
│   │   ├── router.py          # All HTTP endpoints
│   │   ├── schemas.py         # Pydantic models (request/response)
│   │   ├── models.py          # DB models (SQLAlchemy)
│   │   ├── service.py         # Business logic
│   │   ├── dependencies.py    # FastAPI dependencies
│   │   ├── config.py          # Domain-specific config
│   │   ├── constants.py       # Error codes, literals
│   │   ├── exceptions.py      # Domain exceptions
│   │   └── utils.py          # Non-business helpers
│   ├── posts/
│   │   └── ...
│   ├── users/
│   │   └── ...
│   ├── config.py              # Global config (Pydantic BaseSettings)
│   ├── database.py            # DB connection
│   ├── exceptions.py          # Global exceptions
│   ├── pagination.py           # Shared utilities
│   └── main.py               # App entry point
├── tests/
│   ├── auth/
│   ├── posts/
│   └── conftest.py
├── templates/                  # Jinja2 templates
├── requirements/
│   ├── base.txt
│   ├── dev.txt
│   └── prod.txt
└── .env
```

**Evidence**: [zhanymkanov/fastapi-best-practices README](https://github.com/zhanymkanov/fastapi-best-practices/blob/52707b6917eaa42dd818823c58d431a90a09796c/README.md)

> "The structure I found more scalable and evolvable is inspired by Netflix's Dispatch, with some minor modifications... Store all domain directories inside `src` folder... Each package has its own router, schemas, models, etc."

### Layered Architecture for Scalability

For larger applications, the **Repository Pattern + Service Layer** is battle-tested:

```
Request → Router → Service → Repository → Database
                      ↓
                Schemas (Pydantic validation)
```

**Key principles from the FastAPI community:**

1. **Dependency Injection via FastAPI's `Depends()`** — chainable, cacheable, reusable
2. **Pydantic for all data validation** — request bodies, response models, settings
3. **Keep routers thin** — delegate business logic to services
4. **Repository pattern** for database access — testable, swappable
5. **Module-level config** — split `BaseSettings` by domain (auth vs. global)

**Code example** — Service layer with async DB query:
```python
# src/posts/service.py
async def get_posts(creator_id: UUID4, limit: int = 10, offset: int = 0) -> list[dict]:
    query = (
        select(posts)
        .join(profiles, posts.c.owner_id == profiles.c.id)
        .where(posts.c.owner_id == creator_id)
        .limit(limit)
        .offset(offset)
        .order_by(desc(coalesce(posts.c.updated_at, posts.c.published_at, posts.c.created_at)))
    )
    return await database.fetch_all(query)
```

**Evidence**: [zhanymkanov/fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices/blob/52707b6917eaa42dd818823c58d431a90a09796c/README.md)

---

## 2. SaaS UI/UX Patterns

### Feature Gating & Upselling UI

**Key Patterns:**
- **Tooltips on disabled elements** — explain why a feature is locked ("Upgrade to Pro to enable this")
- **Upgrade banners** — contextual banners when user hits a plan limit
- **Progressive disclosure** — hide advanced features behind toggles or "Advanced" sections
- **Muted/disabled states with locks** — visual indication + click → upgrade flow

**Evidence**: [WhatIsYourDesign SaaS UI/UX Guide 2026](https://feeds.whatifdesign.co/blog/saassolar-branding-ui-guidelines)

> "Progressive disclosure moves advanced features to secondary screens, making applications easier to learn and less error-prone... Toggle for advanced features: hide power-user options behind 'Advanced' sections."

### Role-Based Navigation & Permissions

**Best Practices:**
- **Sidebar navigation with role-specific sections** — each role sees only relevant nav items
- **Permission checks on backend** — never trust frontend-only gates
- **Role-adaptive UI** — same endpoint returns different field sets per role
- **Visual hierarchy guides attention** — 80/20 principle: focus on 20% features delivering 80% value

**Evidence**: [DesignX SaaS Dashboard Best Practices](https://designx.co/saas-dashboard-design-best-practices/)

> "Your SaaS dashboard is where users spend 80% of their time... When DesignX worked with Solutions360 on their B2B platform audit, we identified 14 dashboard widgets that users never interacted with—removing them improved task completion time by 32%."

### Responsive Design for Data-Heavy Tables

- **Fluid grids** — resize proportionally, not fixed pixels
- **Horizontal scroll + pinned columns** for wide tables
- **Skeleton loaders** — show structure while data loads
- **Pagination with lazy loading** — don't load 10k rows at once
- **Breakpoints**: 320px (phone), 768px (tablet), 1024px+ (desktop)

### Loading States & Optimistic UI

- **Skeleton screens** — reduce perceived wait time
- **Optimistic updates** — show expected result immediately, reconcile with server
- **Progress indicators** for operations >1 second
- **Toast notifications** for success/error confirmation

### Dark Mode Implementation

The official [tiangolo/full-stack-fastapi-template](https://github.com/tiangolo/full-stack-fastapi-template) includes dark mode via Tailwind CSS + shadcn/ui:

```css
/* Tailwind dark mode via class strategy */
<div class="dark:bg-slate-900 dark:text-white">
```

**Evidence**: [Full Stack FastAPI Template](https://github.com/tiangolo/full-stack-fastapi-template) — includes "🦇 Dark mode support" as a core feature.

---

## 3. Playwright E2E Testing Best Practices

### Writing Non-Flaky Tests

**Core principles** from [playwright.dev best practices](https://playwright.dev/docs/best-practices):

**Evidence**: [Playwright Best Practices Official Docs](https://playwright.dev/docs/best-practices)

1. **Use web-first assertions** — `expect().toBeVisible()` auto-waits; manual `isVisible()` checks do NOT:
   ```typescript
   // ✅ Good — auto-waits
   await expect(page.getByText('welcome')).toBeVisible();
   // ❌ Bad — no waiting
   expect(await page.getByText('welcome').isVisible()).toBe(true);
   ```

2. **Use locators, not XPath/CSS selectors** — prefer `getByRole()`, `getByLabel()`, `getByTestId()`:
   ```typescript
   // ✅ Good — semantic, resilient
   await page.getByRole('button', { name: 'Submit' }).click();
   // ❌ Bad — brittle to DOM changes
   page.locator('button.buttonIcon.episode-actions-later');
   ```

3. **Isolate tests with `beforeEach`** — each test gets fresh state:
   ```typescript
   test.beforeEach(async ({ page }) => {
     await page.goto('/login');
     await page.getByLabel('Username').fill('testuser');
     await page.getByLabel('Password').fill('password');
     await page.getByRole('button', { name: 'Sign in' }).click();
   });
   ```

4. **Avoid `waitForTimeout()`** — use Playwright's auto-waiting or explicit conditions:
   ```typescript
   // ❌ Bad
   await page.waitForTimeout(2000);
   // ✅ Good — wait for specific state
   await expect(page.getByTestId('data-table')).toBeVisible();
   ```

5. **Retries + trace viewer** for CI debugging:
   ```yaml
   # playwright.config.ts
   retries: process.env.CI ? 2 : 0,
   trace: 'on-first-retry'
   ```

### Authentication in Tests

**Pattern from freeCodeCamp's Playwright setup** (1.2k tests, production-grade):

```typescript
// Use shared auth state to skip login between tests
test.use({ 
  storageState: 'playwright/.auth/development-user.json' 
});

// Or seed test users via API before tests
test.beforeEach(async ({ page }) => {
  await page.goto('/login');
  await seedTestUser({ email: 'admin@example.com', role: 'admin' });
});
```

**Evidence**: [freeCodeCamp e2e tests](https://github.com/freeCodeCamp/freeCodeCamp/blob/main/e2e/email-sign-up-alert.spec.ts) — shows `test.beforeEach` patterns with `storageState`.

### Multi-Role App Testing

```typescript
// Define role-specific fixtures
test.describe('Admin features', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill('admin@example.com');
    await page.getByLabel('Password').fill(process.env.ADMIN_PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Admin Dashboard')).toBeVisible();
  });
  
  test('can access user management', async ({ page }) => {
    await page.getByRole('link', { name: 'User Management' }).click();
    // ...
  });
});

test.describe('Regular user features', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill('user@example.com');
    await page.getByLabel('Password').fill(process.env.USER_PASSWORD);
    // ...
  });
});
```

### Testing Plan Limitations & Feature Gating

```typescript
test('shows upgrade prompt when hitting limit', async ({ page }) => {
  // Seed user at plan limit
  await seedUserAtPlanLimit('free');
  
  await page.goto('/dashboard');
  await page.getByRole('button', { name: 'Create Report' }).click();
  
  // Verify gated UX
  await expect(page.getByText(/upgrade to pro/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create Report' })).toBeDisabled();
});
```

---

## 4. Frontend Component Architecture (Server-Rendered Apps)

### Comparison for Jinja2/HTML-Based UI

| Approach | Best For | Pros | Cons |
|----------|----------|------|------|
| **Jinja2 Macros** | Shared UI fragments | Built-in, server-only, no JS | Limited interactivity, template logic can get complex |
| **HTMX** | Server-driven CRUD, partial updates | HTML attrs only, server is source of truth | Requires HTML-returning endpoints, lifecycle complexity |
| **Alpine.js** | Client-side UI state (dropdowns, modals, toggles) | Tiny (~15KB), HTML attrs, no build step | Not for complex state, DOM lifecycle issues with HTMX |
| **Web Components** | Truly reusable encapsulated components | Browser-native, framework-agnostic | Higher complexity, shadow DOM styling issues |

**Evidence**: [OpenReplay: HTMX vs Alpine.js](https://blog.openreplay.com/htmx-vs-alpine-when-use/)

> "HTMX handles server-driven interactivity by making requests and swapping HTML fragments, while Alpine.js manages client-side reactivity and local UI state... For most server-rendered applications, HTMX covers the majority of interactions, with Alpine filling gaps where client-only behavior improves the experience."

### Recommended Hybrid Approach for Flask/FastAPI + Jinja2

1. **Jinja2 macros** for static, reusable HTML components (cards, tables, forms)
2. **HTMX** for dynamic content loading, form submissions, CRUD operations
3. **Alpine.js** for client-side interactivity that doesn't need server (modals, dropdowns, toggles)

**Example — Jinja2 macro with Alpine for interactivity:**
```html
{% macro feature_card(title, description, locked=false) %}
<div class="feature-card" x-data="{ expanded: false }">
  <h3>{{ title }}</h3>
  <p>{{ description }}</p>
  {% if locked %}
  <button disabled class="btn-locked">
    🔒 Upgrade to Unlock
  </button>
  {% else %}
  <button @click="expanded = !expanded" class="btn-expand">
    {{ 'Collapse' if expanded else 'Expand' }}
  </button>
  {% endif %}
</div>
{% endmacro %}
```

---

## 5. Performance Optimization

### Python Backend

**Caching** (Redis-based, multi-layer):
- **Application-level cache** — `fastapi-cache` with Redis backend
- **Database query caching** — cache frequent aggregations
- **Response caching** — full response caching for static/rarely-changing endpoints

```python
from fastapi import FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

FastAPICache.init(RedisBackend(app.state.redis), prefix="spectra"))
```

**Evidence**: [ZeonEdge Python Backend Performance Optimization 2026](https://zeonedge.com/es/blog/python-backend-performance-optimization-2026-slow-to-blazing-fast)

**Database optimization:**
- **Connection pooling** — SQLAlchemy `pool_size` and `max_overflow`
- **Indexing** — profile slow queries with `EXPLAIN ANALYZE`
- **Async queries** — use `asyncpg` with `asyncpg` driver for FastAPI

```python
# SQLAlchemy async config
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,  # Verify connections
)
```

**Async workers** — for CPU-bound tasks, offload to Celery:
```python
# Use BackgroundTasks for quick fire-and-forget
from fastapi import BackgroundTasks
bg.add_task(send_email, user.email)

# Use Celery for long-running tasks (>1 second, needs retry)
@app.task
def generate_report(report_id: str):
    # CPU-heavy work
    pass
```

### Frontend Asset Delivery

- **Vite/ESBuild** — for bundling (if using modern frontend)
- **Minification** — ` Ruff` for Python, Terser for JS
- **CDN** — serve static assets from Cloudflare/Fastly with cache headers
- **Gzip/Brotli compression** — enable on nginx/Traefik
- **HTTP cache headers** — `Cache-Control: max-age=31536000` for hashed assets

**Traefik config for asset optimization** (from [tiangolo/full-stack-fastapi-template](https://github.com/tiangolo/full-stack-fastapi-template)):
```yaml
# Traefik handles HTTPS certs automatically
labels:
  - "traefik.http.routers.app.entrypoints=websecure"
  - "traefik.http.routers.app.tls.certResolver=le"
```

---

## 6. Security Hardening

### OWASP Top 10 Alignment (2026 Update)

The 2026 OWASP Top 10 for SaaS platforms:

| Risk | Mitigation |
|------|------------|
| **Broken Access Control** | Role-based permission checks on every endpoint; never trust frontend |
| **Security Misconfiguration** | CIS Benchmarks for containers; automated config scanning |
| **Software Supply Chain Failures** | SCA tools (Dependabot, Snyk); SBOM generation |
| **Cryptographic Failures** | Use `cryptography` library; never roll your own crypto |
| **Injection** | Parameterized queries; input validation with Pydantic |
| **Insecure Design** | Threat modeling; security design review |
| **Authentication Failures** | JWT with short expiry + refresh tokens; MFA support |
| **Software/Data Integrity Failures** | Sigstore for container signing; CI/CD pipeline scanning |
| **Security Logging & Alerting Failures** | Structured logging; alerting on auth failures |
| **Mishandling of Exceptional Conditions** | Global exception handlers; no stack traces in production |

**Evidence**: [GigaTester OWASP Top 10 2026 Explained](https://gigatester.com/owasp-top-10-explained/)

> "The OWASP Top 10 is an evolving list that highlights the ten most dangerous security risks facing web applications."

### Dependency Scanning

- **PyUp/Snyk** — Python dependency vulnerability scanning
- **Dependabot** — automatic PRs for outdated dependencies
- **Safety** — `pip install safety` for Python-specific checks

```bash
# CI/CD Security scanning
safety check --json > safety-report.json
pip-audit --format=json > pip-audit-report.json
```

### Container Security

- **Use minimal base images** — `python:3.12-slim` not `python:3.12`
- **Run as non-root user** — `USER app`
- **CIS Benchmarks** — apply Docker CIS Benchmarks
- **Secret scanning** — GitHub Advanced Security scans for secrets in code

**Evidence**: [Checkmarx Container Security Tools 2026](https://checkmarx.com/learn/container-security/10-container-security-tools-to-know-in-2026/)

> "Vulnerability and dependency scanning identifies exploitable flaws in libraries, frameworks, and operating system packages."

### Security Checklist for Spectra

- [ ] JWT authentication with short-lived access tokens + refresh tokens
- [ ] Role-based access control on every API endpoint
- [ ] Input validation on all Pydantic schemas
- [ ] SQL injection prevention (parameterized queries)
- [ ] CORS configuration — explicit allowed origins
- [ ] Rate limiting on auth endpoints
- [ ] Password hashing with `bcrypt`/`argon2`
- [ ] HTTPS only with secure cookie flags
- [ ] Security headers (CSP, HSTS, X-Frame-Options)
- [ ] Dependency scanning in CI/CD
- [ ] Container runs as non-root
- [ ] Secrets via environment variables, not in code
- [ ] Structured logging (no sensitive data in logs)
- [ ] Global exception handler — no stack traces to clients
- [ ] Automated security scanning (SAST/DAST/SCA)

---

## Key Repositories Referenced

| Repository | Stars | Purpose |
|-----------|-------|---------|
| [zhanymkanov/fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices) | 17.1k | FastAPI conventions & project structure |
| [tiangolo/full-stack-fastapi-template](https://github.com/tiangolo/full-stack-fastapi-template) | 42.9k | Production-ready FastAPI + React + Playwright template |
| [microsoft/playwright](https://github.com/microsoft/playwright) | — | Playwright E2E testing framework |

---

## Actionable Recommendations for Spectra

1. **Adopt domain-based structure** — move from flat file layout to `src/auth/`, `src/core/`, etc.
2. **Implement feature gating** — add upgrade prompts with `x-data` (Alpine) for locked features
3. **Add Playwright tests** — start with auth flows and critical user journeys; use `beforeEach` isolation
4. **Consider HTMX + Alpine hybrid** — for server-rendered pages needing interactivity
5. **Add Redis caching layer** — cache frequent DB queries and expensive computations
6. **Harden security posture** — implement dependency scanning, container hardening, global error handling
7. **Add dark mode** — if using Tailwind CSS, toggle via `.dark` class strategy
