"""
Shared constants for the Spectra platform.

All values that might need to be changed over time — external URLs, timeouts,
limits, intervals, magic numbers — live here so they are easy to find and update.

Organisation:
  External URLs & APIs  — third-party endpoints, ordered by service group
  Exploit Intelligence  — MSF / KEV / EPSS / NVD / ExploitDB settings
  HTTP & Networking     — timeouts, retries, socket config
  WebSocket             — WS-specific limits
  Worker / Job Queue    — PostgreSQL-backed job worker settings
  Background Tasks      — maintenance task intervals
  Caching & State       — TTLs, key prefixes, state-store config
  Mission Engine        — concurrency, limits, timeouts
  API                   — pagination, rate limits, bulk limits
  Security              — token blacklist, encryption params
  Docker / Sandboxing   — image references, build settings
  Wordlists             — SecLists URLs and directory paths
  GeoIP                 — geolocation service settings
  Reporting / Debrief   — report-generation limits
  Memory system         — agent memory limits
  Feature labels        — human-readable plan feature names
  Data directory layout — runtime data path roots (relative to DATA_ROOT)
"""

from __future__ import annotations

import os

# ===========================================================================
# External URLs & APIs
# ===========================================================================

# --- Exploit Intelligence ---------------------------------------------------

#: Metasploit module metadata index (rapid7/metasploit-framework on GitHub).
MSF_METADATA_URL: str = (
    "https://raw.githubusercontent.com/rapid7/metasploit-framework/master/db/modules_metadata_base.json"
)

#: CISA Known Exploited Vulnerabilities catalog.
CISA_KEV_URL: str = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

#: EPSS (Exploit Prediction Scoring System) API — first.org.
EPSS_API_URL: str = "https://api.first.org/data/v1/epss"

#: NVD CVE API v2.0 base URL.
NVD_API_BASE_URL: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# --- Wordlists (SecLists on GitHub) ----------------------------------------

#: Base URL for the danielmiessler/SecLists raw content on GitHub.
SECLISTS_BASE_URL: str = "https://raw.githubusercontent.com/danielmiessler/SecLists/master"

#: Common web directory / file paths (~4,600 entries).
SECLISTS_COMMON_WEB_URL: str = f"{SECLISTS_BASE_URL}/Discovery/Web-Content/common.txt"

#: Top usernames for brute-force testing (~8,900 entries).
SECLISTS_TOP_USERNAMES_URL: str = f"{SECLISTS_BASE_URL}/Usernames/top-usernames-shortlist.txt"

#: Top 1,000 most common passwords.
SECLISTS_COMMON_PASSWORDS_URL: str = f"{SECLISTS_BASE_URL}/Passwords/Common-Credentials/top-1000.txt"

#: Top 5,000 subdomains for DNS enumeration.
SECLISTS_SUBDOMAINS_TOP5000_URL: str = f"{SECLISTS_BASE_URL}/Discovery/DNS/subdomains-top1million-5000.txt"

# --- GeoIP -----------------------------------------------------------------

#: ipwho.is free GeoIP API — returns JSON for ``GET /ipwho.is/<ip>``.
GEOIP_API_URL: str = "https://ipwho.is"

# --- Docker images ---------------------------------------------------------

#: Base image for the golden tools container build (mirrors deploy/docker/Dockerfile.worker).
SANDBOX_BASE_IMAGE: str = "kalilinux/kali-rolling:latest"

# ===========================================================================
# Time Conversion
# ===========================================================================

#: Seconds in one hour.
SECONDS_PER_HOUR: int = 3_600

#: Seconds in one day.
SECONDS_PER_DAY: int = 86_400

#: Seconds in one week.
SECONDS_PER_WEEK: int = 604_800

# ===========================================================================
# HTTP & Networking
# ===========================================================================

#: Timeout (seconds) for external data downloads (MSF, KEV, EPSS, NVD…).
EXTERNAL_HTTP_TIMEOUT: float = 30.0

#: Timeout (seconds) for GeoIP lookups.
GEOIP_TIMEOUT: float = 5.0

#: Default retry count for internal HTTP gateway clients.
HTTP_CLIENT_MAX_RETRIES: int = 3

#: Exponential-backoff base (seconds) for gateway client retries.
HTTP_CLIENT_RETRY_BACKOFF: float = 0.5

#: Default HTTP client timeout in seconds (internal services).
HTTP_CLIENT_TIMEOUT: int = 30

#: Webhook delivery max retries.
WEBHOOK_MAX_RETRIES: int = 3

#: TCP receive-buffer size for shell session sockets (bytes).
SHELL_SOCKET_RECV_BYTES: int = 4096

#: Default callback port for reverse shells.
SHELL_CALLBACK_PORT_START: int = 4444

#: End of callback port range for reverse shells.
SHELL_CALLBACK_PORT_END: int = 4500

#: WebSocket keepalive ping interval (seconds).
WS_KEEPALIVE_INTERVAL: int = 30

# ===========================================================================
# WebSocket
# ===========================================================================

#: Maximum messages per second from a single WebSocket connection.
WS_MAX_MESSAGES_PER_SECOND: int = 10

#: Maximum WebSocket message size in bytes (64 KB).
WS_MAX_MESSAGE_SIZE: int = 65536

# ===========================================================================
# Worker / Job Queue  (PostgreSQL-backed)
# ===========================================================================

#: Default queue name for the tools worker.
WORKER_DEFAULT_QUEUE: str = "default"

#: Maximum concurrent jobs in the tools worker.
WORKER_MAX_JOBS: int = 10

#: Default job timeout in seconds (10 minutes).
WORKER_JOB_TIMEOUT: int = 600

#: How long (seconds) job results are kept in the queue table (1 hour).
WORKER_KEEP_RESULT: int = 3600

#: Interval (seconds) between worker health-checks.
WORKER_HEALTH_CHECK_INTERVAL: int = 30

# ===========================================================================
# Background Tasks
# ===========================================================================

#: How often (seconds) the cache-cleanup background task runs (10 min).
CACHE_CLEANUP_INTERVAL: int = 600

#: How often (seconds) the system-cleanup background task runs (1 hour).
SYSTEM_CLEANUP_INTERVAL: int = 3600

# ===========================================================================
# Caching & State
# ===========================================================================

#: Refresh interval for the in-process exploit database (7 days).
EXPLOIT_DB_REFRESH_INTERVAL: int = 604_800

#: Cache TTL for EPSS scores (24 hours).
EPSS_CACHE_TTL: int = 86_400

#: Cache TTL for NVD CVE results (24 hours).
CVE_CACHE_TTL: int = 86_400

#: Seconds to wait between NVD API requests without an API key (5 req / 30 s).
NVD_RATE_LIMIT_DELAY: float = 6.5

#: Seconds to wait between NVD API requests with an API key (50 req / 30 s).
NVD_RATE_LIMIT_DELAY_WITH_KEY: float = 0.6

#: Key prefix for exploit-DB entries in the CacheEntry table.
EXPLOIT_DB_CACHE_KEY_PREFIX: str = "exploit_db:"

#: Key prefix for mission state in the SystemCache table.
MISSION_STATE_KEY_PREFIX: str = "mission_state:"

#: Minutes before an inactive mission state record is auto-cleaned (2 hours).
MISSION_STATE_TTL_MINUTES: int = 120

# ===========================================================================
# Mission Engine
# ===========================================================================

#: Maximum number of missions running simultaneously (system-wide safety cap).
MAX_CONCURRENT_MISSIONS: int = 10

#: Maximum replans per mission to prevent infinite loops.
MAX_REPLANS_PER_MISSION: int = 3

#: Maximum number of attack-vector iterations before giving up.
MAX_EXPLOIT_ITERATIONS: int = 20

#: Maximum characters of exploit output to log inline.
EXPLOIT_OUTPUT_LOG_CHARS: int = 300

#: Mission-level timeout in seconds (1 hour).
MISSION_TIMEOUT_SECONDS: int = 3600

#: Maximum number of credentials stored per mission.
MAX_CREDENTIALS_PER_MISSION: int = 100

#: Maximum auto-chain depth to prevent infinite chaining.
MAX_CHAIN_DEPTH: int = 10

#: Maximum scope hosts from a CIDR range.
MAX_HOSTS_DEFAULT: int = 256

#: Default tool execution timeout (seconds).
TOOL_DEFAULT_TIMEOUT: int = 300

#: Extra seconds added to tool timeout for queue/dispatch overhead.
TOOL_JOB_BUFFER_TIMEOUT: int = 60

#: Timeout for tool installation jobs (seconds).
TOOL_INSTALL_TIMEOUT: int = 600

#: Maximum concurrent tool executions per ToolExecutionService instance.
TOOL_MAX_CONCURRENCY: int = 8

#: Maximum tool execution retries on transient failure.
TOOL_MAX_RETRIES: int = 2

#: Maximum stdout characters kept from a single tool run.
TOOL_MAX_STDOUT_CHARS: int = 3000

#: Maximum stderr characters kept from a single tool run.
TOOL_MAX_STDERR_CHARS: int = 500

#: Timeout (seconds) for compiling a Go exploit script.
GO_COMPILE_TIMEOUT: int = 60

# ===========================================================================
# API
# ===========================================================================

#: Default page size for list endpoints.
API_DEFAULT_PAGE_SIZE: int = 20

#: Maximum page size for list endpoints.
API_MAX_PAGE_SIZE: int = 100

#: Maximum CVE results returned per lookup.
CVE_RESULTS_LIMIT: int = 50

#: Maximum events/traces returned by observability endpoints.
OBSERVABILITY_MAX_RESULTS: int = 500

#: Default API rate limit string (slowapi / redis-throttle format).
#: Override via API_RATE_LIMIT env var in test or high-traffic environments.
API_RATE_LIMIT: str = os.environ.get("API_RATE_LIMIT", "120/minute")

#: Maximum findings IDs in a single bulk-status-update request.
MAX_BULK_FINDINGS: int = 100

#: Maximum rows returned by data export endpoints.
MAX_EXPORT_ROWS: int = 10_000

# ===========================================================================
# Security
# ===========================================================================

#: Maximum number of entries in the in-process JWT blacklist.
JWT_BLACKLIST_MAX_SIZE: int = 10_000

#: PBKDF2 salt length (bytes) for password-based export encryption. RFC 8018 §4.
PBKDF2_SALT_LENGTH: int = 16

# ===========================================================================
# Docker / Sandboxing
# ===========================================================================

# SANDBOX_BASE_IMAGE is defined under External URLs & APIs above.

# ===========================================================================
# Wordlists
# ===========================================================================

#: Relative path (from project root) of the shared wordlists directory.
WORDLISTS_DIR: str = "wordlists"

# ===========================================================================
# Reporting / Debrief
# ===========================================================================

#: Maximum number of findings passed to the debrief agent.
DEBRIEF_MAX_FINDINGS: int = 30

#: Maximum number of log lines passed to the debrief agent.
DEBRIEF_MAX_LOGS: int = 50

#: Maximum characters of the debrief executive summary to log inline.
DEBRIEF_SUMMARY_LOG_CHARS: int = 200

# ===========================================================================
# Memory system
# ===========================================================================

#: Maximum tool lessons kept in agent memory.
MEMORY_MAX_TOOL_LESSONS: int = 500

#: Maximum exploit lessons kept in agent memory.
MEMORY_MAX_EXPLOIT_LESSONS: int = 200

# ===========================================================================
# Feature labels  — human-readable names for plan feature keys
# ===========================================================================

FEATURE_LABELS: dict[str, str] = {
    "api_access": "API Access",
    "byok": "BYOK (Bring Your Own Key)",
    "vpn": "VPN Support",
    "vpn_support": "VPN Support",
    "cve_browser": "CVE Browser",
    "shell_access": "Shell Access",
    "custom_plugins": "Custom Plugins",
    "priority_support": "Priority Support",
    "advanced_reporting": "Advanced Reporting",
    "team_collaboration": "Team Collaboration",
    "manual_mode": "Manual Mode",
    "sso": "SSO Integration",
    "sla": "SLA Guarantee",
    "dedicated_support": "Dedicated Support",
}


def format_feature_label(key: str) -> str:
    """Format a feature key into a human-readable label with proper capitalisation."""
    return FEATURE_LABELS.get(key, key.replace("_", " ").title())


# ===========================================================================
# Data directory layout  — paths relative to settings.DATA_ROOT
# ===========================================================================

DATA_DIR: str = "data"
DATA_CONFIG_DIR: str = "data/config"
DATA_MISSIONS_DIR: str = "data/missions"
DATA_SESSIONS_DIR: str = "data/sessions"
DATA_CACHE_DIR: str = "data/cache"
DATA_AUTH_DIR: str = "data/auth"
