# Spectra Plugin Configuration Guide

This document provides a comprehensive guide to creating, configuring, and managing tool plugins in Spectra.

---

## Table of Contents

1. [Overview](#overview)
2. [Plugin Structure](#plugin-structure)
3. [Field Reference](#field-reference)
4. [Categories & Capabilities](#categories--capabilities)
5. [AI Metadata](#ai-metadata)
6. [Installation Methods](#installation-methods)
7. [Execution Configuration](#execution-configuration)
8. [Output Parsing](#output-parsing)
9. [Stealth Configuration](#stealth-configuration)
10. [Security & Signing](#security--signing)
11. [Plugin Template](#plugin-template)
12. [Examples](#examples)

---

## Overview

Spectra uses a **Dynamic Plugin System** to integrate security tools. Each tool is defined in a JSON configuration file stored in the `plugins/` directory. The system supports:

- **Hot Loading**: Drop a `.json` file into `plugins/` to instantly register a new tool
- **Cryptographic Signing**: Ed25519 signatures to verify plugin integrity
- **AI-Driven Selection**: Rich metadata helps the AI choose the right tool for each situation
- **Stealth Profiles**: Per-tool configurations for stealthy operation

---

## Plugin Structure

A plugin configuration file is a JSON object with the following top-level structure:

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
  "ui": { ... },
  "signature": "hex-encoded-signature"
}
```

---

## Field Reference

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (lowercase, hyphens allowed). Pattern: `^[a-z0-9][a-z0-9-]*[a-z0-9]$` |
| `name` | string | Human-readable display name |
| `version` | string | Semantic version (e.g., `1.0.0`) |
| `category` | enum | Primary tool category (see [Categories](#categories--capabilities)) |
| `description` | string | Brief description of what the tool does |
| `execution` | object | Execution configuration (see [Execution](#execution-configuration)) |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metadata` | object | `{}` | AI-friendly metadata (see [AI Metadata](#ai-metadata)) |
| `installation` | object | `{}` | Installation configuration |
| `parsing` | object | `{}` | Output parsing configuration |
| `stealth` | object | `{}` | Stealth mode configuration |
| `ui` | object | `{}` | UI display configuration |
| `signature` | string | `null` | Ed25519 signature (required in production) |
| `is_system` | boolean | `false` | Whether this is a built-in system tool |

---

## Categories & Capabilities

### Primary Categories

| Category | Description | Example Tools |
|----------|-------------|---------------|
| `discovery` | Network reconnaissance and host discovery | Nmap, Naabu, Masscan |
| `enumeration` | Service and content enumeration | Ffuf, Gobuster, Amass |
| `vulnerability` | Vulnerability scanning | Nuclei, Nikto |
| `exploitation` | Exploitation and attacks | SQLMap, Metasploit, Hydra |
| `post_exploitation` | Post-exploitation activities | LinPEAS, BloodHound |
| `secrets` | Secret and credential scanning | Gitleaks, TruffleHog |
| `web` | Web-specific tools | WPScan, Nikto |
| `network` | Network-level tools | Nmap, Wireshark |
| `custom` | Custom/uncategorized tools | - |

### Capabilities (Fine-Grained)

Capabilities provide fine-grained classification for AI tool selection:

**Discovery Capabilities:**

- `port_scan` - Port scanning
- `service_detection` - Service version detection
- `os_detection` - Operating system fingerprinting
- `host_discovery` - Live host detection

**Enumeration Capabilities:**

- `subdomain_enum` - Subdomain enumeration
- `directory_brute` - Directory brute-forcing
- `dns_enum` - DNS enumeration
- `vhost_discovery` - Virtual host discovery
- `parameter_fuzzing` - Parameter fuzzing

**Web Capabilities:**

- `web_crawl` - Web crawling
- `web_fingerprint` - Web technology fingerprinting
- `cms_detection` - CMS detection
- `waf_detection` - WAF detection

**Vulnerability Capabilities:**

- `vuln_scan` - Vulnerability scanning
- `cve_detection` - CVE detection
- `misconfig_detection` - Misconfiguration detection

**Exploitation Capabilities:**

- `sql_injection` - SQL injection
- `command_injection` - Command injection
- `file_upload` - File upload exploitation
- `auth_bypass` - Authentication bypass
- `brute_force` - Brute force attacks
- `credential_spray` - Credential spraying
- `exploit_framework` - Exploit framework

**Post-Exploitation Capabilities:**

- `privilege_escalation` - Privilege escalation
- `lateral_movement` - Lateral movement
- `data_exfil` - Data exfiltration
- `persistence` - Persistence mechanisms

**Secrets Capabilities:**

- `secret_scan` - Secret scanning
- `credential_harvest` - Credential harvesting

---

## AI Metadata

The `metadata` object provides rich information for AI-driven tool selection:

```json
{
  "metadata": {
    "ai_description": "Detailed description for AI reasoning about when to use this tool",
    "capabilities": ["port_scan", "service_detection"],
    "supported_targets": ["ip", "ip_range", "cidr", "domain", "host"],
    "risk_level": "low",
    "tags": ["network", "ports", "discovery"],
    "use_cases": [
      "Initial network reconnaissance",
      "Service version detection"
    ],
    "limitations": [
      "May trigger IDS alerts",
      "Slow on large networks"
    ],
    "complements": ["nuclei", "nikto"],
    "prerequisites": []
  }
}
```

### Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `ai_description` | string | Detailed description for AI decision-making |
| `capabilities` | array | List of capabilities this tool provides |
| `supported_targets` | array | Target types: `ip`, `ip_range`, `cidr`, `domain`, `url`, `host`, `file`, `any` |
| `risk_level` | enum | Risk level: `passive`, `low`, `medium`, `high`, `critical` |
| `tags` | array | Searchable keywords for flexible matching |
| `use_cases` | array | Specific scenarios where this tool excels |
| `limitations` | array | Known limitations or unsuitable scenarios |
| `complements` | array | Tool IDs that work well with this tool |
| `prerequisites` | array | Tool IDs that should run before this tool |

### Risk Levels

| Level | Description | Examples |
|-------|-------------|----------|
| `passive` | No interaction with target | SearchSploit, OSINT tools |
| `low` | Read-only, minimal footprint | Nmap (version scan), Nuclei |
| `medium` | Active scanning, may trigger IDS | Nikto, Ffuf |
| `high` | Exploitation attempts | SQLMap, Hydra |
| `critical` | May cause damage | Metasploit exploits |

---

## Installation Methods

Configure how the tool should be installed:

```json
{
  "installation": {
    "method": "apt",
    "commands": [
      "apt-get update",
      "apt-get install -y nmap"
    ],
    "verification_command": "nmap --version",
    "verification_regex": "Nmap version (\\d+\\.\\d+)"
  }
}
```

### Supported Installation Methods

| Method | Description |
|--------|-------------|
| `none` | Tool is already installed (built-in) |
| `apt` | Install via apt-get |
| `pipx` | Install via pipx (isolated Python) |
| `go` | Install via `go install` |
| `binary` | Download pre-built binary |
| `script` | Run custom shell commands |

### Installation Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `method` | enum | Yes | Installation method |
| `commands` | array | No | Shell commands to run |
| `verification_command` | string | No | Command to verify installation |
| `verification_regex` | string | No | Regex to match against verification output |

---

## Execution Configuration

Define how the tool is executed:

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

### Execution Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `command` | string | Yes | - | Base command to run |
| `args_template` | string | No | `""` | Argument template with placeholders |
| `timeout` | integer | No | `300` | Default timeout in seconds |
| `working_dir` | string | No | `null` | Working directory for execution |
| `env` | object | No | `{}` | Additional environment variables |

### Template Placeholders

| Placeholder | Description |
|-------------|-------------|
| `{target}` | Target IP, domain, or URL |
| `{output_file}` | Path to output file |
| `{ports}` | Port specification (e.g., `-p 80,443`) |
| `{flags}` | Additional flags from tool_args |
| `{wordlist}` | Path to wordlist file |
| `{level}` | Scan intensity level |
| `{risk}` | Risk level for exploitation |

### Argument Modifiers

Use `arg_modifiers` to transform argument values before templating. This is useful for:

- Adding flag prefixes (e.g., `-x` for extensions)
- Converting lists to comma-separated values

```json
{
  "execution": {
    "command": "gobuster",
    "args_template": "dir -u {target} -w /usr/share/seclists/Discovery/Web-Content/common.txt {extensions}",
    "arg_modifiers": {
      "extensions": {
        "prefix": "-x ",
        "separator": ","
      }
    }
  }
}
```

| Modifier    | Description                                    |
| ----------- | ---------------------------------------------- |
| `prefix`    | String to prepend (e.g., `-x` adds flag)       |
| `separator` | Replace spaces with this character (e.g., `,`) |

**Example transformation:**

- Input: `{"extensions": "php html txt"}`
- After modifiers: `{"extensions": "-x php,html,txt"}`

---

## Output Parsing

Configure how tool output is parsed:

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

### Parsing Fields

| Field | Type | Description |
|-------|------|-------------|
| `format` | enum | Output format: `json`, `xml`, `text`, `ndjson`, `csv` |
| `mapping` | object | Field mapping from tool output to Spectra's Finding model |
| `jq_filter` | string | Optional jq filter for JSON output |

---

## Stealth Configuration

Configure tool behavior in stealth mode:

```json
{
  "stealth": {
    "rate_limit": 10,
    "delay_ms": 1000,
    "extra_args": {
      "-T": "2",
      "--scan-delay": "1s"
    }
  }
}
```

### Stealth Fields

| Field | Type | Description |
|-------|------|-------------|
| `rate_limit` | integer | Maximum requests/packets per second |
| `delay_ms` | integer | Delay between requests in milliseconds |
| `extra_args` | object | Additional arguments for stealth mode |

---

## Security & Signing

### Security Requirements Checklist

Before deploying a plugin, ensure it meets the following security requirements:

- [ ] **No Dangerous Commands**: Avoid `rm -rf`, `mkfs`, `dd`, or piping to `bash` (`| bash`).
- [ ] **Input Validation**: Ensure all arguments are properly escaped (handled by the platform, but verify logic).
- [ ] **Least Privilege**: The tool should not require root unless absolutely necessary.
- [ ] **Output Safety**: Ensure the tool doesn't output sensitive data (like private keys) to stdout/stderr if possible.
- [ ] **Resource Limits**: The tool should not consume excessive memory or CPU.
- [ ] **Network Restrictions**: The tool should only connect to the specified target.

### Plugin Signing

All plugins must be cryptographically signed in production mode (`PLUGIN_SAFE_MODE=true`). The signature is an Ed25519 signature of the canonicalized JSON (without the signature field).

**Generate Keys:**

```bash
python scripts/sign_plugin.py keygen --key-dir keys
```

**Sign a Plugin:**

```bash
python scripts/sign_plugin.py sign --plugin plugins/my-tool.json --key-dir keys
```

This will update the JSON file with a `signature` field.

**Verification Process:**

1. The platform loads the public key from `keys/plugin_signing.pub`.
2. It removes the `signature` field from the plugin JSON.
3. It canonicalizes the JSON (sorts keys, removes whitespace).
4. It verifies the signature against the canonical JSON.
5. If verification fails, the plugin is rejected (in safe mode).

### Safe Mode

When `PLUGIN_SAFE_MODE=true`, the system:

- Blocks dangerous commands (e.g., `rm -rf /`)
- Requires valid signatures
- Validates command patterns

---

## Plugin Template

Use this template as a starting point for new plugins:

```json
{
  "id": "my-tool",
  "name": "My Tool",
  "version": "1.0.0",
  "category": "discovery",
  "description": "Brief description of what the tool does",
  "metadata": {
    "ai_description": "Detailed description for AI reasoning. Explain WHEN to use this tool, WHAT it's good at, and any important context the AI should know.",
    "capabilities": ["port_scan"],
    "supported_targets": ["ip", "domain"],
    "risk_level": "low",
    "tags": ["keyword1", "keyword2"],
    "use_cases": [
      "Use case 1",
      "Use case 2"
    ],
    "limitations": [
      "Limitation 1",
      "Limitation 2"
    ],
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
    "mapping": {
      "name": "title",
      "severity": "severity"
    }
  },
  "stealth": {
    "rate_limit": 10,
    "delay_ms": 500,
    "extra_args": {}
  },
  "ui": {
    "icon": "terminal",
    "color": "violet"
  },
  "signature": null
}
```

---

## Examples

### Example 1: Network Scanner (Nmap)

```json
{
  "id": "nmap",
  "name": "Nmap",
  "version": "1.0.0",
  "category": "discovery",
  "description": "Network exploration tool and security/port scanner",
  "metadata": {
    "ai_description": "Nmap is the industry-standard network scanner. Use it for initial host discovery, port scanning, service version detection, and OS fingerprinting.",
    "capabilities": ["port_scan", "service_detection", "os_detection", "host_discovery"],
    "supported_targets": ["ip", "ip_range", "cidr", "domain", "host"],
    "risk_level": "low",
    "tags": ["network", "ports", "services", "fingerprinting"],
    "use_cases": [
      "Initial network reconnaissance",
      "Port scanning to find open services",
      "Service version detection"
    ],
    "limitations": [
      "May trigger IDS/IPS alerts",
      "Requires raw socket access for SYN scans"
    ],
    "complements": ["nuclei", "nikto"],
    "prerequisites": []
  },
  "installation": {
    "method": "none",
    "verification_command": "nmap --version",
    "verification_regex": "Nmap version (\\d+\\.\\d+)"
  },
  "execution": {
    "command": "nmap",
    "args_template": "-sV -sC {ports} {flags} -oX {output_file} {target}",
    "timeout": 600
  },
  "parsing": {
    "format": "xml",
    "mapping": {
      "name": "service",
      "port": "portid",
      "protocol": "protocol"
    }
  },
  "stealth": {
    "delay_ms": 1000,
    "extra_args": {
      "-T": "2",
      "--scan-delay": "1s"
    }
  },
  "ui": {
    "icon": "network",
    "color": "blue"
  }
}
```

### Example 2: Web Fuzzer (Ffuf)

```json
{
  "id": "ffuf",
  "name": "Ffuf",
  "version": "1.0.0",
  "category": "enumeration",
  "description": "Fast web fuzzer written in Go",
  "metadata": {
    "ai_description": "Ffuf is the fastest and most versatile web fuzzer. Use it for directory brute-forcing, parameter discovery, and virtual host enumeration.",
    "capabilities": ["directory_brute", "parameter_fuzzing", "vhost_discovery"],
    "supported_targets": ["url"],
    "risk_level": "low",
    "tags": ["web", "fuzzing", "directories", "api"],
    "use_cases": [
      "Fast directory enumeration",
      "Parameter discovery",
      "API endpoint enumeration"
    ],
    "limitations": [
      "Wordlist-dependent",
      "May trigger rate limiting"
    ],
    "complements": ["nuclei", "nikto"],
    "prerequisites": ["nmap"]
  },
  "installation": {
    "method": "go",
    "commands": ["go install github.com/ffuf/ffuf/v2@latest"],
    "verification_command": "ffuf -V",
    "verification_regex": "ffuf"
  },
  "execution": {
    "command": "ffuf",
    "args_template": "-u {target}/FUZZ -w {wordlist} -o {output_file} -of json",
    "timeout": 600
  },
  "parsing": {
    "format": "json",
    "mapping": {
      "url": "url",
      "status": "status"
    }
  },
  "stealth": {
    "rate_limit": 10,
    "delay_ms": 500
  },
  "ui": {
    "icon": "crosshair",
    "color": "yellow"
  }
}
```

### Example 3: Exploitation Tool (SQLMap)

```json
{
  "id": "sqlmap",
  "name": "SQLMap",
  "version": "1.0.0",
  "category": "exploitation",
  "description": "Automatic SQL injection and database takeover tool",
  "metadata": {
    "ai_description": "SQLMap is the de-facto standard for automated SQL injection detection and exploitation. Use it when you suspect SQL injection vulnerabilities.",
    "capabilities": ["sql_injection", "exploit_framework"],
    "supported_targets": ["url"],
    "risk_level": "high",
    "tags": ["sqli", "database", "exploitation", "injection"],
    "use_cases": [
      "Confirming SQL injection vulnerabilities",
      "Database enumeration and extraction"
    ],
    "limitations": [
      "Only targets SQL injection",
      "May cause database errors"
    ],
    "complements": ["nuclei"],
    "prerequisites": ["nmap", "nuclei"]
  },
  "installation": {
    "method": "none",
    "verification_command": "sqlmap --version",
    "verification_regex": "sqlmap version"
  },
  "execution": {
    "command": "sqlmap",
    "args_template": "-u {target} --batch --level={level} --risk={risk} --output-dir={output_file}",
    "timeout": 600
  },
  "parsing": {
    "format": "text",
    "mapping": {}
  },
  "stealth": {
    "rate_limit": 1,
    "delay_ms": 2000,
    "extra_args": {
      "--delay": "2",
      "--random-agent": "true"
    }
  },
  "ui": {
    "icon": "database",
    "color": "red"
  }
}
```

---

## Best Practices

1. **AI Descriptions**: Write detailed `ai_description` fields that explain WHEN and WHY to use the tool
2. **Capabilities**: List all relevant capabilities for accurate AI selection
3. **Prerequisites**: Define tool dependencies for proper sequencing
4. **Stealth Settings**: Always configure stealth mode for production use
5. **Testing**: Test plugins in development before signing
6. **Versioning**: Update version when making changes
7. **Security**: Always sign plugins before deployment

---

## Document History

Last Updated: December 2025
