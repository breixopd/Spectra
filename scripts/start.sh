#!/bin/bash
set -e

# Wait for DB to be ready
echo "Waiting for database..."
until curl -s http://db:5432 > /dev/null 2>&1 || nc -z db 5432; do
  sleep 1
done
echo "Database is ready."

# Run migrations
echo "Running database migrations..."
# Generate migration if it doesn't exist (auto-generation)
# We check if versions folder is empty
if [ -z "$(ls -A alembic/versions)" ]; then
   echo "No migrations found. Generating initial migration..."
   alembic revision --autogenerate -m "Initial migration"
fi

# Apply migrations
alembic upgrade head
echo "Migrations applied."

# Start application
echo "Starting application..."
exec "$@"
