# Authentication

[← Wiki Home](home.md) | [Security](security.md) | [Configuration](configuration.md)

---

Spectra's authentication system: JWT tokens, password management, rate limiting, RBAC, and API keys.

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
| `POST /api/auth/token` | Login | Returns access + refresh tokens |
| `POST /api/auth/refresh` | Refresh | Exchange refresh token for new access token |
| `POST /api/auth/logout` | Logout | Invalidates the current token |

### Token Blacklist

Tokens are invalidated via a persistent blacklist stored in the `cache_entries` database table. Both individual token invalidation and per-user "invalidate all" are supported. The blacklist is loaded into memory on startup and synced to the database asynchronously.

### Secret Key Management

- **`JWT_SECRET_KEY`**: Required for production. If empty, a random key is generated on startup — all sessions invalidate on restart.
- **`SECRET_KEY`**: General application secret for encryption. Auto-generated if using the default value.

> **Production**: Always set `JWT_SECRET_KEY` to a strong random value. Generate one with `openssl rand -hex 32`.

---

## Password Reset Flow

1. User submits email to `POST /api/auth/forgot-password`
2. Server generates a time-limited password reset token (1 hour expiry)
3. Token is sent to the user's email (when email service is configured)
4. User submits new password + token to `POST /api/auth/reset-password`
5. Token is verified, password is updated

The `forgot-password` endpoint always returns `204 No Content` regardless of whether the email exists, preventing user enumeration.

### Endpoints

| Endpoint | Rate Limit | Description |
|----------|------------|-------------|
| `POST /api/auth/forgot-password` | 3/minute | Request password reset |
| `POST /api/auth/reset-password` | 5/minute | Submit new password with token |
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

Rate limiting uses `slowapi` with in-memory storage. Limits are applied per-user (authenticated) or per-IP (unauthenticated).

### Rate Limit Presets

| Endpoint Category | Limit | Constant |
|-------------------|-------|----------|
| Login | 5/minute | `RateLimits.LOGIN` |
| Setup | 3/minute | `RateLimits.SETUP` |
| Token refresh | 10/minute | `RateLimits.TOKEN_REFRESH` |
| Forgot password | 3/minute | (inline) |
| Reset password | 5/minute | (inline) |
| Mission start | 10/minute | `RateLimits.MISSION_START` |
| Mission steer | 30/minute | `RateLimits.MISSION_STEER` |
| Tool list | 60/minute | `RateLimits.TOOL_LIST` |
| Tool execute | 20/minute | `RateLimits.TOOL_EXECUTE` |
| Tool upload | 5/minute | `RateLimits.TOOL_UPLOAD` |
| API default | 100/minute | `RateLimits.API_DEFAULT` |
| API heavy | 30/minute | `RateLimits.API_HEAVY` |
| WebSocket connect | 10/minute | `RateLimits.WS_CONNECT` |

Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are included in responses.

> **Scaling note**: The default in-memory rate limiter is per-process. In multi-instance deployments, rate limit state is shared across instances via the PostgreSQL database — no external store needed.

---

## RBAC Roles

Three roles with hierarchical permissions:

| Role | Capabilities |
|------|-------------|
| **admin** | Full access — user management, server provisioning, system settings, audit logs, all missions |
| **operator** | Run missions, manage tools, view findings, create targets |
| **viewer** | Read-only access to missions, findings, reports |

### Endpoint Protection

- Most endpoints require `Authorization: Bearer <token>`
- Public endpoints: `/api/health`, `/api/auth/setup`, `/api/auth/setup/status`, `/api/public/*`
- Admin-only endpoints: `/api/admin/*`, `/system/services/*`, server provisioning
- Role checks enforced at the router level via `get_current_active_user` dependency

---

## API Key Authentication

API keys are used for server-to-server communication in the gateway system:

- **Gateway clients** include an `X-API-Key` header when calling remote Spectra services
- **Server nodes** store API keys for authentication between pool members
- Keys are validated on the receiving end before processing requests

API keys are distinct from JWT tokens and are intended for programmatic/service access only.

---

## Initial Setup

The first admin account is created via `POST /api/auth/setup` (or the `/setup` web UI):

1. Only callable when no users exist in the database
2. Creates an admin user with the provided credentials
3. After setup, the endpoint is permanently disabled
4. Subsequent users are created by admins via `/api/admin/users`

---

## FULLY_AUTOMATED Mode

When `FULLY_AUTOMATED=true`, all human approval gates are bypassed — missions run without operator confirmation.

> **Warning**: Never enable `FULLY_AUTOMATED=true` in production environments connected to real targets. This mode is intended for development, testing, and controlled lab environments only. In production, set `FULLY_AUTOMATED=false` to maintain human oversight of critical security decisions.
