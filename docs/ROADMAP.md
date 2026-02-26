# Spectra Roadmap

Single-operator autonomous pentesting platform. Prioritized by impact and effort.

---

## Tier 1 — High Impact, Low-Medium Effort

### 1. Live Tool Output Streaming
**Impact: Very High | Effort: Medium**

Currently tool output only appears after the tool finishes. Stream stdout/stderr via WebSocket in real-time so you can watch nmap scanning, nuclei finding vulns, etc. live in the terminal.

Implementation: In the ARQ worker, pipe subprocess stdout line-by-line to Redis pub/sub. App container subscribes and pushes to WebSocket. Dashboard terminal already handles `onSocketMessage`.

### 2. Scan Profiles / Presets
**Impact: High | Effort: Low**

One-click profiles instead of typing directives:
- **Quick Recon** — nmap fast scan + nuclei top templates (5 min)
- **Full Assessment** — all phases, all tools (30+ min)
- **Web Only** — nikto + ffuf + nuclei web + sqlmap (15 min)
- **Stealth** — slow timing, passive first, no brute force
- **Exploitation Focus** — skip recon, go straight to exploit phase

Implementation: Dropdown on the dashboard command bar. Each profile sets a predefined directive + stealth_mode + skip_phases.

### 3. Finding Deduplication
**Impact: High | Effort: Low**

The DVWA live test produced 38 findings but many were duplicates (same `http-missing-security-headers` for different headers). Deduplicate by:
- CVE ID (exact match)
- Template ID + host (nuclei)
- Port + service combo (nmap)

Show count of occurrences instead of repeated entries.

### 4. Integrate Grounding + Playbooks into Pipeline
**Impact: High | Effort: Medium**

The `grounding.py` and `playbook.py` modules are built but not wired into the execution pipeline yet. Wire them:
- After each tool run, call `validate_tool_output()` and log evidence quality
- Feed `GroundedContext.get_evidence_summary()` into agent prompts instead of raw service lists
- Use `PlaybookEngine.get_recommended_tools()` as a fallback when LLM tool selection fails
- Call `extract_evidence_snippets()` and include in the next agent's prompt

### 5. Model Routing / Fallback Chain
**Impact: High | Effort: Low**

Use cheap/fast model for routine tasks, expensive model for hard ones:
- Tool selection, scope parsing → small model (qwen 3B, gpt-4o-mini)
- Exploit crafting, POC generation, report writing → larger model (gpt-4o, claude)
- If small model fails 2x → auto-escalate to larger model

Implementation: Add `model_override` per agent role in settings. The `LLMClient` factory already supports multiple providers.

### 6. Parallel Tool Execution
**Impact: High | Effort: Medium**

Run independent tools simultaneously instead of sequentially. The ARQ worker already supports `max_jobs=10`. Just enqueue multiple jobs and `await asyncio.gather()`:
- Discovery phase: nmap + naabu + amass in parallel
- Enumeration: gobuster + ffuf in parallel
- Each tool's findings merge into the shared attack surface

---

## Tier 2 — Medium Impact, Medium Effort

### 7. PDF/HTML Report Generation
**Impact: Medium | Effort: Medium**

Current reports are Markdown. Add:
- HTML report with interactive charts (finding severity pie chart, timeline)
- PDF export via WeasyPrint or wkhtmltopdf
- Executive summary (1 page, no jargon) + technical details
- Jinja2 report templates that users can customize

### 8. Exploit Demo Recording (asciinema)
**Impact: Medium | Effort: Medium**

When `record_demo=True`:
1. Wrap each tool command with `asciinema rec --command "..." step_N.cast`
2. After mission, concatenate .cast files
3. Serve via embedded asciinema-player at `/missions/{id}/demo`
4. Optional: convert to GIF/MP4 via `agg`

The `record_demo` field is already in `StartMissionRequest`.

### 9. CVE Database Integration
**Impact: Medium | Effort: Medium**

Download NVD JSON feeds, index into a local SQLite DB. When nmap finds `Apache 2.4.25`, auto-lookup matching CVEs without needing the LLM to know them. Feed exact CVE IDs into exploit selection prompts.

Eliminates a major hallucination source — LLMs often invent plausible-sounding CVE IDs.

### 10. Webhook / ntfy.sh Notifications
**Impact: Medium | Effort: Low**

Push mission events to ntfy.sh, Slack, Discord, or any webhook URL:
- Mission started/completed/failed
- Critical vulnerability found
- Exploitation successful
- Configurable in settings page

### 11. Smart Context-Aware Wordlists
**Impact: Medium | Effort: Low**

Generate custom wordlists using LLM based on target context:
- Company name variations, employee names from OSINT
- Technology-specific paths (e.g., WordPress → `/wp-admin`, `/xmlrpc.php`)
- Industry-specific terms

Feed into ffuf/gobuster/hydra instead of generic wordlists.

---

## Tier 3 — Differentiators

### 12. Attack Graph Visualization
Real-time Cytoscape.js graph showing the full attack path: initial scan → service discovery → vuln found → exploit attempt → shell access → pivot. Each node is a host/service, edges show the attack flow with success/fail colors. Already have Cytoscape loaded in the dashboard.

### 13. MITRE ATT&CK Mapping
Tag each tool/technique with its ATT&CK TTP ID automatically. Generate an ATT&CK Navigator JSON that can be loaded into the official Navigator tool to see coverage heatmap. Useful for compliance and purple team exercises.

### 14. AI Debrief Agent
After mission completion, a `DebriefAgent` analyzes the full mission log and generates:
- What worked and what didn't
- What a human pentester would have done differently
- Specific remediation recommendations for each finding
- Risk prioritization based on business context

### 15. Adversary Simulation Playbooks
Pre-built attack playbooks that mimic specific threat actors:
- APT28 (Fancy Bear): spearphishing → lateral movement → data exfil
- FIN7: web app exploitation → POS malware deployment
- Lazarus Group: supply chain → cryptomining

Each playbook is a JSON file with ordered steps, tools, and TTPs.

### 16. Exploit Chain Builder
Enhanced version of the Pipeline editor specifically for multi-stage attacks:
- Visual flow: `Exploit Web App → Get Shell → Dump Creds → Pivot to Internal → Exfil Data`
- Each stage has success criteria (regex match on output)
- Automatic fallback paths (if exploit A fails, try exploit B)
- Shareable as JSON files

### 17. Target Diff / Change Detection
Compare scan results across runs. Show what changed:
- New ports opened since last scan
- New services deployed
- Vulnerabilities patched vs new ones introduced
- Useful for continuous monitoring

### 18. Offline / Air-Gapped Mode
Full functionality without internet:
- Local Ollama models (already supported)
- Local CVE database (SQLite)
- Bundled wordlists (seclists already in tools container)
- No CDN dependencies (bundle Tailwind, fonts, icons)

---

## Architecture Optimizations

### Already Built
- ✅ Grounding framework (`grounding.py`) — tool output validation, evidence extraction, confidence tracking
- ✅ Playbook system (`playbook.py`) — deterministic service→tool mapping, success pattern learning
- ✅ Manual Mode — direct tool execution without LLM
- ✅ Pipeline editor — chain tools visually
- ✅ Safety Supervisor — blocks dangerous commands
- ✅ K-threshold consensus at 5 quality gates
- ✅ Dynamic temperature per agent role
- ✅ Plugin auto-install in tools container
- ✅ WebSocket real-time updates

### Suggested Optimizations
1. **Connection pooling for ARQ** — reuse Redis connections instead of creating new pool per tool execution
2. **Lazy model loading** — don't load sentence-transformers embedding model until RAG is actually used
3. **Tool result caching** — cache nmap scan results for 5 min to avoid duplicate scans during plan adaptation
4. **Prompt token budgeting** — track token usage per mission, warn when approaching limits
5. **Graceful degradation** — if LLM provider is down, fall back to playbook-only mode (no AI, just run the playbook steps sequentially)

---

## Removed from Roadmap (Single-User)
- ~~Role-based access control~~ — single operator, not needed
- ~~Collaborative mode~~ — no multi-user
- ~~Plugin marketplace~~ — just drop JSON files into `plugins/`
- ~~Scheduled scans~~ — can be done with cron externally
- ~~Multi-target campaigns~~ — can run missions sequentially
