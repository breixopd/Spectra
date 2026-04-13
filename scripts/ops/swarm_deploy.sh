#!/usr/bin/env bash
# scripts/ops/swarm_deploy.sh — Deploy Spectra to Docker Swarm
# Usage: ./scripts/ops/swarm_deploy.sh [OPTIONS]
#   --init         Initialize a new Swarm cluster
#   --join TOKEN   Join worker to existing Swarm
#   --deploy       Deploy/update the stack
#   --status       Show stack status
#   --rollback     Rollback to previous version
#   --label NODE ROLE  Set node role label (spectra.app|spectra.db|spectra.ai|spectra.worker)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.swarm.yml"
STACK_NAME="spectra"
LOG_PREFIX="[swarm]"

log()  { echo "${LOG_PREFIX} $(date +%H:%M:%S) $*"; }
warn() { echo "${LOG_PREFIX} $(date +%H:%M:%S) [WARN] $*" >&2; }
die()  { echo "${LOG_PREFIX} $(date +%H:%M:%S) [FATAL] $*" >&2; exit 1; }

check_swarm() {
  docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q "active" \
    || die "Docker Swarm is not active. Run with --init first."
}

check_manager() {
  docker info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null | grep -q "true" \
    || die "This node is not a Swarm manager."
}

cmd_init() {
  log "Initializing Docker Swarm..."
  local advertise_addr="${1:-}"
  if [[ -n "${advertise_addr}" ]]; then
    docker swarm init --advertise-addr "${advertise_addr}"
  else
    docker swarm init
  fi
  log "Swarm initialized. Join tokens:"
  echo ""
  echo "  Worker:  $(docker swarm join-token -q worker)"
  echo "  Manager: $(docker swarm join-token -q manager)"
  echo ""
  # Limit retained Swarm task history to avoid stale task container buildup
  docker swarm update --task-history-limit 3 >/dev/null 2>&1 || warn "Could not set task-history-limit"

  log "Label this node:"
  local node_id
  node_id=$(docker info --format '{{.Swarm.NodeID}}')
  echo "  docker node update --label-add spectra.app=true ${node_id}"
  echo "  docker node update --label-add spectra.db=true  ${node_id}"
}

cmd_label() {
  local node="${1:-}" role="${2:-}"
  [[ -n "${node}" && -n "${role}" ]] || die "Usage: --label NODE ROLE"
  check_swarm
  check_manager
  docker node update --label-add "spectra.${role}=true" "${node}"
  log "Node ${node} labeled with spectra.${role}=true"
}

cmd_secrets() {
  log "Creating Docker Swarm secrets..."

  # Source .env for values
  if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a; source "${PROJECT_ROOT}/.env"; set +a
  fi

  local secrets_created=0

  create_secret() {
    local name="$1" value="$2"
    if docker secret inspect "${name}" >/dev/null 2>&1; then
      log "Secret '${name}' already exists — skipping"
    else
      echo -n "${value}" | docker secret create "${name}" - >/dev/null
      log "Created secret: ${name}"
      ((secrets_created++))
    fi
  }

  create_secret "db_password"        "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"
  create_secret "db_url"             "postgresql+asyncpg://spectra:${POSTGRES_PASSWORD}@db:5432/spectra"
  create_secret "service_auth"       "${SERVICE_AUTH_SECRET:?SERVICE_AUTH_SECRET not set}"
  create_secret "jwt_secret"         "${JWT_SECRET_KEY:?JWT_SECRET_KEY not set}"
  create_secret "secret_key"         "${SECRET_KEY:?SECRET_KEY not set}"
  create_secret "encryption_key"     "${ENCRYPTION_KEY:?ENCRYPTION_KEY not set}"
  create_secret "redis_password"     "${REDIS_PASSWORD:?REDIS_PASSWORD not set}"
  create_secret "garage_access_key"  "${GARAGE_ACCESS_KEY:?GARAGE_ACCESS_KEY not set}"
  create_secret "garage_secret_key"  "${GARAGE_SECRET_KEY:?GARAGE_SECRET_KEY not set}"
  create_secret "garage_rpc_secret"  "${GARAGE_RPC_SECRET:?GARAGE_RPC_SECRET not set}"
  create_secret "clickhouse_password" "${CLICKHOUSE_PASSWORD:?CLICKHOUSE_PASSWORD not set}"
  create_secret "openai_api_key"     "${OPENAI_API_KEY:-}"

  log "Secrets ready (${secrets_created} created)"
}

cmd_deploy() {
  check_swarm
  check_manager

  [[ -f "${COMPOSE_FILE}" ]] || die "Swarm compose file not found: ${COMPOSE_FILE}"
  [[ -f "${PROJECT_ROOT}/.env" ]] || die ".env file not found"

  log "Deploying ${STACK_NAME} stack..."

  # Ensure secrets exist
  cmd_secrets

  # Pre-deploy: check node roles
  local nodes_with_roles
  nodes_with_roles=$(docker node ls --format '{{.Hostname}} {{.Status}}' | grep -c "Ready" || true)
  log "Active nodes: ${nodes_with_roles}"

  # Check minimum node labels
  for role in app db; do
    local count
    count=$(docker node ls -f "node.label.spectra.${role}=true" --format '{{.ID}}' | wc -l)
    if [[ "${count}" -eq 0 ]]; then
      warn "No nodes labeled with spectra.${role}=true. Services may not schedule."
      warn "Fix: docker node update --label-add spectra.${role}=true <node-id>"
    fi
  done

  # Deploy the stack
  set -a; source "${PROJECT_ROOT}/.env"; set +a
  docker stack deploy -c "${COMPOSE_FILE}" "${STACK_NAME}" --with-registry-auth

  log "Stack deployed. Waiting for services to converge..."

  # Wait for services
  local max_wait=120
  local elapsed=0
  while [[ "${elapsed}" -lt "${max_wait}" ]]; do
    local running
    running=$(docker stack services "${STACK_NAME}" --format '{{.Replicas}}' | grep -c '1/1\|2/2' || true)
    local total
    total=$(docker stack services "${STACK_NAME}" --format '{{.Replicas}}' | wc -l)
    log "Services ready: ${running}/${total}"
    if [[ "${running}" -eq "${total}" ]] && [[ "${total}" -gt 0 ]]; then
      log "All services converged!"
      break
    fi
    sleep 5
    ((elapsed+=5))
  done

  if [[ "${elapsed}" -ge "${max_wait}" ]]; then
    warn "Some services did not converge within ${max_wait}s"
    docker stack services "${STACK_NAME}" --format 'table {{.Name}}\t{{.Replicas}}\t{{.Image}}'
    exit 1
  fi

  # Health check
  log "Running health check..."
  sleep 5
  if "${SCRIPT_DIR}/../health_check.sh" 2>/dev/null; then
    log "Deployment successful!"
  else
    warn "Health check failed — check service logs"
    exit 1
  fi
}

cmd_status() {
  check_swarm
  check_manager

  echo "=== Nodes ==="
  docker node ls --format 'table {{.Hostname}}\t{{.Status}}\t{{.Availability}}\t{{.ManagerStatus}}'
  echo ""
  echo "=== Services ==="
  docker stack services "${STACK_NAME}" --format 'table {{.Name}}\t{{.Replicas}}\t{{.Image}}\t{{.Ports}}' 2>/dev/null || echo "Stack not deployed"
  echo ""
  echo "=== Tasks ==="
  docker stack ps "${STACK_NAME}" --format 'table {{.Name}}\t{{.Node}}\t{{.CurrentState}}\t{{.Error}}' --no-trunc 2>/dev/null | head -20 || true
}

cmd_rollback() {
  check_swarm
  check_manager

  log "Rolling back all services to previous version..."
  docker stack services "${STACK_NAME}" --format '{{.Name}}' | while read -r svc; do
    docker service rollback "${svc}" 2>/dev/null && log "Rolled back: ${svc}" || warn "No previous spec: ${svc}"
  done
  log "Rollback complete"
}

# Main
ACTION="${1:-}"
shift || true

case "${ACTION}" in
  --init)    cmd_init "$@";;
  --join)    docker swarm join --token "$@";;
  --label)   cmd_label "$@";;
  --secrets) cmd_secrets;;
  --deploy)  cmd_deploy;;
  --status)  cmd_status;;
  --rollback) cmd_rollback;;
  provision)
    # Provision a new node: harden + install Docker + join swarm
    TARGET_HOST="${1:?Usage: $0 provision <host> [--join-token <token>]}"
    JOIN_TOKEN=""
    shift
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --join-token) JOIN_TOKEN="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    log "Provisioning node: ${TARGET_HOST}"

    # Copy and run hardening script
    log "Hardening server..."
    scp "${SCRIPT_DIR}/harden_server.sh" "${TARGET_HOST}:/tmp/harden_server.sh"
    ssh "${TARGET_HOST}" "chmod +x /tmp/harden_server.sh && sudo /tmp/harden_server.sh --yes"

    # Install Docker
    log "Installing Docker..."
    ssh "${TARGET_HOST}" 'bash -se' <<'REMOTE_DOCKER_INSTALL'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
  curl -fsSL "https://download.docker.com/linux/$(. /etc/os-release && echo "${ID}")/gpg" | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
fi
sudo chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME:-${UBUNTU_CODENAME:-}} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker "$(id -un)"
REMOTE_DOCKER_INSTALL

    # Join swarm if token provided
    if [[ -n "${JOIN_TOKEN}" ]]; then
        MANAGER_IP=$(hostname -I | awk '{print $1}')
        log "Joining swarm..."
        ssh "${TARGET_HOST}" "sudo docker swarm join --token ${JOIN_TOKEN} ${MANAGER_IP}:2377"
        log "Node joined swarm successfully"
    else
        log "Skipping swarm join (no --join-token provided)"
        log "Get a join token with: docker swarm join-token worker"
    fi

    log "Provisioning complete for ${TARGET_HOST}"
    ;;
  *)
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  --init [ADDR]      Initialize Swarm cluster"
    echo "  --join TOKEN IP    Join as worker node"
    echo "  --label NODE ROLE  Set node role (app|db|ai|worker) → spectra.<role>=true"
    echo "  --secrets          Create/verify Docker secrets"
    echo "  --deploy           Deploy or update the stack"
    echo "  --status           Show stack status"
    echo "  --rollback         Rollback all services"
    echo "  provision HOST     Provision a new node (harden + Docker + join)"
    exit 1
    ;;
esac
