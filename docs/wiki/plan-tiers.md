# Plan Tiers

> Spectra plan definitions for admin configuration.
> Updated: 2026-03-10

---

## Overview

Plans are **admin-managed** — created and edited via the Admin Panel (Plans tab). Each user is assigned one plan. New registrations get the plan marked `is_default = true`.

Plans control:
- Resource limits (missions, targets, storage, sandboxes)
- API rate limits
- Feature flags (autonomous mode, exports, API keys, etc.)

---

## Recommended Tier Configuration

### Free

| Field | Value |
|-------|-------|
| `name` | `free` |
| `display_name` | `Free` |
| `description` | `Get started with basic manual security testing` |
| `is_default` | `true` |
| `sort_order` | `0` |
| `max_concurrent_missions` | `1` |
| `max_missions_per_month` | `5` |
| `max_targets` | `10` |
| `sandbox_max_containers` | `1` |
| `sandbox_resource_tier` | `small` |
| `max_storage_mb` | `100` |
| `max_api_requests_per_hour` | `50` |
| `max_api_requests_per_day` | `200` |
| `features` | `{"autonomous_mode": false, "manual_mode": true, "report_export": ["json"], "custom_wordlists": false, "pipeline_builder": false, "cve_browser": true, "shell_access": false, "api_access": false, "vpn_support": false, "advanced_reporting": false}` |

### Starter

| Field | Value |
|-------|-------|
| `name` | `starter` |
| `display_name` | `Starter` |
| `description` | `For individual security researchers and bug bounty hunters` |
| `is_default` | `false` |
| `sort_order` | `1` |
| `max_concurrent_missions` | `2` |
| `max_missions_per_month` | `25` |
| `max_targets` | `50` |
| `sandbox_max_containers` | `1` |
| `sandbox_resource_tier` | `medium` |
| `max_storage_mb` | `500` |
| `max_api_requests_per_hour` | `100` |
| `max_api_requests_per_day` | `1000` |
| `features` | `{"autonomous_mode": true, "manual_mode": true, "report_export": ["json", "pdf", "html"], "custom_wordlists": true, "pipeline_builder": false, "cve_browser": true, "shell_access": true, "api_access": false, "vpn_support": false, "advanced_reporting": false}` |

### Professional

| Field | Value |
|-------|-------|
| `name` | `professional` |
| `display_name` | `Professional` |
| `description` | `Full-featured assessments for professional pentesters and consultancies` |
| `is_default` | `false` |
| `sort_order` | `2` |
| `max_concurrent_missions` | `5` |
| `max_missions_per_month` | `null` (unlimited) |
| `max_targets` | `500` |
| `sandbox_max_containers` | `3` |
| `sandbox_resource_tier` | `large` |
| `max_storage_mb` | `5000` |
| `max_api_requests_per_hour` | `500` |
| `max_api_requests_per_day` | `5000` |
| `features` | `{"autonomous_mode": true, "manual_mode": true, "report_export": ["json", "pdf", "html"], "custom_wordlists": true, "pipeline_builder": true, "cve_browser": true, "shell_access": true, "api_access": true, "vpn_support": true, "advanced_reporting": true}` |

### Enterprise

| Field | Value |
|-------|-------|
| `name` | `enterprise` |
| `display_name` | `Enterprise` |
| `description` | `Unlimited access for security teams and large organizations` |
| `is_default` | `false` |
| `sort_order` | `3` |
| `max_concurrent_missions` | `999` |
| `max_missions_per_month` | `null` (unlimited) |
| `max_targets` | `null` (unlimited) |
| `sandbox_max_containers` | `10` |
| `sandbox_resource_tier` | `xlarge` |
| `max_storage_mb` | `50000` |
| `max_api_requests_per_hour` | `5000` |
| `max_api_requests_per_day` | `50000` |
| `features` | `{"autonomous_mode": true, "manual_mode": true, "report_export": ["json", "pdf", "html"], "custom_wordlists": true, "pipeline_builder": true, "cve_browser": true, "shell_access": true, "api_access": true, "vpn_support": true, "advanced_reporting": true, "team_sharing": true}` |

---

## Plan Model Schema

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | UUID (auto) | — | Primary key |
| `name` | string(100) | — | Unique machine name (e.g., `free`, `starter`) |
| `display_name` | string(200) | — | Shown in UI (e.g., `Free`, `Starter`) |
| `description` | text | null | Marketing description for pricing page |
| `is_active` | bool | true | Whether plan is available for selection |
| `is_default` | bool | false | Assigned to new registrations (only one should be true) |
| `sort_order` | int | 0 | Display order on pricing page |
| `max_concurrent_missions` | int | 1 | Max active missions at once |
| `max_missions_per_month` | int/null | null | Monthly mission cap (null = unlimited) |
| `max_targets` | int/null | null | Total target count limit (null = unlimited) |
| `max_api_requests_per_hour` | int | 100 | Hourly API rate limit |
| `max_api_requests_per_day` | int | 1000 | Daily API rate limit |
| `sandbox_resource_tier` | string | `medium` | Container size: small/medium/large/xlarge |
| `sandbox_max_containers` | int | 1 | Max concurrent sandbox containers |
| `max_storage_mb` | int | 500 | S3 storage quota per user |
| `features` | JSONB | null | Feature flags (see Feature Flags section) |

---

## Feature Flags Reference

The `features` JSONB column stores a dictionary of feature toggles. When a feature is not present in the dictionary, it defaults to **allowed** (graceful degradation).

| Flag | Type | Description |
|------|------|-------------|
| `autonomous_mode` | bool | AI-driven autonomous mission execution |
| `manual_mode` | bool | Manual pentest session tools |
| `report_export` | list | Allowed export formats: `["json", "pdf", "html"]` |
| `custom_wordlists` | bool | Upload and manage custom wordlists |
| `pipeline_builder` | bool | Multi-tool pipeline chains |
| `cve_browser` | bool | CVE search and exploit database |
| `shell_access` | bool | Reverse shell WebSocket sessions |
| `api_access` | bool | Programmatic API key usage |
| `vpn_support` | bool | VPN config support on missions |
| `advanced_reporting` | bool | Executive summary generation |
| `team_sharing` | bool | Multi-user organization features (future) |

---

## Admin Plan Management

Plans are managed via:
- **Admin Panel** → Plans tab → Create/Edit/Deactivate plans
- **API**: `GET/POST/PUT/DELETE /api/admin/plans/`

### Creating Plans via API

```bash
POST /api/admin/plans/
Content-Type: application/json
Authorization: Bearer <admin_token>

{
  "name": "starter",
  "display_name": "Starter",
  "description": "For individual researchers",
  "max_concurrent_missions": 2,
  "max_missions_per_month": 25,
  "max_targets": 50,
  "features": {
    "autonomous_mode": true,
    "shell_access": true,
    "report_export": ["json", "pdf", "html"]
  }
}
```

### Initial Setup

On first app start, the setup wizard creates the admin user. Plans should be created immediately after via the Admin Panel. The first plan marked `is_default = true` will be assigned to all new registrations.
