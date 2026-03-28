"""
Shared constants for the Spectra platform.

Centralizes magic numbers and fixed string values to a single place
so they are easy to locate and change.
"""

# ---------------------------------------------------------------------------
# Task queue
# ---------------------------------------------------------------------------

#: Default queue name for the tools worker (PG-backed job queue).
WORKER_DEFAULT_QUEUE: str = "default"

# ---------------------------------------------------------------------------
# Scope / network scanning
# ---------------------------------------------------------------------------

#: Maximum number of hosts that will be included from a CIDR range.
MAX_HOSTS_DEFAULT: int = 256

# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

#: Maximum number of missions running simultaneously (system-wide safety cap).
#: Per-user limits are enforced via Plan.max_concurrent_missions in
#: app.api.dependencies.check_mission_limit — this global cap prevents overload.
MAX_CONCURRENT_MISSIONS: int = 10

#: Maximum replans per mission to prevent infinite loops.
MAX_REPLANS_PER_MISSION: int = 3

# ---------------------------------------------------------------------------
# Exploitation engine
# ---------------------------------------------------------------------------

#: Maximum number of attack-vector iterations before giving up.
MAX_EXPLOIT_ITERATIONS: int = 20

#: Maximum characters of exploit output to log inline.
EXPLOIT_OUTPUT_LOG_CHARS: int = 300

#: Mission-level timeout in seconds (1 hour default).
MISSION_TIMEOUT_SECONDS: int = 3600

# ---------------------------------------------------------------------------
# Worker settings (PostgreSQL-backed job queue)
# ---------------------------------------------------------------------------

#: Maximum concurrent jobs in the tools worker.
WORKER_MAX_JOBS: int = 10

#: Default job timeout in seconds (10 minutes).
WORKER_JOB_TIMEOUT: int = 600

#: How long (seconds) job results are kept (1 hour).
WORKER_KEEP_RESULT: int = 3600

#: Interval (seconds) between worker health-checks.
WORKER_HEALTH_CHECK_INTERVAL: int = 30

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

#: TCP receive-buffer size for shell session sockets (bytes).
SHELL_SOCKET_RECV_BYTES: int = 4096

#: Default callback port for reverse shells.
SHELL_CALLBACK_PORT_START: int = 4444

#: End of callback port range for reverse shells.
SHELL_CALLBACK_PORT_END: int = 4500

# ---------------------------------------------------------------------------
# Script compilation / execution
# ---------------------------------------------------------------------------

#: Timeout (seconds) for compiling a Go exploit script.
GO_COMPILE_TIMEOUT: int = 60

# ---------------------------------------------------------------------------
# Debrief / reporting
# ---------------------------------------------------------------------------

#: Maximum number of findings passed to the debrief agent.
DEBRIEF_MAX_FINDINGS: int = 30

#: Maximum number of log lines passed to the debrief agent.
DEBRIEF_MAX_LOGS: int = 50

#: Maximum characters of the debrief executive summary to log inline.
DEBRIEF_SUMMARY_LOG_CHARS: int = 200

# ---------------------------------------------------------------------------
# API pagination / limits
# ---------------------------------------------------------------------------

#: Default page size for list endpoints.
API_DEFAULT_PAGE_SIZE: int = 20

#: Maximum page size for list endpoints.
API_MAX_PAGE_SIZE: int = 100

#: Maximum CVE results returned per lookup.
CVE_RESULTS_LIMIT: int = 50

#: Maximum events/traces returned by observability endpoints.
OBSERVABILITY_MAX_RESULTS: int = 500

# ---------------------------------------------------------------------------
# Memory system limits
# ---------------------------------------------------------------------------

#: Maximum tool lessons kept in memory.
MEMORY_MAX_TOOL_LESSONS: int = 500

#: Maximum exploit lessons kept in memory.
MEMORY_MAX_EXPLOIT_LESSONS: int = 200

# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------

#: Default API rate limit.
API_RATE_LIMIT: str = "100/minute"

# ---------------------------------------------------------------------------
# Exploit Database
# ---------------------------------------------------------------------------

#: URL for Metasploit module metadata (raw GitHub).
MSF_METADATA_URL: str = "https://raw.githubusercontent.com/rapid7/metasploit-framework/master/db/modules_metadata_base.json"

#: URL for CISA Known Exploited Vulnerabilities catalog.
CISA_KEV_URL: str = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

#: EPSS API base URL.
EPSS_API_URL: str = "https://api.first.org/data/v1/epss"

# ---------------------------------------------------------------------------
# Data directory layout
# ---------------------------------------------------------------------------

DATA_DIR: str = "data"
DATA_CONFIG_DIR: str = "data/config"
DATA_MISSIONS_DIR: str = "data/missions"
DATA_SESSIONS_DIR: str = "data/sessions"
DATA_CACHE_DIR: str = "data/cache"
DATA_AUTH_DIR: str = "data/auth"

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

#: Maximum messages per second from a single WebSocket connection.
WS_MAX_MESSAGES_PER_SECOND: int = 10

#: Maximum WebSocket message size in bytes (64 KB).
WS_MAX_MESSAGE_SIZE: int = 65536

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

#: Default retry count for HTTP gateway clients.
HTTP_CLIENT_MAX_RETRIES: int = 3

#: Default HTTP client timeout in seconds.
HTTP_CLIENT_TIMEOUT: int = 30

#: Webhook delivery max retries.
WEBHOOK_MAX_RETRIES: int = 3

# ---------------------------------------------------------------------------
# Feature labels — human-readable names for plan feature keys
# ---------------------------------------------------------------------------

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


#: Refresh interval for exploit database (7 days in seconds).
EXPLOIT_DB_REFRESH_INTERVAL: int = 604800

#: Cache TTL for EPSS scores (24 hours in seconds).
EPSS_CACHE_TTL: int = 86400
