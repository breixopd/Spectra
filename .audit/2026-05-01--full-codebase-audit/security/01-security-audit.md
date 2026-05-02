# Spectra security notes (read-only)

**Scope:** auth/JWT, subprocess, Compose secrets, CORS, RBAC, injection-adjacent patterns. Not a pentest.

## Confirmed

- **Compose defaults:** `docker/compose.yaml` uses predictable fallbacks (DB/Redis/Garage/S3 keys, `SERVICE_AUTH_SECRET`, `APP_PASSWORD`/`ADMIN_PASSWORD` default `Admin123!`). Fine for isolated dev; **override** for shared or prod-like deploys.
- **Shell when `str` command:** `spectra_platform/services/tools/registry/executor.py` and `services/worker/.../helpers.py` call `create_subprocess_shell` for string commands. **Shell injection** if any untrusted input reaches that path; prefer argv lists.
- **Rate limit JWT decode:** `spectra_platform/auth/rate_limit.py` decodes Bearer JWTs **without** blacklist/session checks for per-user keys. Revoked tokens can still shape rate buckets (not an API auth bypass).
- **RBAC split:** `get_current_superuser` only checks `is_superuser`; `require_permission` (`services/api/authz.py`) treats `role=="admin"` as full permissions. **`admin` without `is_superuser`** passes permission gates but fails superuser-only endpoints—inconsistent vertical control.
- **Key coupling:** `spectra_platform/auth/security.py` falls back MFA Fernet key from **`JWT_SECRET_KEY`** if `ENCRYPTION_KEY` unset—signing compromise widens impact.
- **JWT bootstrap:** `spectra_platform/core/config.py` may auto-generate JWT secret when empty outside production—unsafe if environment mis-tagged.
- **Admin IP allowlist:** `AdminIPAllowlistMiddleware` is **off** when `ADMIN_IP_ALLOWLIST` empty; admin APIs then rely on app auth + deployment posture.
- **Service auth:** `spectra_platform/di/service_auth.py` 401 when secret missing (except `/health`,`/healthz`)—fail-closed.
- **CORS:** `CORS_ORIGINS` rejects `*` in settings; API uses enumerated origins + `allow_credentials=True`; `SecurityHeadersMiddleware` validates `Origin` on mutating requests when not `DEBUG`.

## Suspected / partial review

- **IDOR:** Many routes scope by user for non-superusers; **not all routers** traced—missions/findings/export deserve targeted checks.
- **MCP:** Single `MCP_API_KEY` in `services/api/api/mcp.py`—strength/rotation is operational.
- **JWT blacklist:** In-process cap (`JWT_BLACKLIST_MAX_SIZE`); eviction under load/multi-replica **needs validation**.
- **Client IP:** Rate limits use `request.client.host`; correct limits assume **trusted reverse proxy** config.
- **Static pentest JS** under `services/api/static/js/`: product-intended strings; risk is **mis-categorized exposure**, not automatic RCE.

## Next steps

Rotate away Compose literals for non-local; split signing vs encryption secrets; subprocess lists over strings; reconcile `admin` role vs `is_superuser`; spot-audit high-value IDs for ownership.
