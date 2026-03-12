"""Provisioning recipes for remote Spectra services."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProvisionStep:
    """A single step in a provisioning recipe."""

    name: str
    command: str
    timeout: int = 120
    required: bool = True


# Docker installation (shared across all service types)
_DOCKER_INSTALL_STEPS = [
    ProvisionStep(
        name="Check/Install Docker",
        command=(
            "if command -v docker &>/dev/null; then echo 'Docker already installed'; "
            "else curl -fsSL https://get.docker.com | sh; fi"
        ),
        timeout=300,
    ),
    ProvisionStep(
        name="Start Docker daemon",
        command="systemctl enable docker && systemctl start docker && docker info >/dev/null 2>&1",
        timeout=30,
    ),
    ProvisionStep(
        name="Create Spectra network",
        command="docker network create spectra-remote 2>/dev/null || true",
        timeout=10,
        required=False,
    ),
]


# Container name constants per service type (used by deprovision)
CONTAINER_NAMES: dict[str, str] = {
    "sandbox_worker": "spectra-sandbox-worker",
    "app_worker": "spectra-app-worker",
    "tools_worker": "spectra-tools-worker",
    "db_replica": "spectra-db-replica",
    "db_backup": "spectra-db-backup",
}

PROVISIONING_RECIPES: dict[str, list[ProvisionStep]] = {
    "sandbox_worker": [
        *_DOCKER_INSTALL_STEPS,
        ProvisionStep(
            name="Pull Spectra tools image",
            command="docker pull ghcr.io/spectra/spectra-tools:latest || docker build -t spectra-tools /tmp/spectra-tools/ || echo 'will_build_next'",
            timeout=600,
            required=False,
        ),
        ProvisionStep(
            name="Stop existing sandbox worker",
            command="docker stop spectra-sandbox-worker 2>/dev/null; docker rm spectra-sandbox-worker 2>/dev/null; echo ok",
            timeout=15,
            required=False,
        ),
        ProvisionStep(
            name="Start sandbox worker",
            command=(
                "docker run -d --name spectra-sandbox-worker "
                "--network spectra-remote --restart unless-stopped "
                "-p {service_port}:5000 "
                "{env_vars} "
                "-v /var/run/docker.sock:/var/run/docker.sock:ro "
                "spectra-tools"
            ),
            timeout=30,
        ),
    ],
    "app_worker": [
        *_DOCKER_INSTALL_STEPS,
        ProvisionStep(
            name="Pull Spectra app image",
            command="docker pull {registry}/spectra-app:{version} || echo 'image_pull_skipped'",
            timeout=600,
            required=False,
        ),
        ProvisionStep(
            name="Stop existing app worker",
            command="docker stop spectra-app-worker 2>/dev/null; docker rm spectra-app-worker 2>/dev/null; echo ok",
            timeout=15,
            required=False,
        ),
        ProvisionStep(
            name="Start app worker",
            command=(
                "docker run -d --name spectra-app-worker "
                "--network spectra-remote --restart always "
                "-p {service_port}:5000 "
                "{env_vars} "
                "{registry}/spectra-app:{version}"
            ),
            timeout=30,
        ),
    ],
    "tools_worker": [
        *_DOCKER_INSTALL_STEPS,
        ProvisionStep(
            name="Pull Spectra tools image",
            command="docker pull {registry}/spectra-tools:{version} || echo 'image_pull_skipped'",
            timeout=600,
            required=False,
        ),
        ProvisionStep(
            name="Stop existing tools worker",
            command="docker stop spectra-tools-worker 2>/dev/null; docker rm spectra-tools-worker 2>/dev/null; echo ok",
            timeout=15,
            required=False,
        ),
        ProvisionStep(
            name="Start tools worker",
            command=(
                "docker run -d --name spectra-tools-worker "
                "--network spectra-remote --restart always "
                "--cap-add NET_ADMIN --cap-add NET_RAW "
                "-p {service_port}:5000 "
                "{env_vars} "
                "{registry}/spectra-tools:{version}"
            ),
            timeout=30,
        ),
    ],
    "db_replica": [
        *_DOCKER_INSTALL_STEPS,
        ProvisionStep(
            name="Pull pgvector image",
            command="docker pull pgvector/pgvector:pg16",
            timeout=600,
        ),
        ProvisionStep(
            name="Stop existing DB replica",
            command="docker stop spectra-db-replica 2>/dev/null; docker rm spectra-db-replica 2>/dev/null; echo ok",
            timeout=15,
            required=False,
        ),
        ProvisionStep(
            name="Start DB replica",
            command=(
                "docker run -d --name spectra-db-replica "
                "--network spectra-remote --restart always "
                "-p {service_port}:5432 "
                "{env_vars} "
                "-v spectra_pg_data:/var/lib/postgresql/data "
                "pgvector/pgvector:pg16"
            ),
            timeout=30,
        ),
    ],
    "db_backup": [
        *_DOCKER_INSTALL_STEPS,
        ProvisionStep(
            name="Create backup directory",
            command="mkdir -p /opt/spectra/backups",
            timeout=10,
        ),
        ProvisionStep(
            name="Install backup script",
            command=(
                "cat > /opt/spectra/backup.sh << 'BACKUP_EOF'\n"
                "#!/bin/bash\n"
                "TIMESTAMP=$(date +%Y%m%d_%H%M%S)\n"
                "PGPASSWORD=$DB_PASS pg_dump -h $DB_HOST -U $DB_USER $DB_NAME "
                "| gzip > /opt/spectra/backups/spectra_$TIMESTAMP.sql.gz\n"
                "ls -t /opt/spectra/backups/spectra_*.sql.gz | tail -n +31 | xargs -r rm\n"
                "echo \"Backup completed: spectra_$TIMESTAMP.sql.gz\"\n"
                "BACKUP_EOF\n"
                "chmod +x /opt/spectra/backup.sh"
            ),
            timeout=10,
        ),
        ProvisionStep(
            name="Configure environment for backups",
            command=(
                "cat > /opt/spectra/backup.env << ENV_EOF\n"
                "DB_HOST={db_host}\n"
                "DB_USER={db_user}\n"
                "DB_PASS={db_pass}\n"
                "DB_NAME={db_name}\n"
                "ENV_EOF\n"
                "chmod 600 /opt/spectra/backup.env"
            ),
            timeout=10,
        ),
        ProvisionStep(
            name="Setup daily backup cron",
            command=(
                "(crontab -l 2>/dev/null | grep -v spectra/backup; "
                "echo '0 2 * * * . /opt/spectra/backup.env && /opt/spectra/backup.sh >> /var/log/spectra-backup.log 2>&1') | crontab -"
            ),
            timeout=10,
        ),
    ],
}
