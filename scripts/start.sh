#!/bin/bash
set -euo pipefail

# ── Auto-generate secrets on first boot ──
# If core secrets are missing, generate them and persist to the data volume.
# This allows first-time setup without manual .env configuration.
SECRETS_DIR="/app/data/secrets"
mkdir -p "$SECRETS_DIR"

_generate_secret() {
    local name="$1"
    local length="${2:-64}"
    local file="$SECRETS_DIR/$name"
    if [[ -z "${!name:-}" ]] && [[ ! -f "$file" ]] && [[ ! -f "/run/secrets/${name,,}" ]]; then
        echo "Generating $name..."
        openssl rand -hex "$((length / 2))" > "$file"
        chmod 600 "$file"
    fi
    if [[ -f "$file" ]] && [[ -z "${!name:-}" ]]; then
        export "$name"="$(< "$file")"
    fi
}

_generate_secret JWT_SECRET_KEY 64
_generate_secret SECRET_KEY 64
_generate_secret SERVICE_AUTH_SECRET 64
_generate_secret ENCRYPTION_KEY 64

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
    # Also check Swarm secret path directly
    swarm_secret="/run/secrets/${secret_var,,}"
    if [[ -f "$swarm_secret" ]] && [[ -z "${!secret_var:-}" ]]; then
        export "$secret_var"="$(< "$swarm_secret")"
    fi
done

# Auto-derive RATE_LIMIT_STORAGE from redis_password secret if not explicitly set
if [[ -f "/run/secrets/redis_password" ]] && [[ -z "${RATE_LIMIT_STORAGE:-}" ]]; then
    export RATE_LIMIT_STORAGE="redis://:$(cat /run/secrets/redis_password)@redis:6379/0"
fi

# Align container group membership with mounted Docker socket. Never mutate the
# socket itself: it is a host-owned bind mount, and chown/chmod here can break
# the developer's Docker permissions after `docker compose up`.
if [ -S /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo "")
    if [ -n "$DOCKER_GID" ] && [ "$DOCKER_GID" != "0" ]; then
        SOCKET_GROUP=$(getent group "$DOCKER_GID" | cut -d: -f1 || true)
        if [ -z "$SOCKET_GROUP" ]; then
            if getent group docker >/dev/null; then
                groupmod -o -g "$DOCKER_GID" docker 2>/dev/null || true
            else
                groupadd -o -g "$DOCKER_GID" docker 2>/dev/null || true
            fi
            SOCKET_GROUP="docker"
        fi
        usermod -aG "$SOCKET_GROUP" spectra 2>/dev/null || true
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

DB_NAME=""
if [ -n "${DATABASE_URL:-}" ]; then
    DB_NAME=$(echo "$DATABASE_URL" | sed -E 's|.*://[^/]+/||; s|\?.*||')
fi
if [ -n "${DB_NAME:-}" ]; then
    echo "Ensuring database '$DB_NAME' exists..."
    /opt/venv/bin/python -c "
import asyncio, asyncpg, urllib.parse
u = urllib.parse.urlparse('${DATABASE_URL//+asyncpg/}')
host = u.hostname or 'db'
port = u.port or 5432
user = u.username or 'spectra'
password = u.password or '${POSTGRES_PASSWORD:-spectra_test}'
async def ensure():
    conn = await asyncpg.connect(host=host, port=port, user=user, password=password, database='postgres')
    try:
        exists = await conn.fetchval(\"SELECT 1 FROM pg_database WHERE datname = '\$DB_NAME'\")
        if not exists:
            await conn.execute(f\"CREATE DATABASE \\\"{DB_NAME}\\\"\")
            print(f\"Created database {DB_NAME}\")
        else:
            print(f\"Database {DB_NAME} already exists\")
    finally:
        await conn.close()
asyncio.run(ensure())
" 2>/dev/null || true
fi

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

# Drop privileges and start application
echo "Starting application..."
exec gosu spectra "$@"
