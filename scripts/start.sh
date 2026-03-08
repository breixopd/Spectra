#!/bin/bash
set -e

# Fix Docker socket permissions if mounted (needed for tool execution)
if [ -S /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo "")
    if [ -n "$DOCKER_GID" ] && [ "$DOCKER_GID" != "0" ]; then
        groupmod -g "$DOCKER_GID" docker 2>/dev/null || groupadd -g "$DOCKER_GID" docker 2>/dev/null || true
        usermod -aG docker spectra 2>/dev/null || true
    fi
    # If running as root and spectra user exists, allow socket access
    if [ "$(id -u)" = "0" ] && id spectra >/dev/null 2>&1; then
        chmod 666 /var/run/docker.sock 2>/dev/null || true
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

# Run migrations
echo "Running database migrations..."
if ! alembic upgrade head 2>&1; then
    echo "ERROR: Database migration failed. Check the error above."
    exit 1
fi
echo "Migrations applied."

# Start application
echo "Starting application..."
exec "$@"
