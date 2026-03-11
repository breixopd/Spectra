# API Reference

[← Wiki Home](home.md) | [Configuration](configuration.md) | [Scaling](scaling.md) | [Architecture](architecture.md)

---

Comprehensive reference for the Spectra REST API.

## Base URL

All API endpoints are prefixed with `/api`.

- **Development:** `http://localhost:5000/api`
- **Production:** `https://<your-domain>/api` (via Caddy)

## Authentication

Most endpoints require a JWT token (exceptions: `/api/health`, `/api/auth/setup`, `/api/auth/setup/status`).

- **Header:** `Authorization: Bearer <token>`
- **Obtaining a Token:** `POST /api/auth/token` with username and password.

---

## Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Basic health check. Returns `{"status": "ok"}`. No auth required. |

---

## Authentication & Setup

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/token` | Login — returns JWT access + refresh tokens |
| POST | `/api/auth/refresh` | Refresh an expired access token |
| POST | `/api/auth/logout` | Invalidate current token |
| POST | `/api/auth/setup` | Create initial admin account (only before any users exist) |
| GET | `/api/auth/setup/status` | Check if setup has been completed |

### POST `/api/auth/token`

```text
Content-Type: application/x-www-form-urlencoded

username=admin&password=secret
```

**Response:**

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

Rate-limited with IP-based lockout after repeated failures.

---

## Missions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/missions` | Create and start a new mission |
| GET | `/api/missions` | List all missions |
| GET | `/api/missions/presets` | List mission presets |
| GET | `/api/missions/attack-summary` | Global attack summary across missions |
| GET | `/api/missions/adversary-playbooks` | List adversary playbooks |
| GET | `/api/missions/adversary-playbooks/{id}` | Get playbook details |
| GET | `/api/missions/exploit-chains` | List exploit chains |
| POST | `/api/missions/exploit-chains` | Create exploit chain |
| GET | `/api/missions/{id}` | Get mission details |
| POST | `/api/missions/{id}/stop` | Stop a running mission |
| POST | `/api/missions/{id}/pause` | Pause a mission |
| POST | `/api/missions/{id}/resume` | Resume a paused mission |
| POST | `/api/missions/{id}/steer` | Steer a running mission (modify objectives) |
| GET | `/api/missions/{id}/progress` | Get mission progress |
| GET | `/api/missions/{id}/task-tree` | Get mission task tree |
| GET | `/api/missions/{id}/diff/{other_id}` | Compare two missions |
| GET | `/api/missions/{id}/report/pdf` | Download PDF report |
| GET | `/api/missions/{id}/export/json` | Export mission as JSON |

### POST `/api/missions`

```json
{
  "target": "192.168.1.100",
  "directive": "Full security audit focusing on web vulnerabilities."
}
```

### POST `/api/missions/{id}/steer`

```json
{
  "instruction": "Focus on SQL injection vectors, skip brute force"
}
```

---

## Targets

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/targets` | Add a target |
| GET | `/api/targets` | List all targets |
| GET | `/api/targets/{id}` | Get target details |
| PATCH | `/api/targets/{id}` | Update target |
| DELETE | `/api/targets/{id}` | Delete a target |
| GET | `/api/targets/{id}/findings` | Get findings for a target |
| POST | `/api/targets/bulk-import` | Import multiple targets |
| POST | `/api/targets/bulk-delete` | Delete multiple targets |

---

## Findings

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/findings` | Create a finding |
| GET | `/api/findings` | List findings (filterable) |
| GET | `/api/findings/{id}` | Get finding details |
| PATCH | `/api/findings/{id}` | Update a finding |
| DELETE | `/api/findings/{id}` | Delete a finding |
| POST | `/api/findings/{id}/verify` | Mark finding as verified |
| POST | `/api/findings/{id}/confirm` | Confirm a finding |
| POST | `/api/findings/{id}/dismiss` | Dismiss a finding |
| POST | `/api/findings/{id}/false-positive` | Mark as false positive |
| POST | `/api/findings/{id}/retest` | Queue finding for retest |
| POST | `/api/findings/bulk-update` | Bulk update findings |
| GET | `/api/findings/export/csv` | Export findings as CSV |
| GET | `/api/findings/export/json` | Export findings as JSON |

---

## Tools

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tools` | List all registered tools |
| GET | `/api/tools/available` | List installed/available tools |
| GET | `/api/tools/for-ai` | Tool list formatted for AI agents |
| GET | `/api/tools/{id}` | Get tool details |
| GET | `/api/tools/{id}/config` | Get tool configuration |
| POST | `/api/tools/{id}/test` | Test-run a tool |
| POST | `/api/tools/{id}/install` | Install a specific tool |
| DELETE | `/api/tools/{id}` | Remove a tool plugin |
| POST | `/api/tools/validate` | Validate a plugin JSON |
| POST | `/api/tools/sign` | Sign a plugin |
| POST | `/api/tools/save-unsigned` | Save unsigned plugin |
| POST | `/api/tools/upload` | Upload a plugin file |
| POST | `/api/tools/install-all` | Install all registered tools |

See [Plugins](plugins.md) for the plugin JSON schema.

---

## Exploits

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/exploits` | List exploit attempts |
| GET | `/api/exploits/recent` | Recent exploit attempts |
| GET | `/api/exploits/stats` | Exploit statistics |
| GET | `/api/exploits/{id}` | Get exploit details |
| GET | `/api/exploits/by-name/{name}` | Search exploits by name |

---

## CVE Intelligence

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/cve/lookup` | Lookup CVEs by service/version |
| GET | `/api/cve/cve/{cve_id}/exploits` | Get exploits for a CVE |
| GET | `/api/cve/cve/{cve_id}/enriched` | Get enriched CVE data |
| GET | `/api/cve/searchsploit/{query}` | Search ExploitDB |

---

## System

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/system/status` | System health, DB state, tool install progress |
| GET | `/api/system/safety-stats` | Safety supervisor statistics |
| GET | `/api/system/audit-log` | Audit log entries |
| GET | `/api/system/data-sources` | Available data sources (CVE DBs, etc.) |
| POST | `/api/system/data-sources/refresh` | Trigger background refresh of data sources |
| POST | `/api/system/clear/tools` | Clear tool cache |
| POST | `/api/system/clear/missions` | Clear all missions |
| POST | `/api/system/clear/cache` | Clear application cache |
| POST | `/api/system/operations/add` | Register a background operation |
| POST | `/api/system/operations/remove` | Remove a background operation |
| POST | `/api/system/operations/update-progress` | Update operation progress |

---

## Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Get current runtime settings |
| POST | `/api/settings` | Update runtime settings |
| GET | `/api/ai/status` | AI provider connection status |
| POST | `/test-llm` | Test LLM connectivity |

See [Configuration](configuration.md) for all setting details.

---

## Server Pool Management

All server pool endpoints require superuser authentication. See [Scaling](scaling.md) for usage guide.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/servers` | List all registered server nodes |
| POST | `/api/admin/servers` | Register a new server node |
| DELETE | `/api/admin/servers/{id}` | Remove a server node |
| PATCH | `/api/admin/servers/{id}` | Update server node properties |
| POST | `/api/admin/servers/health-check` | Trigger health check on all nodes |
| POST | `/api/admin/servers/verify` | Test SSH connectivity to a remote server |
| POST | `/api/admin/servers/provision` | Auto-install service on remote server (202 Accepted) |
| POST | `/api/admin/servers/deprovision` | Remove service from remote server |

### POST `/api/admin/servers`

```json
{
  "service_type": "sandbox_worker",
  "name": "tools-server-1",
  "url": "http://192.168.1.50:9090",
  "weight": 2,
  "max_capacity": 20
}
```

Valid `service_type` values: `sandbox_worker`, `db`, `storage`.

### POST `/api/admin/servers/provision`

```json
{
  "host": "192.168.1.50",
  "port": 22,
  "username": "root",
  "private_key": "...",
  "service_type": "sandbox_worker",
  "service_port": 9090
}
```

---

## Service Health & Topology

| Method | Path | Description |
|--------|------|-------------|
| GET | `/system/services/health` | Health check all registered services |
| GET | `/system/services/topology` | Current service topology (local vs remote) |

---

## Observability

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/observability/stats` | Overall system metrics |
| GET | `/api/observability/metrics` | Prometheus-style metrics |
| GET | `/api/observability/traces` | Request traces |
| GET | `/api/observability/traces/{id}` | Trace details |
| GET | `/api/observability/slow-operations` | Slow operation report |
| GET | `/api/observability/errors` | Error log |
| GET | `/api/observability/services/health` | Per-service health |
| GET | `/api/observability/circuit-breakers` | Circuit breaker states |
| POST | `/api/observability/circuit-breakers/reset` | Reset circuit breakers |
| GET | `/api/observability/cache/stats` | Cache hit/miss stats |
| GET | `/api/observability/events` | Event stream |
| GET | `/api/observability/events/stats` | Event statistics |

---

## Pentest Sessions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/pentest-sessions` | Create a session |
| GET | `/api/pentest-sessions` | List sessions |
| GET | `/api/pentest-sessions/{id}` | Get session details |
| POST | `/api/pentest-sessions/{id}/log` | Add log entry |
| POST | `/api/pentest-sessions/{id}/complete` | Mark complete |
| GET | `/api/pentest-sessions/{id}/export` | Export session |
| POST | `/api/pentest-sessions/{id}/notes` | Add note |
| GET | `/api/pentest-sessions/{id}/notes` | List notes |
| PUT | `/api/pentest-sessions/{id}/notes` | Update notes |
| DELETE | `/api/pentest-sessions/{id}/notes/{nid}` | Delete note |
| POST | `/api/pentest-sessions/{id}/history` | Add history entry |
| GET | `/api/pentest-sessions/{id}/history` | Get history |
| POST | `/api/pentest-sessions/{id}/evidence` | Upload evidence |
| GET | `/api/pentest-sessions/{id}/evidence` | List evidence |
| DELETE | `/api/pentest-sessions/{id}/evidence/{eid}` | Delete evidence |
| PUT | `/api/pentest-sessions/{id}/scope` | Update session scope |

---

## VPN

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/vpn` | Upload VPN config |
| GET | `/api/vpn/configs` | List VPN configs |
| DELETE | `/api/vpn/configs/{name}` | Delete a VPN config |
| POST | `/api/vpn/connect/{name}` | Connect to VPN |
| POST | `/api/vpn/disconnect/{name}` | Disconnect from VPN |
| GET | `/api/vpn/status` | Current VPN status |
| POST | `/api/vpn/test` | Test VPN connectivity |

---

## Wordlists

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/wordlists` | List available wordlists |
| POST | `/api/wordlists/upload` | Upload a wordlist |
| POST | `/api/wordlists/download-preset/{id}` | Download a preset wordlist |
| DELETE | `/api/wordlists/{filename}` | Delete a wordlist |

---

## Manual Helpers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/manual-helpers/checklists` | List pentest checklists |
| GET | `/api/manual-helpers/checklists/{id}` | Get checklist details |
| GET | `/api/manual-helpers/payloads` | List payload templates |
| GET | `/api/manual-helpers/gtfobins` | GTFOBins reference |
| POST | `/api/manual-helpers/cvss/calculate` | Calculate CVSS score |
| GET | `/api/manual-helpers/reports/templates` | List report templates |
| POST | `/api/manual-helpers/reports/generate` | Generate a report |

---

## Shell (WebSocket)

| Method | Path | Description |
|--------|------|-------------|
| WebSocket | `/api/shell/{session_id}` | Interactive reverse shell session |
| GET | `/api/shell/sessions` | List active shell sessions |
| POST | `/api/shell/reconnect/{finding_id}` | Reconnect to a shell |

---

## WebSocket (Real-time)

| Protocol | Path | Description |
|----------|------|-------------|
| WebSocket | `/ws?token=<jwt>` | Real-time mission updates, logs, findings stream |

Pass JWT as query parameter. Connection rejected if token is invalid or missing.
