#!/bin/bash
set -euo pipefail

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
    echo "Running database migrations..."
    if ! gosu spectra alembic -c config/alembic.ini upgrade heads 2>&1; then
        echo "ERROR: Database migration failed. Check the error above."
        exit 1
    fi
    echo "Migrations applied."
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
