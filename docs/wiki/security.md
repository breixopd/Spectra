# Security

[← Wiki Home](home.md) | [Configuration](configuration.md) | [Architecture](architecture.md)

---

Spectra's security model — authentication, authorization, encryption, network isolation, and audit logging.

## Authentication

### JWT Tokens

- Algorithm: HS256 (configurable via `JWT_ALGORITHM`)
- Token lifetime: 24 hours default (`ACCESS_TOKEN_EXPIRE_MINUTES=1440`)
- Tokens issued via `POST /api/v1/auth/token` with username/password
- Refresh via `POST /api/v1/auth/refresh`
- Invalidation via `POST /api/v1/auth/logout` (revokes access and refresh tokens via `invalidated_before`)
- MFA cancel via `POST /api/v1/auth/mfa/cancel` (invalidates pending MFA tokens)
- Rate-limited with IP-based lockout after repeated failures

### Browser Sessions

- Browser login sets `access_token` and `refresh_token` as HttpOnly cookies.
- The `refresh_token` cookie is scoped to `/api/v1/auth/refresh`; the `access_token` cookie is scoped to `/`.
- Same-origin browser API calls use cookies, not bearer headers.
- The frontend attempts a silent refresh through `POST /api/v1/auth/refresh` before redirecting the browser back to `/login`.
- Cookie-authenticated mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`) must send `X-CSRF-Token` matching the `csrf_token` cookie.

### Bearer Tokens and API Keys

- Bearer JWTs remain supported for CLI and programmatic clients.
- `Authorization: Bearer <token>` takes precedence over cookie auth when both are present.
- `X-API-Key` remains supported for gateway and service-to-service calls.
- CSRF validation is skipped for bearer and API-key requests because they do not rely on the browser cookie session.

### WebSocket Authentication

- `/ws` and shell WebSockets accept `?token=<access JWT>`.
- If no query token is supplied, the server falls back to the `access_token` cookie.
- Missing or invalid credentials cause the socket to close with an authentication failure.

### Initial Setup

- `POST /api/v1/auth/setup` creates the first admin account
- Only callable once (before any users exist)
- After setup, redirects to normal login flow

### Secret Key Management

- `JWT_SECRET_KEY`: Required for production. Auto-generated if empty (sessions invalidate on restart). Used **only** for signing tokens.
- `ENCRYPTION_KEY`: Separate encryption key for MFA TOTP secrets and credential storage. Defaults to `JWT_SECRET_KEY` if not set — set explicitly to isolate key domains.
- `SECRET_KEY`: General application secret. Auto-generated if using default value.

---

## Authorization (RBAC)

Role-based access control with three tiers:

| Role | Capabilities |
| ------ | ------------- |
| **admin** | Full access — user management, server provisioning, system settings, all missions
| **staff** | View missions, findings, targets, reports; manage users and view audit logs
| **user** | Run missions, manage tools, view findings, create targets |

### Endpoint Protection

- Browser UI/API requests can authenticate via the `access_token` cookie
- Programmatic clients can authenticate with `Authorization: Bearer <token>` or `X-API-Key`
- Public endpoints: `/api/health`, `/api/v1/auth/setup`, `/api/v1/auth/setup/status`
- Admin-only endpoints: `/api/admin/*`, `/api/v1/system/*`, server provisioning
- Superuser checks enforced at the router level

### MCP (`/api/mcp`)

- **Authentication:** Shared **`MCP_API_KEY`** via `Authorization: Bearer …` or `X-API-Key`. Constant-time comparison prevents trivial timing leaks on the key string.
- **User scoping:** For mission/target/list tools, the server **replaces** any client-supplied `user_id` with **`MCP_USER_ID`** from settings (`spectra_api/api/mcp.py` — `_execute_mcp_tool`). Without `MCP_USER_ID`, those tools error at runtime. This blocks callers from enumerating or mutating other tenants by passing arbitrary UUIDs while holding only the shared MCP key.
- **Knowledge search:** `search_knowledge_base` uses the shared AI/RAG gateway and is **not** user-row-scoped in the same way; treat MCP network access as privileged and keep **`MCP_API_KEY`** high-entropy and rotated like other service secrets.

---

## Encryption

### Credential Store

- Per-mission, in-memory credential storage during mission lifecycle
- Credentials extracted from tool output via regex patterns
- Never persisted to disk unencrypted
- Scoped to mission — destroyed when mission ends

### API Key Management

- SSH keys for server provisioning stored encrypted in DB (via `spectra_platform/core/encryption.py`)
- LLM API keys stored as `SecretStr` (Pydantic) — never serialized to logs or JSON
- Plugin files validated via schema and command blocklist

### Transport Security

- **Production**: Caddy provides TLS termination with auto-provisioned Let's Encrypt certificates
- **Browser sessions**: `access_token` and `refresh_token` cookies are always `HttpOnly`, `SameSite=Strict`, and `Secure`; the separate non-HttpOnly `csrf_token` cookie uses `Secure` outside DEBUG and relaxes only for local HTTP development
- **HSTS**: Strict-Transport-Security header with 63072000s max-age and preload
- **Database**: `sslmode=require` recommended for production DATABASE_URL
- **S3/Garage**: TLS for all object storage traffic in production

---

## Network Security

### Sandbox Isolation

Each mission sandbox is isolated:

- Separate Docker container with `CAP_DROP ALL` + only `NET_ADMIN`/`NET_RAW`
- PID limits (`--pids-limit 256`)
- tmpfs for temporary storage
- No Docker socket access
- Per-sandbox Docker networks prevent cross-mission access (`SANDBOX_NETWORK_ISOLATION=true`)

See [Sandboxes](sandboxes.md) for full isolation details.

### VPN Support

- Per-mission VPN configuration injection
- Each sandbox has its own network namespace
- WireGuard and OpenVPN supported
- VPN in one sandbox doesn't affect others

### Docker Network Architecture

- `spectra-network`: Main network for app ↔ DB ↔ tools communication
- Per-sandbox networks: `spectra-sandbox-{mission_id}` for strict isolation
- Sandboxes connect to DB network only — no direct inter-sandbox communication

---

---

## Safety Mechanisms

### SafetySupervisor

- Regex blocklist for dangerous commands (`rm -rf`, fork bombs, etc.)
- LLM analysis of every command before execution
- Blocks large wordlists (anti-brute-force policy)
- Only allows default credential testing

### Consensus Voting

Critical decisions pass through quality gates with multi-model validation:

- **PLAN** gate: 2/3 voters must agree (70% confidence)
- **EXECUTION** gate: 3/3 voters must agree for high-risk actions (80% confidence)

### Scope Enforcement

- Agents only target authorized hosts defined in the mission scope
- Out-of-scope targets are blocked

---

## Audit Logging

- All API requests logged with user identity, action, and timestamp
- Sandbox lifecycle events: create, destroy, crash, VPN connect, tool execution
- Server provisioning: all SSH commands logged
- Mission events: start, stop, pause, resume, steer, findings
- Infrastructure changes: server pool modifications
- Available via `GET /api/v1/system/audit-log`


## Container Hardening

- App service runs with read-only root filesystem (tmpfs `/tmp`)
- App Docker socket mount is read-only
- `no-new-privileges` applied to app and worker containers
- Worker retains `NET_ADMIN`/`NET_RAW` for VPN/sandbox networking only

---

## Security Headers

Production Caddy configuration includes:

| Header | Value |
| -------- | ------- |
| Content-Security-Policy | Restrictive CSP |
| Strict-Transport-Security | `max-age=63072000; includeSubDomains; preload` |
| X-Frame-Options | `DENY` |
| X-Content-Type-Options | `nosniff` |
| X-XSS-Protection | `1; mode=block` |
| Referrer-Policy | `strict-origin-when-cross-origin` |

---

## Security Configuration

Key configuration for security hardening:

| Setting | Default | Recommendation |
| --------- | --------- | ---------------- |
| `JWT_SECRET_KEY` | Auto-generated | Set a strong random value in production |
| `ENCRYPTION_KEY` | `''` (falls back to JWT key) | Set explicitly to separate signing and encryption key domains |
| `REQUIRE_APPROVAL` | `false` | Set `true` in **environment only** for operator-wide human-in-the-loop on high-risk actions (not an Admin UI toggle) |
| `SANDBOX_NETWORK_ISOLATION` | `true` | Keep enabled |
| `DEBUG` | `false` | Never enable in production |

See [Configuration](configuration.md) for all settings.

---

## Admin ML training exports

- `GET /api/v1/admin/training/export` requires admin permission (`MANAGE_SETTINGS`) and returns **approved training samples only** for fine-tuning workflows (unapproved rows are never included in the HTTP export).

---

## GDPR Compliance

Spectra includes built-in features for EU General Data Protection Regulation compliance.

### Data Export (Article 20 — Portability)

Users can export all their personal data as a downloadable JSON file via `GET /api/v1/auth/export-data`. The export includes: user profile, missions, targets, findings, and audit log entries.

Available in the UI at Settings → Data & Privacy → "Download My Data".

### Right to Erasure (Article 17 — Deletion)

Users can permanently delete their account and all associated data via `DELETE /api/v1/auth/account`. Requires password confirmation. Audit logs are preserved with `user_id` set to NULL to maintain audit integrity. The last superuser account cannot be deleted.

Available in the UI at Settings → Data & Privacy → "Delete Account".

### Restriction of Processing (Article 18)

Users can toggle a `processing_restricted` flag on their account via `POST /api/v1/auth/restrict-processing`. All restriction changes are recorded in the audit log.

### Cookie Consent

A cookie consent banner is displayed on all pages (`partials/_cookie_consent.html`). Users can choose:

- **Accept All** — enables all cookies
- **Essential Only** — limits to strictly necessary cookies

Consent is stored in a `cookie_consent` cookie (1-year expiry). A cookie preferences link is available in the footer. The cookie policy page at `/legal/cookie` documents all cookies used.

### Legal Pages

Spectra includes standard legal pages:

- `/legal/privacy` — Privacy policy with automated decision-making section
- `/legal/terms` — Terms of service with data deletion section
- `/legal/cookie` — Cookie policy with full cookie inventory

### UI Controls

The Settings → Data & Privacy tab provides:

- Download My Data button
- Restrict Processing toggle
- Training Data opt-out toggle
- Delete Account button (with password confirmation modal)

All GDPR features are covered by dedicated Playwright tests (`tests/e2e/ui/test_gdpr_features.py`).

See [Operations](operations.md#gdpr-data-management) for operator-facing GDPR commands.
