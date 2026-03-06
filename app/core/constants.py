"""
Shared constants for the Spectra platform.

Centralizes magic numbers and fixed string values to a single place
so they are easy to locate and change.
"""

# ---------------------------------------------------------------------------
# ARQ task queue
# ---------------------------------------------------------------------------

#: Name of the ARQ Redis queue used by the tools worker.
ARQ_QUEUE_NAME: str = "spectra:tasks"

# ---------------------------------------------------------------------------
# Scope / network scanning
# ---------------------------------------------------------------------------

#: Maximum number of hosts that will be included from a CIDR range.
MAX_HOSTS_DEFAULT: int = 256

# ---------------------------------------------------------------------------
# Exploitation engine
# ---------------------------------------------------------------------------

#: Maximum number of attack-vector iterations before giving up.
MAX_EXPLOIT_ITERATIONS: int = 20

#: Maximum characters of exploit output to log inline.
EXPLOIT_OUTPUT_LOG_CHARS: int = 300

# ---------------------------------------------------------------------------
# ARQ worker settings
# ---------------------------------------------------------------------------

#: Maximum concurrent ARQ jobs in the tools worker.
ARQ_MAX_JOBS: int = 10

#: Default ARQ job timeout in seconds (10 minutes).
ARQ_JOB_TIMEOUT: int = 600

#: How long (seconds) ARQ keeps job results in Redis (1 hour).
ARQ_KEEP_RESULT: int = 3600

#: Interval (seconds) between ARQ worker health-checks.
ARQ_HEALTH_CHECK_INTERVAL: int = 30

# ---------------------------------------------------------------------------
# Redis / networking
# ---------------------------------------------------------------------------

#: Interval (seconds) for Redis client health-checks.
REDIS_HEALTH_CHECK_INTERVAL: int = 30

#: TCP receive-buffer size for shell session sockets (bytes).
SHELL_SOCKET_RECV_BYTES: int = 4096

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
API_DEFAULT_PAGE_SIZE: int = 50

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
