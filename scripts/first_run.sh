#!/usr/bin/env bash
set -euo pipefail

# Spectra First-Run Setup
# Generates all secrets, bootstraps Garage S3, runs migrations, starts stack.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.yml"
ENV_FILE="${PROJECT_ROOT}/.env"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

log() { echo -e "${GREEN}[SETUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Helpers ──

generate_password() { openssl rand -base64 18 | tr -d '/+=' | head -c 24; }
generate_secret()   { openssl rand -base64 32; }
generate_hex()      { openssl rand -hex 32; }

# Write a var to .env only if it is missing or empty.
env_set() {
    local var="$1" value="$2"
    if grep -q "^${var}=" "${ENV_FILE}" 2>/dev/null; then
        local current
        current="$(grep "^${var}=" "${ENV_FILE}" | head -1 | cut -d= -f2-)"
        if [[ -n "${current}" ]]; then
            return 0  # already set, don't overwrite
        fi
        # Var exists but is empty — replace the line
        sed -i "s|^${var}=.*|${var}=${value}|" "${ENV_FILE}"
    else
        echo "${var}=${value}" >> "${ENV_FILE}"
    fi
}

# ── Phase 1: Prerequisites ──

check_prereqs() {
    log "[1/5] Checking prerequisites..."
    for cmd in docker openssl; do
        command -v "$cmd" >/dev/null 2>&1 || { err "Required command not found: $cmd"; exit 1; }
    done

    docker compose version >/dev/null 2>&1 || { err "Docker Compose V2 required"; exit 1; }

    if [[ ! -f "${ENV_FILE}" ]]; then
        if [[ -f "${ENV_FILE}.example" ]]; then
            log "Creating .env from .env.example..."
            cp "${ENV_FILE}.example" "${ENV_FILE}"
        else
            log "Creating empty .env..."
            touch "${ENV_FILE}"
        fi
    fi
    chmod 600 "${ENV_FILE}"
    log "Prerequisites OK"
}

# ── Phase 2: Auto-generate ALL secrets ──

generate_secrets() {
    log "[2/5] Generating secrets..."

    local pg_pass redis_pass ch_pass
    pg_pass="$(generate_password)"
    redis_pass="$(generate_password)"
    ch_pass="$(generate_password)"

    env_set POSTGRES_PASSWORD "${pg_pass}"
    env_set REDIS_PASSWORD "${redis_pass}"
    env_set CLICKHOUSE_PASSWORD "${ch_pass}"
    env_set GARAGE_RPC_SECRET "$(generate_hex)"

    env_set JWT_SECRET_KEY "$(generate_secret)"
    env_set SECRET_KEY "$(generate_secret)"
    env_set SERVICE_AUTH_SECRET "$(generate_secret)"
    env_set ENCRYPTION_KEY "$(generate_secret)"

    # Re-read passwords (may have been pre-configured by user)
    set -a; source "${ENV_FILE}"; set +a

    env_set DATABASE_URL "postgresql+asyncpg://spectra:${POSTGRES_PASSWORD}@db:5432/spectra"
    env_set RATE_LIMIT_STORAGE "redis://:${REDIS_PASSWORD}@redis:6379/0"
    env_set S3_ENDPOINT_URL "http://garage:3900"

    log "  ✓ Secrets ready"
}

# ── Phase 3: Start core services ──

start_core() {
    log "[3/5] Starting core services..."
    docker compose -f "${COMPOSE_FILE}" up -d db redis garage

    log "Waiting for services to be healthy..."
    local retries=30
    while [[ $retries -gt 0 ]]; do
        if docker compose -f "${COMPOSE_FILE}" ps --format json 2>/dev/null | \
           python3 -c "
import sys, json
raw = sys.stdin.read().strip()
if not raw:
    sys.exit(1)
# Handle both JSON array and newline-delimited JSON objects
if raw.startswith('['):
    services = json.loads(raw)
else:
    services = [json.loads(line) for line in raw.splitlines() if line.strip()]
targets = {'db', 'redis', 'garage'}
matched = [s for s in services if s.get('Service', '') in targets]
sys.exit(0 if matched and all(s.get('Health', '') == 'healthy' for s in matched) else 1)
" 2>/dev/null; then
            log "Core services healthy"
            return 0
        fi
        retries=$((retries - 1))
        sleep 2
    done
    err "Core services failed to become healthy"
    exit 1
}

# ── Phase 4: Bootstrap Garage S3 ──

bootstrap_garage() {
    log "[4/5] Bootstrapping S3 storage..."

    # Check if already bootstrapped
    if docker compose -f "${COMPOSE_FILE}" exec -T garage /garage status 2>/dev/null | grep -q "CONFIGURED"; then
        local existing_buckets
        existing_buckets=$(docker compose -f "${COMPOSE_FILE}" exec -T garage /garage bucket list 2>/dev/null || echo "")
        if echo "$existing_buckets" | grep -q "spectra-missions"; then
            log "S3 buckets already exist — skipping bootstrap"
            return 0
        fi
    fi

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

    # Parse garage keys from init output
    local access_key secret_key
    access_key="$(echo "$init_output" | sed -n 's/.*GARAGE_ACCESS_KEY=//p' | tail -1 | tr -d '[:space:]')"
    secret_key="$(echo "$init_output" | sed -n 's/.*GARAGE_SECRET_KEY=//p' | tail -1 | tr -d '[:space:]')"

    if [[ -n "$access_key" && -n "$secret_key" ]]; then
        # Force-overwrite garage keys since they come from the running instance
        sed -i "s|^GARAGE_ACCESS_KEY=.*|GARAGE_ACCESS_KEY=${access_key}|" "${ENV_FILE}"
        if grep -q "^GARAGE_SECRET_KEY=" "${ENV_FILE}"; then
            sed -i "s|^GARAGE_SECRET_KEY=.*|GARAGE_SECRET_KEY=${secret_key}|" "${ENV_FILE}"
        else
            echo "GARAGE_SECRET_KEY=${secret_key}" >> "${ENV_FILE}"
        fi
        if grep -q "^GARAGE_ACCESS_KEY=" "${ENV_FILE}"; then
            true  # already handled by sed above
        else
            echo "GARAGE_ACCESS_KEY=${access_key}" >> "${ENV_FILE}"
        fi
        log "  ✓ S3 credentials written to .env"
    else
        warn "Could not parse Garage credentials — check garage-init output"
        echo "$init_output"
    fi

    log "S3 storage bootstrapped"
}

# ── Phase 5: Start everything ──

start_all() {
    log "[5/5] Starting all services..."

    # Re-read .env (now has Garage keys)
    docker compose -f "${COMPOSE_FILE}" up -d

    log "Waiting for application to be healthy..."
    local retries=30
    while [[ $retries -gt 0 ]]; do
        if curl -sf "http://localhost:${APP_PORT:-443}/api/v1/health?scope=public" >/dev/null 2>&1; then
            log "Application is healthy"
            return 0
        fi
        retries=$((retries - 1))
        sleep 3
    done
    warn "Application health check timed out — check docker logs"
}

# ── Summary ──

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
    echo -e "    Health:  curl -sf '${url}/api/v1/health?scope=public' | python3 -m json.tool"
    echo ""
}

# ── Main ──

main() {
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Spectra First-Run Setup${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo ""

    check_prereqs
    generate_secrets
    start_core
    bootstrap_garage
    start_all
    print_summary
}

main "$@"
