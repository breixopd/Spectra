# Spectra Improvement Roadmap

## Agent Grounding, Reliability & Anti-Hallucination

### Current Architecture Strengths

The MAKER framework already provides solid foundations:
- **K-Threshold Voting** at 5 quality gates (PLAN, TOOL_SELECTION, PAYLOAD, REPLAN, EXECUTION)
- **Safety Supervisor** blocks dangerous commands before execution
- **Structured outputs** via Pydantic models with `json_repair` fallback
- **Dynamic temperature** per agent role (low for scope/safety, high for exploit creativity)
- **RAG knowledge base** for learning from past exploits

### Improvements to Implement

#### 1. Output Verification Loop (Highest Impact)

Currently agents trust tool output at face value. Add a verification step:

```
Tool runs → Output parsed → VerificationAgent checks output →
  If output makes sense for the tool/target → Accept
  If output is empty/garbled/suspicious → Flag for retry or alternate tool
```

Implementation: In `MissionExecutor.execute_task()`, after tool execution, run a lightweight verification prompt that asks: "Does this output look like valid {tool_name} output against {target_type}? Is this a false positive?" This catches tool misconfigurations and LLM hallucinations about findings.

#### 2. Fact-Grounded Prompting

Every agent prompt should include **concrete evidence** from previous steps, not summaries. Current prompts use `services_info` and `vulns_info` strings. Enhance to include:
- Raw nmap output snippets (first 500 chars)
- Exact port/version strings from parsing
- Exact CVE IDs from Nuclei/Nikto

This prevents the LLM from inventing services or versions that don't exist.

#### 3. Tool Output Assertion Framework

Add assertion checks in the parser that validate tool output against known patterns:

```python
TOOL_OUTPUT_VALIDATORS = {
    "nmap": lambda output: "<nmaprun" in output or "Nmap scan report" in output,
    "nuclei": lambda output: '"template-id"' in output or "[INF]" in output,
    "sqlmap": lambda output: "sqlmap" in output.lower(),
}
```

If a tool's output doesn't match its expected pattern, the finding is marked `unverified` and the agent is told to retry or skip.

#### 4. Confidence Decay

Track confidence through the pipeline. A finding discovered by a tool (confidence: 0.9) that's validated by consensus (0.85) but fails manual verification drops to 0.3. Only findings above threshold appear in the final report.

#### 5. Chain-of-Thought Audit Trail

Force all agents to include `reasoning_steps` (list of strings) in their output. Each step must reference concrete data:

```json
{
  "reasoning_steps": [
    "Nmap found port 80 running Apache 2.4.41",
    "Apache 2.4.41 has known CVE-2021-41773 (path traversal)",
    "Nuclei confirmed CVE-2021-41773 with 200 response",
    "Attempting exploitation via curl path traversal"
  ]
}
```

This creates an auditable chain and forces the model to ground each step in evidence.

#### 6. Pivoting & Attack Chaining

Current `PostExploitationAgent` plans but doesn't execute. To enable real pivoting:

- **Network pivot detection**: After gaining a shell, run `ip addr`, `arp -a`, `netstat -an` to discover internal networks
- **Session management**: Track multiple active sessions across hosts
- **Credential harvesting**: Parse `/etc/shadow`, browser creds, SSH keys from compromised hosts
- **Lateral movement tasks**: Auto-generate tasks to attack newly discovered internal hosts

Implementation: Add a `PivotAgent` that takes shell access as input, enumerates the compromised host, and generates new `Task` objects targeting internal hosts.

#### 7. POC Code Quality Gates

The `POCDeveloperAgent` generates exploit code but has no quality check. Add:

1. **Static analysis**: Run `pylint`/`ruff` on generated Python code before execution
2. **Sandbox test**: Execute in an isolated container first with a timeout
3. **Output validation**: Check that the script actually produces the expected `[+] Exploit Successful` marker
4. **Consensus validation**: POC code goes through PAYLOAD quality gate

---

## Video Demo Recording

### Feasibility: Medium (Achievable with current architecture)

#### Approach

The tools container already runs commands via `asyncio.create_subprocess_shell`. A video demo would:

1. **Record terminal sessions** using `script` or `asciinema` (lightweight, text-based recording)
2. **Convert to video** using `asciinema` + `svg-term` or `termtosvg` for animated SVGs
3. **Trigger recording** when `record_demo=True` in the mission request

#### Implementation Plan

1. Add `asciinema` to the tools container Dockerfile
2. Wrap tool execution commands in `asciinema rec --command "..." output.cast`
3. After mission completion, concatenate `.cast` files into a single recording
4. Store recordings in `reports/missions/{mission_id}/demo.cast`
5. Add a playback endpoint that serves an embedded `asciinema-player`
6. For video export: use `agg` (asciinema gif generator) to create MP4/GIF

#### Alternative: Browser-based recording

Since Spectra has a web UI with Xterm.js terminal:
- Use the `MediaRecorder` API in the browser to record the terminal output area
- Stream all tool output through WebSocket to the terminal
- Record the DOM canvas as the mission runs
- Save as WebM/MP4 on the client side

The `record_demo` boolean field has already been added to `StartMissionRequest`.

---

## Improvements & Feature Ideas

### High Priority

| Feature | Impact | Effort | Description |
|---------|--------|--------|-------------|
| **Tool output streaming** | High | Medium | Stream tool stdout via WebSocket in real-time instead of waiting for completion. Show live nmap/nuclei output in the terminal. |
| **Scan profiles** | High | Low | Preset profiles: "Quick Recon" (nmap fast + nuclei), "Full Assessment" (all phases), "Web Only" (nikto + ffuf + nuclei web), "Stealth" (slow, passive first). |
| **Finding deduplication** | High | Low | Deduplicate findings by CVE/port/service before reporting. Current system can log the same vuln multiple times. |
| **Scheduled scans** | Medium | Medium | Cron-like scheduling for recurring assessments. Compare results across runs to detect new vulns. |
| **Multi-target campaigns** | Medium | Medium | Scan multiple targets in parallel as a single campaign with aggregated reporting. |

### Medium Priority

| Feature | Impact | Effort | Description |
|---------|--------|--------|-------------|
| **Report templates** | Medium | Medium | PDF/HTML report generation with executive summary, technical details, risk matrix, remediation. Use Jinja2 templates + WeasyPrint for PDF. |
| **CVE database integration** | Medium | Medium | Ingest NVD/CVE JSON feeds into RAG. Auto-correlate discovered service versions with known CVEs. |
| **Plugin marketplace** | Medium | High | Community-contributed plugins. Signed, versioned, with auto-update. GitHub-backed or self-hosted. |
| **Role-based access** | Medium | Medium | Beyond superuser: viewer (read reports), operator (run scans), admin (manage settings). |
| **Webhook notifications** | Low | Low | Send mission events to Slack, Discord, email, or custom webhooks. |

### Architecture Improvements

| Feature | Impact | Effort | Description |
|---------|--------|--------|-------------|
| **Agent memory** | High | Medium | Long-term memory across missions. "Last time I scanned this network, I found X". Uses RAG with mission-scoped embeddings. |
| **Model routing** | Medium | Medium | Use different LLM models for different tasks: fast/small for tool selection, large/capable for exploit crafting. Route by task complexity. |
| **Parallel tool execution** | High | Medium | Run independent tools in parallel (e.g., nmap and amass simultaneously). Currently sequential. |
| **Retry with escalation** | Medium | Low | If a small model fails at a task 3 times, escalate to a larger model. Fallback chain: local 3B → local 7B → cloud API. |
| **Offline mode** | Medium | Medium | Full functionality without internet using local Ollama models, local CVE database, and offline wordlists. |

### Differentiators (What Would Make This Stand Out)

1. **Attack Graph Visualization**: Real-time Cytoscape.js graph showing the attack path from initial access → privilege escalation → lateral movement → data exfiltration. Each node is a host/service, edges are attack vectors with success/fail indicators.

2. **AI Debrief**: After mission completion, an AI agent generates a "lessons learned" analysis: what worked, what didn't, what a human pentester would have done differently, and how to improve defenses.

3. **Compliance Mapping**: Map findings to compliance frameworks (PCI-DSS, HIPAA, SOC2, NIST). Auto-generate compliance-ready reports.

4. **MITRE ATT&CK Mapping**: Tag each exploit/technique with its ATT&CK TTP ID. Generate ATT&CK Navigator heatmap showing coverage.

5. **Collaborative Mode**: Multiple operators can watch the same mission in real-time, steer together, and annotate findings. Think "Google Docs for pentesting".

6. **Adversary Simulation Playbooks**: Pre-built attack playbooks that simulate specific threat actors (APT28, FIN7, etc.) using their known TTPs. Useful for purple team exercises.

7. **Smart Wordlists**: Generate context-aware wordlists based on target info (company name, industry, discovered tech stack) using LLM. Feed into brute-force tools.

8. **Exploit Chain Builder**: Visual editor (like the pipeline we built) but specifically for multi-stage exploits: "Exploit web app → get shell → dump creds → pivot to DB → exfil data". Each stage has success criteria and fallback paths.
