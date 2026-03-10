# Security

[← Wiki Home](home.md) | [Configuration](configuration.md) | [Architecture](architecture.md)

---

Spectra's security model — authentication, authorization, encryption, network isolation, and audit logging.

## Authentication

### JWT Tokens

- Algorithm: HS256 (configurable via `JWT_ALGORITHM`)
- Token lifetime: 24 hours default (`ACCESS_TOKEN_EXPIRE_MINUTES=1440`)
- Tokens issued via `POST /api/auth/token` with username/password
- Refresh via `POST /api/auth/refresh`
- Invalidation via `POST /api/auth/logout`
- Rate-limited with IP-based lockout after repeated failures

### Initial Setup

- `POST /api/auth/setup` creates the first admin account
- Only callable once (before any users exist)
- After setup, redirects to normal login flow

### Secret Key Management

- `JWT_SECRET_KEY`: Required for production. Auto-generated if empty (sessions invalidate on restart).
- `SECRET_KEY`: General application secret. Auto-generated if using default value.

---

## Authorization (RBAC)

Role-based access control with three tiers:

| Role | Capabilities |
| ------ | ------------- |
| **admin** | Full access — user management, server provisioning, system settings, all missions |
| **operator** | Run missions, manage tools, view findings, create targets |
| **viewer** | Read-only access to missions, findings, reports |

### Endpoint Protection

- Most endpoints require authentication (`Authorization: Bearer <token>`)
- Public endpoints: `/api/health`, `/api/auth/setup`, `/api/auth/setup/status`
- Admin-only endpoints: `/api/admin/*`, `/system/services/*`, server provisioning
- Superuser checks enforced at the router level

---

## Encryption

### Credential Store

- Per-mission, in-memory credential storage during mission lifecycle
- Credentials extracted from tool output via regex patterns
- Never persisted to disk unencrypted
- Scoped to mission — destroyed when mission ends

### API Key Management

- SSH keys for server provisioning stored encrypted in DB (via `app/core/encryption.py`)
- LLM API keys stored as `SecretStr` (Pydantic) — never serialized to logs or JSON
- Plugin signing keys stored in `keys/` directory (Ed25519)

### Transport Security

- **Production**: Caddy provides TLS termination with auto-provisioned Let's Encrypt certificates
- **HSTS**: Strict-Transport-Security header with 63072000s max-age and preload
- **Database**: `sslmode=require` recommended for production DATABASE_URL
- **S3/MinIO**: TLS for all object storage traffic in production

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

## Plugin Signing

Ed25519 cryptographic signing ensures plugin integrity in production (`PLUGIN_SAFE_MODE=true`).

**Process:**

1. Generate keys: `python scripts/sign_plugin.py keygen --key-dir keys`
2. Sign plugin: `python scripts/sign_plugin.py sign --plugin plugins/my-tool.json`
3. Verification: Platform loads `keys/plugin_signing.pub`, canonicalizes JSON, verifies signature
4. Unsigned plugins rejected in safe mode

See [Plugins](plugins.md) for details.

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
- Available via `GET /api/system/audit-log`

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
| `PLUGIN_SAFE_MODE` | `true` | Keep enabled in production |
| `FULLY_AUTOMATED` | `true` | Set `false` for human-in-the-loop |
| `REQUIRE_APPROVAL` | `false` | Enable for high-security environments |
| `SANDBOX_NETWORK_ISOLATION` | `true` | Keep enabled |
| `DEBUG` | `false` | Never enable in production |

See [Configuration](configuration.md) for all settings.
