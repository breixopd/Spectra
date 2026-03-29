# Authentication

[← Wiki Home](home.md) | [Security](security.md) | [Configuration](configuration.md)

---

Spectra's authentication system: JWT tokens, browser session cookies, password management, rate limiting, RBAC, and API keys.

## JWT Authentication

### Token Types

| Token | Lifetime | Purpose |
|-------|----------|---------|
| **Access token** | 24 hours (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`) | API authentication |
| **Refresh token** | 7 days | Obtain new access tokens without re-login |
| **Password reset token** | 1 hour | One-time use for password reset |

All tokens use HS256 signing with `JWT_SECRET_KEY`.

### Token Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/v1/auth/token` | Login | Returns access + refresh tokens and sets browser session cookies |
| `POST /api/v1/auth/refresh` | Refresh | Rotates the refresh token and issues a new access token |
| `POST /api/v1/auth/logout` | Logout | Invalidates the current session and clears auth cookies |

The canonical auth routes live under `/api/v1/auth/*`. Backward-compatible `/api/auth/*` routes are still mounted for older clients.

### Browser Session Flow

Browser auth is same-origin and cookie-based:

1. `POST /api/v1/auth/token` sets `access_token` and `refresh_token` as HttpOnly cookies.
2. Browser API calls send cookies automatically; normal same-origin UI traffic does not need a bearer header.
3. On `401`, the frontend attempts a silent refresh via `POST /api/v1/auth/refresh` and retries the original request.
4. Cookie-authenticated `POST`/`PUT`/`PATCH`/`DELETE` requests must include `X-CSRF-Token` matching the `csrf_token` cookie.
5. Bearer-token and `X-API-Key` clients remain supported and do not require CSRF.
6. WebSockets accept `?token=<access_token>` and fall back to the `access_token` cookie when the query parameter is absent.

### Token Blacklist

Tokens are invalidated via a persistent blacklist stored in the `cache_entries` database table. Both individual token invalidation and per-user "invalidate all" are supported. The blacklist is loaded into memory on startup and synced to the database asynchronously.

### Secret Key Management

- **`JWT_SECRET_KEY`**: Required for production. If empty, a random key is generated on startup — all sessions invalidate on restart.
- **`SECRET_KEY`**: General application secret for encryption. Auto-generated if using the default value.

> **Production**: Always set `JWT_SECRET_KEY` to a strong random value. Generate one with `openssl rand -hex 32`.

---

## Password Reset Flow

1. User submits email to `POST /api/v1/auth/forgot-password`
2. Server generates a time-limited password reset token (1 hour expiry)
3. Token is sent to the user's email (when email service is configured)
4. User submits new password + token to `POST /api/v1/auth/reset-password`
5. Token is verified, password is updated

The `forgot-password` endpoint always returns `204 No Content` regardless of whether the email exists, preventing user enumeration.

### Endpoints

| Endpoint | Rate Limit | Description |
|----------|------------|-------------|
| `POST /api/v1/auth/forgot-password` | 3/minute | Request password reset |
| `POST /api/v1/auth/reset-password` | 5/minute | Submit new password with token |
| `GET /forgot-password` | — | Web UI form |
| `GET /reset-password` | — | Web UI form |

---

## Account Lockout

Persistent IP-based lockout protects against brute-force login attempts:

| Threshold | Lockout Duration |
|-----------|-----------------|
| 5 failed attempts | 5 minutes |
| 10 failed attempts | 30 minutes |

Lockout state is persisted to `data/auth/.lockout_state.json` and survives application restarts.

---

## Rate Limiting

Rate limiting uses `slowapi`. PostgreSQL remains the persistent state store, PostgreSQL-backed app cache, job queue, and `LISTEN`/`NOTIFY` backbone. Redis is the shared distributed rate-limiting backend. `RATE_LIMIT_STORAGE=memory://` is acceptable for tests or intentionally ephemeral local runs, but it is not the normal deployment recommendation. Limits are applied per-user (authenticated) or per-IP (unauthenticated).

### Rate Limit Presets

| Endpoint Category | Limit | Constant |
|-------------------|-------|----------|
| Login | 5/minute | `RateLimits.LOGIN` |
| Setup | 3/minute | `RateLimits.SETUP` |
| Token refresh | 5/minute | `RateLimits.TOKEN_REFRESH` |
| Forgot password | 3/minute | `RateLimits.FORGOT_PASSWORD` |
| Reset password | 5/minute | `RateLimits.RESET_PASSWORD` |
| Mission start | 5/minute | `RateLimits.MISSION_START` |
| Mission steer | 30/minute | `RateLimits.MISSION_STEER` |
| Tool list | 60/minute | `RateLimits.TOOL_LIST` |
| Tool execute | 20/minute | `RateLimits.TOOL_EXECUTE` |
| Tool upload | 5/minute | `RateLimits.TOOL_UPLOAD` |
| API default | 100/minute | `RateLimits.API_DEFAULT` |
| API heavy | 30/minute | `RateLimits.API_HEAVY` |
| WebSocket connect | 10/minute | `RateLimits.WS_CONNECT` |

Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are included in responses.

> **Deployment note**: Keep Redis as the shared distributed rate-limiting backend for normal deployments. `RATE_LIMIT_STORAGE=memory://` is mainly for tests or intentionally ephemeral local runs. PostgreSQL does not share rate-limit state across replicas. Use Caddy rate limiting only if you intentionally want all limits enforced at the edge.

---

## RBAC Roles

Three roles with hierarchical permissions:

| Role | Capabilities |
|------|-------------|
| **admin** | Full access — user management, server provisioning, system settings, audit logs, all missions |
| **operator** | Run missions, manage tools, view findings, create targets |
| **viewer** | Read-only access to missions, findings, reports |

### Endpoint Protection

- Browser UI and same-origin API calls authenticate with the `access_token` cookie
- Non-browser clients can use `Authorization: Bearer <token>`
- Public endpoints: `/api/health`, `/api/v1/auth/setup`, `/api/v1/auth/setup/status`, `/api/public/*`
- Admin-only endpoints: `/api/admin/*`, `/system/services/*`, server provisioning
- Role checks enforced at the router level via `get_current_active_user` dependency

---

## API Key Authentication

API keys are used for server-to-server communication in the gateway system:

- **Gateway clients** include an `X-API-Key` header when calling remote Spectra services
- **Server nodes** store API keys for authentication between pool members
- Keys are validated on the receiving end before processing requests

API keys are distinct from JWT tokens and are intended for programmatic/service access only.

Because API-key clients authenticate by header instead of browser cookie, they are not subject to CSRF validation.

---

## Initial Setup

The first admin account is created via `POST /api/v1/auth/setup` (or the `/setup` web UI):

1. Only callable when no users exist in the database
2. Creates an admin user with the provided credentials
3. After setup, the endpoint is permanently disabled
4. Subsequent users are created by admins via `/api/admin/users`

---

## FULLY_AUTOMATED Mode

When `FULLY_AUTOMATED=true`, all human approval gates are bypassed — missions run without operator confirmation.

> **Warning**: Never enable `FULLY_AUTOMATED=true` in production environments connected to real targets. This mode is intended for development, testing, and controlled lab environments only. In production, set `FULLY_AUTOMATED=false` to maintain human oversight of critical security decisions.
