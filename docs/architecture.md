# Architecture

Technical deep-dive into Spectra's agent system, execution pipeline, and learning mechanisms.

---

## Agent System (MAKER Framework)

Spectra uses the **MAKER** framework: Maximal Agentic decomposition, K-threshold Error mitigation, and Red-flagging.

### Agent Roles

| Agent | Role | Temperature | Description |
|-------|------|------------|-------------|
| ScopeAgent | Scope | 0.1 | Parses targets (IPs, domains, CIDRs) from user input |
| ToolSelectorAgent | Tool Selection | 0.3 | Selects and configures the right security tool for each task |
| MissionController | Planning | 0.4 | Creates PTES-aligned mission plans, handles steering |
| ExploitCrafter | Exploitation | 0.7 | Selects exploits, configures payloads, iterative retry |
| PayloadCrafter | Payloads | 0.3 | Crafts specific payloads for discovered vulnerabilities |
| POCDeveloper | Code Gen | 0.2 | Writes custom exploit scripts (Python/Go/Bash) |
| VectorGenerator | Analysis | 0.3 | Generates attack vectors from discovered services |
| SafetySupervisor | Safety | 0.1 | Blocks dangerous commands via regex + LLM analysis |
| PostExploitation | Post-Exploit | 0.3 | Plans privilege escalation, persistence, lateral movement |
| ReporterAgent | Reporting | 0.3 | Generates PTES-standard assessment reports |

### Consensus System (K-Threshold Voting)

Critical decisions pass through quality gates where multiple LLM instances vote:

| Gate | When | Voters | Threshold | Min Confidence |
|------|------|--------|-----------|----------------|
| PLAN | Mission planning | 3 | 2/3 | 70% |
| TOOL_SELECTION | Each tool pick | 2 | 2/2 | 50% |
| PAYLOAD | Exploit crafting | 3 | 2/3 | 70% |
| REPLAN | Plan changes | 3 | 2/3 | 60% |
| EXECUTION | High-risk actions | 3 | 3/3 | 80% |

---

## Execution Pipeline

```
User enters target + directive
        │
        ▼
  MissionController creates plan
        │ (validated at PLAN gate)
        ▼
  For each task in plan:
        │
        ├─ tool_selector → picks tool → ToolExecutionService
        │                                      │
        │                        ┌──────────────┘
        │                        ▼
        │              SafetySupervisor checks command
        │                        │
        │                  ┌─────┴─────┐
        │                SAFE        BLOCKED
        │                  │
        │                  ▼
        │         ARQ Worker executes in tools container
        │                  │
        │                  ▼
        │         Output parsed → Findings → Attack Surface updated
        │                  │
        │                  ▼
        │         Memory records tool result + OS detection
        │
        ├─ exploit_crafter → iterative exploitation loop
        │         CVE intel → Memory → RAG → Exploit selection
        │         Retry with different payloads/strategies
        │         On success: record chain to memory + playbook
        │
        ├─ reporter → generates PTES report
        │
        ▼
  Mission complete → post-mission learning
        │
        ├─ False positive detection (repeated info findings)
        ├─ OS profile update
        └─ Memory stats logged
```

---

## Learning System

### Persistent Memory (`memory.py`)

Stored as JSON files in `reports/memory/`:

- **tool_lessons.json** — which tools produced findings for which services
- **exploit_lessons.json** — successful exploit chains with CVEs
- **target_profiles.json** — effective/ineffective tools per OS family
- **false_positives.json** — noisy template IDs to skip

### Playbook Engine (`playbook.py`)

Deterministic service-to-tool mapping (no LLM needed):

- HTTP → nmap → nuclei → nikto → gobuster → sqlmap
- SSH → nmap with scripts → hydra (default creds only) → searchsploit
- SMB → nmap with smb-vuln scripts → metasploit ms17-010
- FTP → nmap with ftp-anon → hydra
- WordPress → wpscan → nuclei wordpress templates

### CVE Intelligence (`cve_intel.py`)

Built-in database of 25+ commonly exploited CVEs. Correlates discovered service versions to known exploits:

```
nmap finds Apache 2.4.49
    → cve_intel returns CVE-2021-41773 (path traversal, CRITICAL, VERSION MATCH)
    → exploit_crafter uses this as primary candidate
```

### Grounding Framework (`grounding.py`)

Anti-hallucination mechanisms:
- Tool output validation (signature pattern matching)
- Evidence extraction (meaningful lines only, not full output)
- Confidence tracking with decay
- Agents must cite concrete evidence in reasoning

---

## LLM Routing (`router.py`)

LiteLLM-powered smart routing:

### Task Tiers

| Tier | Tasks | Recommended Model |
|------|-------|------------------|
| 1 (Simple) | Scope, tool selection, safety | qwen2.5:3b, gpt-4o-mini |
| 2 (Moderate) | Planning, consensus, reporting | gpt-4o-mini, claude-3-haiku |
| 3 (Complex) | Exploit crafting, POC generation | gpt-4o, claude-3.5-sonnet |

### Fallback Chain

```
Ollama (local) → Cloud API (OpenAI/Anthropic) → Mock (testing)
```

---

## Plugin System

### Adding a New Tool

1. Create `plugins/my-tool.json` following the schema in [Plugin Guide](plugins.md)
2. Sign it: `python3 scripts/sign_plugin.py sign --plugin plugins/my-tool.json`
3. Restart: `docker compose restart tools app`
4. The tool appears in the registry and is auto-installed on first use

### Plugin Structure

```json
{
  "id": "my-tool",
  "name": "My Tool",
  "version": "1.0.0",
  "category": "discovery",
  "description": "What it does",
  "metadata": { "ai_description": "...", "capabilities": [...] },
  "installation": { "method": "apt", "commands": [...] },
  "execution": { "command": "my-tool", "args_template": "{target} -o {output_file}" },
  "parsing": { "format": "json" },
  "signature": "..."
}
```

---

## Safety Mechanisms

1. **SafetySupervisor** — regex blocklist + LLM analysis of every command
2. **Anti-brute-force** — blocks rockyou.txt, large wordlists, file-based credential lists
3. **Plugin signing** — Ed25519 signatures required in production
4. **Consensus voting** — multi-model validation for high-risk actions
5. **Container isolation** — all tools run in sandboxed Kali container
6. **Scope enforcement** — agents only target authorized hosts
