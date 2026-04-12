#!/bin/bash
set -euo pipefail

# ── Resolve Docker secrets (Swarm mode) ──
# Docker secrets are mounted as files at /run/secrets/<name>.
# If a *_FILE env var is set, read the file content into the base env var.
for secret_var in JWT_SECRET_KEY SECRET_KEY SERVICE_AUTH_SECRET ENCRYPTION_KEY \
                  DATABASE_URL S3_ACCESS_KEY S3_SECRET_KEY REDIS_PASSWORD \
                  CLICKHOUSE_PASSWORD OPENAI_API_KEY GARAGE_ADMIN_TOKEN; do
    file_var="${secret_var}_FILE"
    if [[ -n "${!file_var:-}" ]] && [[ -f "${!file_var}" ]]; then
        export "$secret_var"="$(< "${!file_var}")"
    fi
done

# Auto-derive RATE_LIMIT_STORAGE from redis_password secret if not explicitly set
if [[ -f "/run/secrets/redis_password" ]] && [[ -z "${RATE_LIMIT_STORAGE:-}" ]]; then
    export RATE_LIMIT_STORAGE="redis://:$(cat /run/secrets/redis_password)@redis:6379/0"
fi

# Fix Docker socket permissions if mounted (needed for sandbox container management)
if [ -S /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo "")
    if [ -n "$DOCKER_GID" ] && [ "$DOCKER_GID" != "0" ]; then
        # Find or create a group matching the socket GID
        DOCKER_GROUP=$(getent group "$DOCKER_GID" | cut -d: -f1 2>/dev/null || echo "")
        if [ -z "$DOCKER_GROUP" ]; then
            # No group with this GID exists — create one
            groupadd -g "$DOCKER_GID" dockersock 2>/dev/null && DOCKER_GROUP="dockersock"
        fi
        if [ -n "$DOCKER_GROUP" ]; then
            usermod -aG "$DOCKER_GROUP" spectra 2>/dev/null || true
        else
            # Last resort: make socket world-readable (container is already isolated)
            chmod 666 /var/run/docker.sock 2>/dev/null || true
        fi
    fi
fi

# Wait for DB to be ready
echo "Waiting for database..."
retries=60
while ! nc -z db 5432 2>/dev/null; do
    retries=$((retries - 1))
    if [ $retries -le 0 ]; then
        echo "ERROR: Database not available after 60 seconds"
        exit 1
    fi
    sleep 1
done
echo "Database is ready!"

# Run migrations as spectra user (skip for non-app microservices)
# Alembic handles concurrent migrations via SELECT FOR UPDATE on the version table.
# Retry loop covers the race where two replicas start simultaneously.
if [ "${SKIP_MIGRATIONS:-false}" = "true" ]; then
    echo "Skipping migrations (SKIP_MIGRATIONS=true)"
else
    echo "Running database migrations..."
    max_retries=3
    retry=0
    while [ $retry -lt $max_retries ]; do
        if gosu spectra alembic -c config/alembic.ini upgrade heads 2>&1; then
            echo "Migrations applied."
            break
        fi
        retry=$((retry + 1))
        if [ $retry -lt $max_retries ]; then
            echo "Migration attempt $retry failed, retrying in 10s..."
            sleep 10
        else
            echo "ERROR: Database migration failed after $max_retries attempts."
            exit 1
        fi
    done
fi

# Ensure data directories are writable (volumes mount as root)
mkdir -p /app/data/missions /app/data/backups /app/logs
chown -R spectra:spectra /app/data /app/logs 2>/dev/null || true

# Sync plugins to shared volume (for sandbox DinD access)
if [ -d /app/plugins ] && [ -d /app/plugins_shared ]; then
    cp -a /app/plugins/. /app/plugins_shared/ 2>/dev/null || true
fi

# Drop privileges and start application as spectra user
echo "Starting application..."
exec gosu spectra "$@"
