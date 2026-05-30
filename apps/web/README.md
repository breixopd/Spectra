# Spectra Web (React SPA)

React single-page application for the Spectra autonomous penetration-testing platform. It is the product UI for the authenticated app and is always served same-origin from FastAPI. Public marketing/landing pages remain server-rendered (Jinja) for SEO.

## Stack and rationale

| Layer | Choice | Why |
| --- | --- | --- |
| Build | **Vite 6** + **React 18** + **TypeScript (strict)** | Fast dev/build, first-class TS, matches 2026 research direction |
| Styling | **Tailwind CSS** + CSS-variable tokens (`src/styles/tokens.css`) | Dense ops-console layout, dark-native theming, owned design tokens |
| Components | **shadcn/ui pattern** (Radix + CVA under `src/components/ui`) | Accessible primitives, fully owned source (no opaque component library) |
| Server state | **TanStack Query v5** | Cache, refetch, invalidation for REST endpoints |
| Routing | **TanStack Router v1** | Type-safe routes/search params, pairs cleanly with TanStack Query; better TS inference than React Router for a large typed API surface |
| Icons | **lucide-react** | Consistent, tree-shakeable icons (used sparingly) |

## Authentication and CSRF

Spectra uses **cookie-based sessions**:

- `access_token` — HttpOnly JWT cookie set by `POST /api/v1/auth/token`
- `refresh_token` — HttpOnly cookie for token refresh
- `csrf_token` — **non-HttpOnly** cookie for double-submit CSRF protection

### CSRF flow (double-submit cookie)

Implemented in `services/api/src/spectra_api/bootstrap/middleware.py` (`SecurityHeadersMiddleware`):

1. On **non-API GET responses**, if `csrf_token` is absent, the server sets a `csrf_token` cookie (`SameSite=Lax`, `Secure` outside `DEBUG`).
2. For **mutating requests** (`POST`, `PUT`, `PATCH`, `DELETE`) that use cookie auth (has `access_token`, no `Authorization` bearer header, no `X-Api-Key`), the server requires:
   - Cookie: `csrf_token`
   - Header: `X-CSRF-Token` with the **same value**
3. Bearer and API-key authenticated requests **skip** CSRF (no browser cookie session).
4. Login (`POST /api/v1/auth/token`) does not require CSRF because no `access_token` cookie exists yet.

The SPA client (`src/lib/api.ts`) mirrors the legacy `services/api/static/js/api.js` behaviour: it reads `csrf_token` from `document.cookie` and sends `X-CSRF-Token` on mutating requests with `credentials: 'include'`.

**Dev note:** Vite serves HTML from port 5173, so CSRF cookies are bootstrapped via a proxied `GET /login` (legacy route) when the cookie is missing.

## REST API surface (prefix `/api/v1`)

All routes below require authentication unless noted. Wired in the foundation client for auth; other routes are documented for upcoming screens.

### Auth (`/api/v1/auth`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/token` | Login (OAuth2 form: `username`, `password`) |
| POST | `/refresh` | Refresh access token |
| POST | `/logout` | Logout, clear cookies |
| GET | `/me` | Current user profile (**session check**) |
| PUT | `/me` | Update profile |
| DELETE | `/account` | Delete account |
| GET | `/api-keys` | List API keys |
| POST | `/api-keys` | Create API key |
| DELETE | `/api-keys/{key_id}` | Revoke API key |
| GET | `/activity` | User audit activity |

### Health

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | Canonical health/readiness |
| GET | `/api/v1/health/ready` | Readiness probe |
| GET | `/api/v1/version` | App version (auth required) |
| GET | `/api/health` | Legacy health alias |

### Missions (`/api/v1/missions`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `` | List missions (paginated) |
| POST | `` | Start mission |
| GET | `/{mission_id}` | Mission detail |
| GET | `/{mission_id}/findings` | Mission findings |
| DELETE | `/{mission_id}` | Delete mission |
| POST | `/{mission_id}/stop` | Stop mission |
| POST | `/{mission_id}/pause` | Pause mission |
| POST | `/{mission_id}/resume` | Resume mission |
| GET | `/summary` | Mission summary stats |
| GET | `/{mission_id}/progress` | Progress |
| GET | `/{mission_id}/task-tree` | Attack/task tree |
| POST | `/{mission_id}/steer` | Steer agent |
| POST | `/{mission_id}/approve` | Approve action |
| GET/POST | `/{mission_id}/feedback` | Operator feedback |
| GET | `/{mission_id}/artifacts` | List artifacts |
| GET | `/{mission_id}/report/pdf` | PDF report export |

### Findings (`/api/v1/findings`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `` | List findings (paginated, filters) |
| POST | `` | Create finding |
| GET | `/{finding_id}` | Finding detail |
| PATCH | `/{finding_id}` | Update finding |
| DELETE | `/{finding_id}` | Delete finding |

### Tools (`/api/v1/tools`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/available` | Tool registry |
| GET | `/{tool_id}` | Tool detail |
| POST | `/upload` | Upload plugin |
| POST | `/{tool_id}/install` | Install tool |
| POST | `/{tool_id}/test` | Test execution |
| GET | `/{tool_id}/stats` | Tool stats |

### System & settings

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/system/status` | System status |
| GET | `/api/v1/system/services/health` | Service health |
| GET | `/api/v1/user/settings` | User preferences / BYOK |
| PUT | `/api/v1/user/settings` | Update preferences |

## WebSockets

| Path | Purpose | Client helper |
| --- | --- | --- |
| `/ws` | Mission/user realtime events (cookie or `?token=` JWT) | `createMissionEventsSocket()` in `src/lib/ws.ts` |
| `/api/v1/shell/{session_id}` | Interactive shell session | `createShellSocket(sessionId)` |

Both accept the `access_token` cookie or a `token` query parameter.

## FastAPI serving model

The SPA is the product UI and is always served (no feature flag). Architecture is a
**hybrid** validated against 2026 best practice: a client-rendered Vite SPA for the
auth-gated, highly interactive app (SEO is irrelevant behind login), and **server-rendered
Jinja for the public marketing/SEO surface** (landing `/`, `/pricing`, `/legal/*`,
`/register`, password flows, `/sitemap.xml`). Client rendering is weak for SEO, so those
public pages deliberately stay SSR.

1. `services/api/src/spectra_api/ui/spa.py` mounts **`/assets`** → Vite build assets (`dist/assets`).
2. A **catch-all GET** returns `dist/index.html` for all app routes except the API and the
   server-rendered surface (`/api`, `/static`, `/ws`, `/admin`, `/mcp`, `/internal`, and the
   marketing/SEO prefixes). The SPA owns `/login` and the authenticated app (home is `/dashboard`).
3. The public landing (`/`) is a server-rendered route registered before the SPA fallback, so
   route ordering keeps it SSR.
4. If `dist/` is absent (e.g. a dev API without a built SPA), the mount is skipped with a warning
   rather than failing — the only guard, and not a feature flag.

### Dist paths

| Environment | Path |
| --- | --- |
| Monorepo dev/build | `apps/web/dist/` |
| API Docker image | `/app/spa/` (copied from builder `apps/web/dist`) |

The API Docker image builds the SPA automatically; no env toggle is required.

## Development

```bash
cd apps/web
npm install
npm run dev
```

Vite dev server (default **5173**) proxies:

- `/api` → `http://localhost:5000`
- `/ws` → `ws://localhost:5000`

Run the API separately on port 5000. The CSRF cookie (`csrf_token`) is set by the API on any
non-API GET (including the SPA shell), so loading the app bootstraps it automatically.

## Production build

```bash
cd apps/web
npm ci
npm run build
```

Output: `apps/web/dist/index.html` and `apps/web/dist/assets/*`.

The API Docker image builds this automatically in `deploy/docker/Dockerfile.api`.

## Routes (foundation placeholders)

| Path | Screen |
| --- | --- |
| `/login` | Login |
| `/dashboard` | Mission Control (authenticated home) |
| `/missions` | Missions list |
| `/missions/:id` | Mission detail |
| `/findings` | Findings list |
| `/findings/:id` | Finding detail |
| `/attack-graph` | Attack graph |
| `/evidence` | Evidence |
| `/reports` | Reports |
| `/tools` | Tools |
| `/settings` | Settings |

## Legacy Jinja retirement

The legacy authenticated Jinja dashboard router (`spectra_api.ui.pages`) is **no longer mounted** —
the SPA owns the entire authenticated app. The module file remains only because a few unit tests
still exercise its handlers directly; it and those tests are slated for deletion once the SPA's API
documentation surface confirms parity. Server-rendered public/marketing/legal/admin pages
(`spectra_api.ui.public`) are kept on purpose: they are SEO-sensitive and correctly server-rendered.
