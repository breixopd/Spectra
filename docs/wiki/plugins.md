# Plugins

[← Wiki Home](home.md) | [Architecture](architecture.md) | [API Reference](api-reference.md)

---

Comprehensive guide to creating, configuring, and managing tool plugins in Spectra.

## Overview

Spectra uses a **Dynamic Plugin System** to integrate security tools. Each tool is defined in a JSON configuration file stored in the `plugins/` directory. The system supports:

- **Hot Loading**: Drop a `.json` file into `plugins/` to instantly register a new tool
- **AI-Driven Selection**: Rich metadata helps the AI choose the right tool for each situation
- **Stealth Profiles**: Per-tool configurations for stealthy operation
- **Golden image**: Plugin `installation` blocks drive rebuilds of `spectra-tools:latest`; changing plugins emits `PLUGIN_UPDATED` and regenerates the Dockerfile layers from `plugins/*.json`

---

## Plugin Structure

```json
{
  "id": "tool-id",
  "name": "Tool Display Name",
  "version": "1.0.0",
  "category": "discovery",
  "description": "Brief description",
  "metadata": { ... },
  "installation": { ... },
  "execution": { ... },
  "parsing": { ... },
  "stealth": { ... },
  "ui": { ... }
}
```

---

## Field Reference

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (lowercase, hyphens). Pattern: `^[a-z0-9][a-z0-9-]*[a-z0-9]$` |
| `name` | string | Human-readable display name |
| `version` | string | Semantic version (e.g., `1.0.0`) |
| `category` | enum | Primary tool category (see below) |
| `description` | string | Brief description of what the tool does |
| `execution` | object | Execution configuration |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metadata` | object | `{}` | AI-friendly metadata |
| `installation` | object | `{}` | Installation configuration |
| `parsing` | object | `{}` | Output parsing configuration |
| `stealth` | object | `{}` | Stealth mode configuration |
| `ui` | object | `{}` | UI display configuration |
| `is_system` | boolean | `false` | Whether this is a built-in system tool |
| `enabled` | boolean | `true` | When `false`, the registry marks the tool disabled and skips availability checks |

---

## Categories & Capabilities

### Primary Categories

| Category | Description | Example Tools |
|----------|-------------|---------------|
| `discovery` | Network reconnaissance and host discovery | Nmap, Naabu |
| `enumeration` | Service and content enumeration | Ffuf, Gobuster, Amass |
| `vulnerability` | Vulnerability scanning | Nuclei, Nikto |
| `exploitation` | Exploitation and attacks | SQLMap, Metasploit, Hydra |
| `post_exploitation` | Post-exploitation activities | LinPEAS |
| `secrets` | Secret and credential scanning | Gitleaks |
| `web` | Web-specific tools | WPScan, Nikto |
| `network` | Network-level tools | Nmap |
| `custom` | Custom/uncategorized tools | — |

### Capabilities (Fine-Grained)

Capabilities provide fine-grained classification for AI tool selection:

**Discovery:** `port_scan`, `service_detection`, `os_detection`, `host_discovery`

**Enumeration:** `subdomain_enum`, `directory_brute`, `dns_enum`, `vhost_discovery`, `parameter_fuzzing`

**Web:** `web_crawl`, `web_fingerprint`, `cms_detection`, `waf_detection`

**Vulnerability:** `vuln_scan`, `cve_detection`, `misconfig_detection`

**Exploitation:** `sql_injection`, `command_injection`, `file_upload`, `auth_bypass`, `brute_force`, `credential_spray`, `exploit_framework`

**Post-Exploitation:** `privilege_escalation`, `lateral_movement`, `data_exfil`, `persistence`

**Secrets:** `secret_scan`, `credential_harvest`

---

## AI Metadata

```json
{
  "metadata": {
    "ai_description": "Detailed description for AI reasoning about when to use this tool",
    "capabilities": ["port_scan", "service_detection"],
    "supported_targets": ["ip", "ip_range", "cidr", "domain", "host"],
    "risk_level": "low",
    "tags": ["network", "ports", "discovery"],
    "use_cases": ["Initial network reconnaissance"],
    "limitations": ["May trigger IDS alerts"],
    "complements": ["nuclei", "nikto"],
    "prerequisites": []
  }
}
```

### Risk Levels

| Level | Description | Examples |
|-------|-------------|---------|
| `passive` | No interaction with target | SearchSploit, OSINT tools |
| `low` | Read-only, minimal footprint | Nmap (version scan), Nuclei |
| `medium` | Active scanning, may trigger IDS | Nikto, Ffuf |
| `high` | Exploitation attempts | SQLMap, Hydra |
| `critical` | May cause damage | Metasploit exploits |

---

## Installation Methods

```json
{
  "installation": {
    "method": "apt",
    "commands": ["apt-get update", "apt-get install -y nmap"],
    "verification_command": "nmap --version",
    "verification_regex": "Nmap version (\\d+\\.\\d+)"
  }
}
```

| Method | Description |
| -------- | ------------- |
| `none` | Tool is already installed (built-in) |
| `apt` | Install via apt-get |
| `pipx` | Install via pipx (isolated Python) |
| `go` | Install via `go install` |
| `binary` | Download pre-built binary |
| `script` | Run custom shell commands |

---

## Execution Configuration

```json
{
  "execution": {
    "command": "nmap",
    "args_template": "-sV -sC {ports} {flags} -oX {output_file} {target}",
    "timeout": 600,
    "working_dir": null,
    "env": {}
  }
}
```

### Template Placeholders

| Placeholder | Description |
| ------------- | ------------- |
| `{target}` | Target IP, domain, or URL |
| `{output_file}` | Path to output file |
| `{ports}` | Port specification (e.g., `-p 80,443`) |
| `{flags}` | Additional flags from tool_args |
| `{wordlist}` | Path to wordlist file |
| `{level}` | Scan intensity level |
| `{risk}` | Risk level for exploitation |

### Argument Modifiers

```json
{
  "execution": {
    "arg_modifiers": {
      "extensions": {
        "prefix": "-x ",
        "separator": ","
      }
    }
  }
}
```

---

## Output Parsing

```json
{
  "parsing": {
    "format": "xml",
    "mapping": {
      "name": "service",
      "port": "portid",
      "protocol": "protocol",
      "state": "state"
    },
    "jq_filter": null
  }
}
```

Supported formats: `json`, `xml`, `text`, `ndjson`, `csv`.

---

## Stealth Configuration

```json
{
  "stealth": {
    "rate_limit": 10,
    "delay_ms": 1000,
    "extra_args": { "-T": "2", "--scan-delay": "1s" }
  }
}
```

---

---

## Included Plugins

Spectra ships with 25+ tool plugins:

| Plugin | Category | Description |
| -------- | ---------- | ------------- |
| nmap | discovery | Network scanner and port mapper |
| nuclei | vulnerability | Template-based vulnerability scanner |
| nikto | vulnerability | Web server scanner |
| gobuster | enumeration | Directory/DNS brute-forcing |
| ffuf | enumeration | Web fuzzer |
| hydra | exploitation | Network login brute-forcer |
| sqlmap | exploitation | SQL injection toolkit |
| metasploit | exploitation | Exploitation framework |
| searchsploit | vulnerability | ExploitDB search |
| wpscan | web | WordPress scanner |
| amass | enumeration | Subdomain enumeration |
| naabu | discovery | Fast port scanner |
| whatweb | web | Web fingerprinter |
| dirsearch | enumeration | Directory brute-forcer |
| subfinder | enumeration | Subdomain discovery |
| feroxbuster | enumeration | Content discovery |
| httpx | web | HTTP toolkit |
| testssl | vulnerability | TLS/SSL testing |
| linpeas | post_exploitation | Linux privilege escalation |
| winpeas | post_exploitation | Windows privilege escalation |
| crackmapexec | exploitation | Network attack framework |
| kerbrute | exploitation | Kerberos brute-forcer |
| enum4linux | enumeration | SMB/NetBIOS enumeration |
| impacket | exploitation | Network protocol toolkit |
| socat | network | Multipurpose relay |
| chisel | network | TCP/UDP tunnel |

---

## Plugin Template

```json
{
  "id": "my-tool",
  "name": "My Tool",
  "version": "1.0.0",
  "category": "discovery",
  "description": "Brief description of what the tool does",
  "metadata": {
    "ai_description": "Detailed description for AI reasoning.",
    "capabilities": ["port_scan"],
    "supported_targets": ["ip", "domain"],
    "risk_level": "low",
    "tags": ["keyword1"],
    "use_cases": ["Use case 1"],
    "limitations": ["Limitation 1"],
    "complements": ["other-tool-id"],
    "prerequisites": []
  },
  "installation": {
    "method": "none",
    "commands": [],
    "verification_command": "my-tool --version",
    "verification_regex": "version (\\d+\\.\\d+\\.\\d+)"
  },
  "execution": {
    "command": "my-tool",
    "args_template": "{target} -o {output_file} {flags}",
    "timeout": 300
  },
  "parsing": {
    "format": "json",
    "mapping": { "name": "title", "severity": "severity" }
  },
  "stealth": {
    "rate_limit": 10,
    "delay_ms": 500,
    "extra_args": {}
  },
  "ui": { "icon": "terminal", "color": "violet" }
}
```

### Adding a New Tool

1. Create `plugins/my-tool.json` following the schema above.
2. Restart spectra_platform/worker or reload plugins via the API so the registry picks up the file; golden-image rebuild follows plugin updates.
3. The tool appears in the registry. Execution installs into sandboxes as needed (see [Sandboxes](sandboxes.md#golden-image-system)).
