# Access Control Matrix

> Complete reference of what each role and plan tier can access in Spectra.
> Updated: 2026-03-10

---

## Roles Overview

| Role | Description | Default? |
|------|------------|----------|
| **Admin** | Full platform control — users, settings, plugins, all data | First user (setup) |
| **Operator** | Standard pentest user — runs missions, manages targets, uses tools | Registration default |
| **Viewer** | Read-only — can view missions, findings, targets, reports | Assigned by admin |

---

## Role Permissions Matrix

| Permission | Admin | Operator | Viewer |
|-----------|:-----:|:--------:|:------:|
| **View Missions** | Yes | Yes | Yes |
| **Create Missions** | Yes | Yes | No |
| **Manage Missions** (pause, resume, delete) | Yes | Yes | No |
| **View Findings** | Yes | Yes | Yes |
| **Manage Findings** (verify, dismiss, update) | Yes | Yes | No |
| **View Targets** | Yes | Yes | Yes |
| **Manage Targets** (create, update, delete) | Yes | Yes | No |
| **Use Tools** (manual tools, wordlists, pipelines) | Yes | Yes | No |
| **Shell Access** (reverse shells, WS sessions) | Yes | Yes | No |
| **View Reports** (export PDF/JSON/HTML) | Yes | Yes | Yes |
| **Manage Settings** (runtime config, AI, services) | Yes | No | No |
| **Manage Users** (create, edit, deactivate users) | Yes | No | No |
| **View Audit Log** | Yes | No | No |

---

## Data Isolation

All user data is isolated by `user_id`. Each user only sees their own:

| Data Type | User-Scoped | Admin Override |
|----------|:-----------:|:--------------:|
| Missions | Yes | Sees all users |
| Targets | Yes | Sees all users |
| Findings | Yes | Sees all users |
| Exploits | Yes | Sees all users |
| Pentest Sessions | Yes | Sees all users |
| Shell Sessions | Yes (via mission ownership) | Sees all |
| Wordlists (custom) | Yes (S3: `{user_id}/wordlists/`) | Sees all |
| Wordlists (system) | Read-only for all | Admin manages |
| Reports | Yes (via mission ownership) | Sees all |
| S3 Storage | Scoped: `{user_id}/{mission_id}/...` | Full access |

---

## Plan Tiers — Feature Access

Plans are **admin-configured** via Admin Panel > Plans. Below are the recommended tier definitions.

### Resource Limits by Plan

| Limit | Free | Starter | Professional | Enterprise |
|-------|:----:|:-------:|:------------:|:----------:|
| Concurrent Missions | 1 | 2 | 5 | Unlimited |
| Missions per Month | 5 | 25 | Unlimited | Unlimited |
| Max Targets | 10 | 50 | 500 | Unlimited |
| Sandbox Containers | 1 | 1 | 3 | 10 |
| Sandbox Resource Tier | small | medium | large | xlarge |
| Storage (MB) | 100 | 500 | 5000 | 50000 |
| API Requests / Hour | 50 | 100 | 500 | 5000 |
| API Requests / Day | 200 | 1000 | 5000 | 50000 |

### Feature Flags by Plan

| Feature | Free | Starter | Professional | Enterprise |
|---------|:----:|:-------:|:------------:|:----------:|
| **Autonomous Mode** (AI-driven missions) | No | Yes | Yes | Yes |
| **Manual Mode** (tools, sessions, helpers) | Yes | Yes | Yes | Yes |
| **Report Export** (PDF/JSON/HTML) | JSON only | All formats | All formats | All formats |
| **Custom Wordlists** (upload, manage) | No | Yes | Yes | Yes |
| **Pipeline Builder** (multi-tool chains) | No | No | Yes | Yes |
| **CVE Browser** (search + exploit DB) | Yes | Yes | Yes | Yes |
| **Shell Access** (reverse shell sessions) | No | Yes | Yes | Yes |
| **API Access** (programmatic API keys) | No | No | Yes | Yes |
| **VPN Support** (mission-level VPN configs) | No | No | Yes | Yes |
| **Advanced Reporting** (executive summary) | No | No | Yes | Yes |
| **Team Sharing** (multi-user org — future) | No | No | No | Yes |

---

## Page & Endpoint Access

### Public Pages (No Auth Required)

| Page | Path | Description |
|------|------|-------------|
| Landing Page | `/` | Marketing page with pricing, Sign In + Get Started buttons |
| Login | `/login` | Authentication form |
| Register | `/register` | Self-service registration with plan selection |
| Forgot Password | `/forgot-password` | Password reset request |
| Reset Password | `/reset-password` | Password reset form (with token) |
| Pricing | `/pricing` | Plan comparison (links to register) |
| Health Check | `/api/health` | System health status |

### Authenticated Pages

| Page | Path | Roles | Description |
|------|------|-------|-------------|
| Dashboard | `/dashboard` | All | Mission overview, quick actions |
| Mission History | `/history` | All | Past missions with search/filter |
| New Mission | `/missions/new` | Operator, Admin | Create new assessment mission |
| Manual Tools | `/manual/{session_id}` | Operator, Admin | Pentest session workspace |
| Toolbox | `/toolbox` | All (read-only for non-admin) | Installed tools catalog |
| Plugin Creator | `/toolbox/create` | **Admin only** | Create new tool plugins |
| Reports | `/reports` | All | Report browser and export |
| Admin Panel | `/admin` | **Admin only** | User management, plans, settings |
| Settings | `/settings` | All authenticated | AI, storage, system config |

### API Endpoints Summary

| Area | Endpoints | Auth | User Isolated | Plan Limited |
|------|-----------|------|:------------:|:------------:|
| Missions | 16+ CRUD + control | Operator+ | Yes | Concurrent + monthly limits |
| Targets | 8 CRUD + bulk | Operator+ | Yes | Max targets limit |
| Findings | 12 CRUD + verify + bulk | Operator+ | Yes | Via mission/target |
| Exploits | 5 read + stats | Operator+ | Yes | Via mission/target |
| Pentest Sessions | 15+ CRUD + evidence | Operator+ | Yes | Via mission |
| Manual Helpers | 8 utility endpoints | Operator+ | Yes | Via session |
| Shell | 3 WebSocket + list | Operator+ | Yes | Via mission |
| Wordlists | 5 CRUD + list | Operator+ | Yes | Custom per-user |
| Reports | 2 export + list | Viewer+ | Yes | Via mission |
| Plugins/Tools | 8 CRUD + validate | Read: All, Write: **Admin** | N/A | N/A |
| Admin | 20+ user/plan/settings | **Admin only** | N/A | N/A |
| Auth | 4 login/logout/refresh | Public (login), Auth (others) | N/A | N/A |
| Public | 6 register/reset/plans | Public | N/A | Rate limited |

---

## Rate Limiting

| Endpoint | Limit | Scope |
|----------|-------|-------|
| `POST /api/auth/token` (login) | 5/minute | Per IP |
| `POST /api/public/register` | 3/minute | Per IP |
| `POST /api/public/forgot-password` | 5/minute | Per IP |
| `POST /api/public/reset-password` | 5/minute | Per IP |
| `POST /api/missions/` (start) | 5/minute | Per user |
| `POST /setup` (initial setup) | 3/minute | Per IP |

---

## Plugin Management Access

| Action | Admin | Operator | Viewer |
|--------|:-----:|:--------:|:------:|
| View installed tools | Yes | Yes | Yes |
| View tool details/config | Yes | Yes | Yes |
| Upload plugin | Yes | No | No |
| Create plugin (editor) | Yes | No | No |
| Sign plugin | Yes | No | No |
| Delete plugin | Yes | No | No |
| Validate plugin | Yes | No | No |

---

## Security Controls

- **Password**: Bcrypt hashed, min length enforced
- **JWT**: HS256 with SecretStr, configurable expiry
- **Account lockout**: After failed login attempts (file-based, async I/O)
- **CORS**: Explicit origin allowlist (no wildcard)
- **CSRF**: Token-based protection on forms
- **Path traversal**: Resolved-path validation in StorageService
- **SQL injection**: SQLAlchemy ORM (parameterized queries throughout)
- **Token blacklist**: In-memory with 10K cap + expired-token pruning
