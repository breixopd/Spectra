#!/usr/bin/env bash
set -euo pipefail

# Spectra First-Run Setup
# Automates: Garage S3 bootstrap, .env configuration, migrations, admin setup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.yml"
ENV_FILE="${PROJECT_ROOT}/.env"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

log() { echo -e "${GREEN}[SETUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Check prerequisites
check_prereqs() {
    log "[1/5] Checking prerequisites..."
    for cmd in docker curl jq openssl; do
        command -v "$cmd" >/dev/null 2>&1 || { err "Required command not found: $cmd"; exit 1; }
    done

    docker compose version >/dev/null 2>&1 || { err "Docker Compose V2 required"; exit 1; }

    if [[ ! -f "${ENV_FILE}" ]]; then
        if [[ -f "${ENV_FILE}.example" ]]; then
            log "Creating .env from .env.example..."
            cp "${ENV_FILE}.example" "${ENV_FILE}"
        else
            err "No .env file found. Create one from .env.example first."
            exit 1
        fi
    fi
    log "Prerequisites OK"

    # ── Auto-generate secrets ──
    if grep -q "change-me-with-a-long-random-value" "${ENV_FILE}"; then
        log "Generating cryptographic secrets..."
        generate_secret() { openssl rand -hex 32; }
        generate_password() { openssl rand -base64 18 | tr -d '/+=' | head -c 24; }

        local db_pass
        db_pass="$(generate_password)"

        sed -i "s|change-me-with-a-long-random-value|$(generate_secret)|" "${ENV_FILE}"
        sed -i "s|change-me-with-a-different-long-random-value|$(generate_secret)|" "${ENV_FILE}"
        sed -i "s|change-me-shared-between-app-ai-scheduler-worker|$(generate_secret)|" "${ENV_FILE}"
        sed -i "s|change-me-db-password|${db_pass}|" "${ENV_FILE}"
        sed -i "s|change-me-redis-pass|$(generate_password)|" "${ENV_FILE}"
        sed -i "s|change-me-clickhouse|$(generate_password)|" "${ENV_FILE}"
        log "  ✓ Secrets generated"
    else
        log ".env already has real secrets, skipping generation"
    fi
}

# Start core services (DB, Redis, Garage)
start_core() {
    log "[2/5] Starting core services..."
    docker compose -f "${COMPOSE_FILE}" up -d db redis garage

    log "Waiting for services to be healthy..."
    local retries=30
    while [[ $retries -gt 0 ]]; do
        if docker compose -f "${COMPOSE_FILE}" ps --format json | \
           python3 -c "import sys,json; services=json.loads(sys.stdin.read()); exit(0 if all(s.get('Health','')=='healthy' for s in services if s['Service'] in ('db','redis','garage')) else 1)" 2>/dev/null; then
            log "Core services healthy"
            return 0
        fi
        retries=$((retries - 1))
        sleep 2
    done
    err "Core services failed to become healthy"
    exit 1
}

# Bootstrap Garage S3
bootstrap_garage() {
    log "[3/5] Bootstrapping S3 storage..."

    # Check if already bootstrapped
    if docker compose -f "${COMPOSE_FILE}" exec -T garage /garage status 2>/dev/null | grep -q "CONFIGURED"; then
        log "Garage already configured, checking buckets..."
        local existing_buckets
        existing_buckets=$(docker compose -f "${COMPOSE_FILE}" exec -T garage /garage bucket list 2>/dev/null || echo "")
        if echo "$existing_buckets" | grep -q "spectra-missions"; then
            log "S3 buckets already exist — skipping bootstrap"
            return 0
        fi
    fi

    # Run the garage-init script and capture credentials
    if [[ ! -f "${PROJECT_ROOT}/docker/garage-init.sh" ]]; then
        err "garage-init.sh not found"
        exit 1
    fi

    local init_output
    init_output="$(bash "${PROJECT_ROOT}/docker/garage-init.sh" 2>&1)" || {
        err "Garage bootstrap failed:"
        echo "$init_output" >&2
        exit 1
    }

    # Parse garage keys from init output and write to .env
    local access_key secret_key
    access_key="$(echo "$init_output" | sed -n 's/.*GARAGE_ACCESS_KEY=//p' | tail -1 | tr -d '[:space:]')"
    secret_key="$(echo "$init_output" | sed -n 's/.*GARAGE_SECRET_KEY=//p' | tail -1 | tr -d '[:space:]')"

    if [[ -n "$access_key" && -n "$secret_key" ]]; then
        sed -i "s|^GARAGE_ACCESS_KEY=.*|GARAGE_ACCESS_KEY=${access_key}|" "${ENV_FILE}"
        sed -i "s|^GARAGE_SECRET_KEY=.*|GARAGE_SECRET_KEY=${secret_key}|" "${ENV_FILE}"
        log "  ✓ S3 credentials auto-configured"
    else
        warn "Could not parse Garage credentials — check garage-init output"
        echo "$init_output"
    fi

    log "S3 storage bootstrapped"
}

# Run database migrations
run_migrations() {
    log "[4/5] Running database migrations..."
    docker compose -f "${COMPOSE_FILE}" run --rm -e SKIP_MIGRATIONS=false app \
        python3 -m alembic -c /app/config/alembic.ini upgrade heads 2>&1 | tail -5
    log "Migrations complete"
}

# Start all services
start_all() {
    log "[5/5] Starting all services..."
    docker compose -f "${COMPOSE_FILE}" up -d

    log "Waiting for application to be healthy..."
    local retries=30
    while [[ $retries -gt 0 ]]; do
        if curl -sf http://localhost:${APP_PORT:-443}/api/health >/dev/null 2>&1; then
            log "Application is healthy"
            return 0
        fi
        retries=$((retries - 1))
        sleep 3
    done
    warn "Application health check timed out — check docker logs"
}

# Print summary
print_summary() {
    local port="${APP_PORT:-443}"
    local scheme="https"
    [[ "$port" == "80" || "$port" == "15080" ]] && scheme="http"
    local url="${scheme}://localhost:${port}"

    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ Spectra is ready!${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${GREEN}Open:${NC}  ${url}/setup"
    echo ""
    echo -e "  Create your admin account, then start your first assessment."
    echo ""
    echo -e "  ${BLUE}Useful commands:${NC}"
    echo -e "    Logs:    docker compose -f docker/docker-compose.yml logs -f app"
    echo -e "    Stop:    docker compose -f docker/docker-compose.yml down"
    echo -e "    Health:  curl -sf ${url}/api/health | python3 -m json.tool"
    echo ""
}

# Main
main() {
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Spectra First-Run Setup${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo ""

    check_prereqs
    start_core
    bootstrap_garage
    run_migrations
    start_all
    print_summary
}

main "$@"
