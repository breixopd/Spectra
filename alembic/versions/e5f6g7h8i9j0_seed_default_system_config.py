"""Seed default system_config values for DB-backed configuration.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6g7h8i9j0"
down_revision = "d4e5f6g7h8i9"
branch_labels = None
depends_on = None

# Default values matching Settings class defaults. Secrets (JWT_SECRET_KEY etc.)
# are NOT seeded here — they are auto-generated and persisted by secret_bootstrap.
_DEFAULTS = [
    # (key, default_value, is_secret, description)
    ("APP_NAME", "Spectra", False, "Application name"),
    ("LOG_LEVEL", "INFO", False, "Logging level"),
    ("TENSORZERO_GATEWAY_URL", "http://tensorzero:3000", False, "TensorZero gateway URL"),
    ("TENSORZERO_API_KEY", "", True, "TensorZero API key"),
    ("LLM_TIMEOUT", "120", False, "LLM request timeout seconds"),
    ("EMBEDDING_MODEL", "local/BAAI/bge-small-en-v1.5", False, "Embedding model name"),
    ("EMBEDDING_API_KEY", "", True, "Embedding provider API key"),
    ("EMBEDDING_API_BASE_URL", "", False, "Embedding API base URL"),
    ("EXPLOIT_DB_AUTO_INIT", "true", False, "Auto-initialize exploit database at startup"),
    ("PLATFORM_DOMAIN", "", False, "Public platform domain"),
    ("PLATFORM_BASE_URL", "", False, "Full platform base URL"),
    ("PLATFORM_EXPOSED", "false", False, "Whether platform is internet-accessible"),
    ("MAINTENANCE_MODE", "false", False, "Enable maintenance mode"),
    ("MAINTENANCE_MESSAGE", "We're performing scheduled maintenance. Please check back shortly.", False, "Maintenance mode message"),
    ("CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000,http://localhost:5050,http://127.0.0.1:5050", False, "Allowed CORS origins (comma-separated)"),
    ("JWT_ALGORITHM", "HS256", False, "JWT signing algorithm"),
    ("ACCESS_TOKEN_EXPIRE_MINUTES", "240", False, "Access token expiry in minutes"),
    ("SESSION_IDLE_TIMEOUT_MINUTES", "60", False, "Session idle timeout in minutes"),
    ("PLUGIN_SAFE_MODE", "true", False, "Enforce plugin signature verification"),
    ("REQUIRE_APPROVAL", "false", False, "Require human approval for high-risk actions"),
    ("CONNECT_BACK_HOST", "spectra-app", False, "Connect-back host for shells"),
    ("DOCKER_REGISTRY", "ghcr.io/spectra", False, "Docker image registry"),
    ("SANDBOX_MAX_CONTAINERS", "10", False, "Max sandbox containers"),
    ("SANDBOX_MEMORY_LIMIT", "2g", False, "Default sandbox memory limit"),
    ("SANDBOX_CPU_SHARES", "512", False, "Default sandbox CPU shares"),
    ("SANDBOX_RESOURCE_TIERS", '{"light": {"memory": "512m", "cpu_shares": 256}, "medium": {"memory": "2g", "cpu_shares": 512}, "heavy": {"memory": "4g", "cpu_shares": 1024}, "extreme": {"memory": "8g", "cpu_shares": 2048}}', False, "Sandbox resource tier definitions (JSON)"),
    ("SANDBOX_MAX_LIFETIME", "7200", False, "Max sandbox lifetime seconds"),
    ("SANDBOX_NETWORK_ISOLATION", "true", False, "Enable sandbox network isolation"),
    ("SANDBOX_IDLE_TIMEOUT", "600", False, "Sandbox idle timeout seconds"),
    ("SANDBOX_HEARTBEAT_INTERVAL", "30", False, "Sandbox heartbeat interval seconds"),
    ("SANDBOX_PER_USER_LIMIT", "3", False, "Max concurrent sandboxes per user"),
    ("SANDBOX_DEFAULT_PRIORITY", "5", False, "Default sandbox job priority (1=highest)"),
    ("SANDBOX_OOM_ESCALATION_ENABLED", "true", False, "Auto-escalate resource tier on OOM"),
    ("SANDBOX_WARM_POOL_SIZE", "2", False, "Pre-warmed idle containers to maintain"),
    ("SANDBOX_AUTO_BUILD_IMAGE", "true", False, "Auto-rebuild golden image on plugin change"),
    ("SANDBOX_IMAGE_SCAN_ENABLED", "true", False, "Scan golden image after build"),
    ("SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL", "false", False, "Block deployment if critical CVEs found"),
    ("MCP_API_KEY", "", True, "MCP server API key"),
    ("AI_SERVICE_URL", "", False, "AI microservice URL"),
    ("SCHEDULER_SERVICE_URL", "http://scheduler:5011", False, "Scheduler service URL"),
    ("WORKER_SERVICE_URL", "http://worker:5012", False, "Worker service URL"),
    ("SANDBOX_ORCHESTRATOR_URL", "", False, "External sandbox orchestrator URL"),
    ("SANDBOX_ORCHESTRATOR_TIMEOUT", "30", False, "Sandbox orchestrator request timeout"),
    ("SANDBOX_ORCHESTRATOR_API_KEY", "", True, "Sandbox orchestrator API key"),
    ("SHELL_ROUTING_MODE", "direct", False, "Shell routing mode: direct, sandbox, or proxy"),
    ("SHELL_PROXY_NODES", "", False, "Proxy node URLs for shell routing (comma-separated)"),
    ("VPN_CONFIG_DIR", "/app/vpn_configs", False, "VPN configuration directory"),
    ("VPN_ENABLED", "true", False, "Enable VPN support"),
    ("VPN_AUTO_CONNECT", "", False, "Auto-connect VPN config (reserved)"),
    ("NOTIFICATION_WEBHOOK", "", False, "Notification webhook URL (e.g., ntfy.sh/topic)"),
    ("SMTP_HOST", "", False, "SMTP server host"),
    ("SMTP_PORT", "587", False, "SMTP server port"),
    ("SMTP_USER", "", False, "SMTP username"),
    ("SMTP_PASSWORD", "", True, "SMTP password"),
    ("SMTP_FROM", "", False, "SMTP from address"),
    ("SMTP_USE_TLS", "true", False, "Use TLS for SMTP"),
    ("EMAIL_VERIFICATION_ENABLED", "false", False, "Enable email verification"),
    ("S3_ENDPOINT_URL", "", False, "S3-compatible storage endpoint"),
    ("S3_ACCESS_KEY", "", True, "S3 access key"),
    ("S3_SECRET_KEY", "", True, "S3 secret key"),
    ("S3_REGION", "us-east-1", False, "S3 region"),
    ("S3_BUCKET_MISSIONS", "spectra-missions", False, "S3 bucket for missions"),
    ("S3_BUCKET_SESSIONS", "spectra-sessions", False, "S3 bucket for sessions"),
    ("S3_BUCKET_KNOWLEDGE", "spectra-knowledge", False, "S3 bucket for knowledge base"),
    ("S3_BUCKET_VPN", "spectra-sessions", False, "S3 bucket for VPN configs"),
    ("S3_BUCKET_BACKUPS", "spectra-backups", False, "S3 bucket for backups"),
    ("GARAGE_ADMIN_TOKEN", "", True, "Garage admin API token"),
    ("GARAGE_ADMIN_URL", "", False, "Garage admin API URL"),
    ("BACKUP_ENABLED", "false", False, "Enable automated backups"),
    ("BACKUP_SCHEDULE_HOURS", "24", False, "Backup interval in hours"),
    ("BACKUP_RETENTION_COUNT", "10", False, "Number of backups to retain"),
    ("AUDIT_LOG_RETENTION_DAYS", "365", False, "Audit log retention days (0=forever)"),
    ("MISSION_RETENTION_DAYS", "0", False, "Auto-delete completed missions after N days (0=forever)"),
    ("ADMIN_IP_ALLOWLIST", "", False, "Admin route IP allowlist (comma-separated CIDRs)"),
    ("AUTOSCALE_ENABLED", "false", False, "Enable auto-scaling"),
    ("AUTOSCALE_WORKER_MIN", "1", False, "Min worker replicas"),
    ("AUTOSCALE_WORKER_MAX", "10", False, "Max worker replicas"),
    ("AUTOSCALE_API_MIN", "1", False, "Min API replicas"),
    ("AUTOSCALE_API_MAX", "5", False, "Max API replicas"),
    ("AUTOSCALE_AI_MAX", "3", False, "Max AI service replicas"),
    ("AUTOSCALE_QUEUE_THRESHOLD", "10", False, "Queue depth to trigger scale-up"),
    ("AUTOSCALE_COOLDOWN_SECS", "300", False, "Cooldown between scale actions (seconds)"),
    ("AUTOSCALE_IDLE_SECS", "300", False, "Idle time before scale-down (seconds)"),
    ("AUTOSCALE_CPU_UP_THRESHOLD", "75", False, "CPU % to trigger scale-up"),
    ("AUTOSCALE_CPU_DOWN_THRESHOLD", "25", False, "CPU % to trigger scale-down"),
    ("SWARM_WORKER_SERVICE", "spectra_worker", False, "Docker Swarm worker service name"),
    ("SWARM_API_SERVICE", "spectra_app", False, "Docker Swarm API service name"),
    ("SWARM_AI_SERVICE", "spectra_ai-svc", False, "Docker Swarm AI service name"),
    ("SWARM_SCHEDULER_SERVICE", "spectra_scheduler", False, "Docker Swarm scheduler service name"),
    ("INFRA_MONITOR_ENABLED", "true", False, "Enable infrastructure monitoring"),
    ("INFRA_MONITOR_PG_THRESHOLD", "80", False, "PostgreSQL connection % alert threshold"),
    ("INFRA_MONITOR_REDIS_THRESHOLD", "85", False, "Redis memory % alert threshold"),
    ("INFRA_MONITOR_STORAGE_THRESHOLD", "90", False, "Storage usage % alert threshold"),
    ("AUTO_HEAL_ENABLED", "true", False, "Enable auto-healing"),
    ("AUTO_HEAL_MAX_RETRIES", "3", False, "Auto-heal max retry attempts"),
    ("AUTO_HEAL_COOLDOWN_SECS", "300", False, "Auto-heal cooldown seconds"),
    ("SYSTEM_MEMORY_ALERT_THRESHOLD", "90", False, "Memory usage % alert threshold"),
    ("SYSTEM_DISK_ALERT_THRESHOLD", "85", False, "Disk usage % alert threshold"),
    ("SYSTEM_LOAD_ALERT_MULTIPLIER", "2.0", False, "Load alert multiplier (x CPUs)"),
    ("DB_MAINTENANCE_INTERVAL", "604800", False, "DB VACUUM ANALYZE interval seconds"),
    ("STALE_JOB_RECOVERY_INTERVAL", "300", False, "Stale job recovery interval seconds"),
    ("EXPLOIT_DB_REFRESH_HOURS", "168", False, "Exploit DB refresh interval hours"),
    ("DOCKER_CLEANUP_INTERVAL", "604800", False, "Docker pruning interval seconds"),
    ("IMAGE_AUTO_UPDATE", "true", False, "Auto-apply image updates"),
    ("IMAGE_CHECK_INTERVAL", "60", False, "Image update check interval seconds"),
    ("PAYMENT_PROVIDER", "noop", False, "Payment provider: noop, stripe, crypto, manual"),
    ("STRIPE_SECRET_KEY", "", True, "Stripe API secret key"),
    ("STRIPE_WEBHOOK_SECRET", "", True, "Stripe webhook signing secret"),
    ("STRIPE_PUBLISHABLE_KEY", "", False, "Stripe publishable key"),
    ("CRYPTO_PAYMENT_URL", "", False, "Crypto payment provider URL"),
    ("CRYPTO_PAYMENT_API_KEY", "", True, "Crypto payment API key"),
    ("MAX_REQUEST_BODY_SIZE", "10485760", False, "Max request body size bytes"),
    ("MAX_UPLOAD_SIZE", "52428800", False, "Max upload size bytes"),
    ("REQUEST_TIMEOUT_SECONDS", "60", False, "Request timeout seconds"),
    ("SANDBOX_WORKER_POLL_DELAY", "0.5", False, "Sandbox worker poll delay seconds"),
]


def upgrade():
    """Seed default system_config rows. ON CONFLICT DO NOTHING preserves existing values."""
    conn = op.get_bind()
    for key, value, is_secret, description in _DEFAULTS:
        conn.execute(
            sa.text(
                "INSERT INTO system_config (id, key, value, is_secret, description, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :key, :value, :is_secret, :description, now(), now()) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value, "is_secret": is_secret, "description": description},
        )


def downgrade():
    """Remove seeded config rows. Only deletes rows with default values to avoid
    destroying user-modified configuration."""
    conn = op.get_bind()
    for key, value, is_secret, description in _DEFAULTS:
        conn.execute(
            sa.text("DELETE FROM system_config WHERE key = :key AND value = :value"),
            {"key": key, "value": value},
        )
