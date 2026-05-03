# API & Backend Robustness Audit — 2026-05-03

## CRITICAL (5)

| # | File | Issue | Fix |
|---|------|-------|-----|
| C1 | factory.py:100-105 | CORS hardcoded to localhost only | Add CORS_ORIGINS env var support |
| C2 | factory.py:83-85 | Swagger/Redoc enabled when DEBUG=True | Disable in production |
| C3 | config.py:58 | DEBUG not enforced | Add production safety check |
| C4 | billing.py:229-239 | Webhook endpoints unauthenticated | Add HMAC verification |
| C5 | shell.py, vpn.py, wordlists.py, manual_helpers.py | Missing upgrade CTAs on feature gates | Add plan name + upgrade link |

## HIGH (10)

| # | File | Issue | Fix |
|---|------|-------|-----|
| H1 | missions/core.py:88-223 | No size limit on directive/requirements | Add field max_length |
| H2 | targets.py:325-374 | No address validation on bulk import | Add IP/hostname format check |
| H3 | vpn.py:89-131 | No content-type validation on upload | Add MIME type check |
| H4 | lifecycle.py:110-148 | No rollback on partial mission creation failure | Add transaction rollback |
| H5 | lifecycle.py:167-197 | No rollback on stop failure | Add compensation logic |
| H6 | factory.py:198-210 | Internal metrics weak HMAC | Use proper secret derivation |
| H7 | vpn.py:89-131 | File written without virus scan | Add ClamAV integration |
| H8 | targets.py:81-132 | No IP/hostname format validation | Add validator |
| H9 | findings/core.py:36-67 | Evidence allows arbitrary dict keys | Whitelist allowed keys |
| H10 | exploits.py:28-89 | Redaction regex edge cases | Test and harden patterns |

## MEDIUM (12)

| # | File | Issue |
|---|------|-------|
| M1 | missions/core.py:226-327 | Target filter slow on large datasets |
| M2 | lifecycle.py:77-165 | No idempotency key support |
| M3 | billing/quota_enforcer.py | No retry for transient failures |
| M4 | missions/core.py:88-223 | New roe/framework fields lack validation |
| M5 | roe_validator.py | New validator needs edge case tests |
| M6 | billing.py:44-72 | Free tier not clearly distinguished |
| M7 | plan.py | Free plan limitations enforcement |
| M8 | wordlists.py:140-181 | No malware scanning on upload |
| M9 | factory.py:150-174 | Timeout exempt paths lack auth check |
| M10 | targets.py | Address not format-validated |
| M11 | findings/core.py | Evidence sanitization |
| M12 | missions/core.py | Mission fields validation |
