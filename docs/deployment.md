# Spectra Deployment Guide

## Overview

Spectra is designed to be deployed using Docker Compose. This guide covers deployment, configuration, and maintenance.

## Prerequisites

- Docker Engine 24.0+
- Docker Compose v2.20+
- NVIDIA Container Toolkit (optional, for local LLM acceleration)

## Deployment Steps

### 1. Clone Repository

```bash
git clone https://github.com/your-org/spectra.git
cd spectra
```

### 2. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and set the following critical variables:

- `JWT_SECRET_KEY`: Generate a secure random string (e.g., `openssl rand -hex 32`)
- `POSTGRES_PASSWORD`: Set a strong database password
- `REDIS_PASSWORD`: Set a strong Redis password
- `LLM_API_KEY`: If using external LLM provider (OpenAI, etc.)

### 3. Production Deployment

Use the production override file to enforce security settings and resource limits.

```bash
docker compose -f docker/docker-compose.yml up -d
```

This will:

- Start all services (App, DB, Redis, Ollama)
- Apply resource limits
- Disable debug mode
- Enable plugin safe mode (signature verification)
- Hide internal ports (DB, Redis) from the host

### 4. Verify Deployment

Check the health endpoint:

```bash
curl http://localhost:5000/health
```

Expected output:

```json
{
  "status": "healthy",
  "service": "spectra",
  "components": {
    "database": "healthy",
    "redis": "healthy"
  }
}
```

## Maintenance

### Database Migrations

Migrations run automatically on startup. To run manually:

```bash
docker compose exec app alembic upgrade head
```

### Backups

**Database:**

```bash
docker compose exec db pg_dump -U spectra spectra > backup_db_$(date +%F).sql
```

**Redis:**
Redis is configured to save snapshots (RDB) and append-only logs (AOF) to the `redis_data` volume.

### Logs

View logs for all services:

```bash
docker compose logs -f
```

## Troubleshooting

### Issue: Database connection failed

- Check logs: `docker compose logs db`
- Verify `POSTGRES_PASSWORD` matches in `.env`

### Issue: Plugin upload failed

- In production, plugins must be signed.
- Ensure `PLUGIN_SAFE_MODE` is handled correctly.
- Sign plugins offline using `scripts/sign_plugin.py`.

### Issue: LLM timeout

- Local LLMs can be slow on CPU.
- Increase `REQUEST_TIMEOUT` in `.env`.
- Use GPU acceleration if available.
