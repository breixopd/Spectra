# Spectra Roadmap

All planned features have been implemented. This document tracks what was built and potential future enhancements.

---

## Implemented Features

### Tier 1 — High Impact
| # | Feature | Status | Module |
|---|---------|--------|--------|
| 1 | Live tool output streaming | ✅ | `app/services/tools/streaming.py` |
| 2 | Scan profiles / presets | ✅ | `app/services/mission/presets.py` |
| 3 | Finding deduplication | ✅ | `app/services/mission/mission.py` |
| 4 | Grounding + playbooks wired | ✅ | `tool_service.py`, `tool_selector.py`, `exploit_crafter.py` |
| 5 | Model routing / fallback | ✅ | `app/services/ai/router.py` (LiteLLM) |
| 6 | Parallel tool execution | ✅ | `app/services/mission/manager/execution.py` |

### Tier 2 — Medium Impact
| # | Feature | Status | Module |
|---|---------|--------|--------|
| 7 | HTML report generation | ✅ | `app/services/mission/report_generator.py` |
| 8 | Exploit demo recording | ✅ | `app/services/mission/demo_recorder.py` |
| 9 | CVE database integration | ✅ | `app/services/ai/cve_intel.py` |
| 10 | Webhook notifications | ✅ | `app/services/notifications.py` |
| 11 | Smart context-aware wordlists | ✅ | `app/services/ai/wordlists.py` |

### Tier 3 — Differentiators
| # | Feature | Status | Module |
|---|---------|--------|--------|
| 12 | Attack graph visualization | ✅ | `app/static/js/dashboard.js` (Cytoscape.js) |
| 13 | MITRE ATT&CK mapping | ✅ | `app/services/ai/mitre_attack.py` |
| 14 | AI debrief agent | ✅ | `app/services/ai/agents/debrief.py` |
| 15 | Adversary simulation playbooks | ✅ | `app/services/ai/adversary_playbooks.py` |
| 16 | Exploit chain builder | ✅ | `app/services/mission/chain_builder.py` |
| 17 | Target diff / change detection | ✅ | `app/services/mission/target_diff.py` |
| 18 | Offline / air-gapped mode | ✅ | `app/services/ai/offline.py` |

### Architecture Optimizations
| Optimization | Status | Module |
|-------------|--------|--------|
| ARQ connection pooling | ✅ | `app/core/optimizations.py` |
| Lazy model loading | ✅ | `app/core/optimizations.py` |
| Tool result caching | ✅ | `app/core/optimizations.py` |
| Prompt token budgeting | ✅ | `app/core/optimizations.py` |
| Graceful degradation | ✅ | `app/core/optimizations.py` + `app/services/ai/offline.py` |

---

## Future Enhancements

Ideas for future development:

- **Scheduled recurring scans** with diff comparison
- **Browser-based exploit verification** using Playwright
- **Custom CVE feed ingestion** from NVD JSON API
- **Report PDF export** via WeasyPrint
- **Attack graph 3D visualization** using Three.js
- **Voice-controlled missions** via Whisper API
- **Mobile companion app** for monitoring missions remotely
