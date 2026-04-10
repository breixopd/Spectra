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
        # Match the docker group GID to the host's socket GID
        groupmod -g "$DOCKER_GID" docker 2>/dev/null || groupadd -g "$DOCKER_GID" dockerhost 2>/dev/null || true
        usermod -aG docker spectra 2>/dev/null || true
        usermod -aG dockerhost spectra 2>/dev/null || true
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
if [ "${SKIP_MIGRATIONS:-false}" = "true" ]; then
    echo "Skipping migrations (SKIP_MIGRATIONS=true)"
else
    echo "Acquiring migration lock..."
    # Use pg_advisory_lock to ensure only one container runs migrations
    # Lock ID 1 = migration lock. Blocking — waits until lock is available.
    if gosu spectra python3 -c "
import sys, os
from sqlalchemy import create_engine, text
db_url = os.environ.get('DATABASE_URL', '').replace('+asyncpg', '')
engine = create_engine(db_url)
with engine.connect() as conn:
    conn.execute(text('SELECT pg_advisory_lock(1)'))
    conn.commit()
print('Lock acquired')
" 2>&1; then
        echo "Running database migrations..."
        if ! gosu spectra alembic -c config/alembic.ini upgrade heads 2>&1; then
            echo "ERROR: Database migration failed. Check the error above."
            # Release the lock before exiting
            gosu spectra python3 -c "
import os
from sqlalchemy import create_engine, text
db_url = os.environ.get('DATABASE_URL', '').replace('+asyncpg', '')
engine = create_engine(db_url)
with engine.connect() as conn:
    conn.execute(text('SELECT pg_advisory_unlock(1)'))
    conn.commit()
" 2>/dev/null || true
            exit 1
        fi
        echo "Migrations applied."
        # Release the lock
        gosu spectra python3 -c "
import os
from sqlalchemy import create_engine, text
db_url = os.environ.get('DATABASE_URL', '').replace('+asyncpg', '')
engine = create_engine(db_url)
with engine.connect() as conn:
    conn.execute(text('SELECT pg_advisory_unlock(1)'))
    conn.commit()
" 2>/dev/null || true
    else
        echo "Could not acquire migration lock. Another instance may be running migrations."
        echo "Waiting 30s for migrations to complete..."
        sleep 30
    fi
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
