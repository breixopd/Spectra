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
HEALTH_CHECK_SCRIPT="${SCRIPT_DIR}/../health_check.sh"
HEALTH_URL="${HEALTH_URL:-http://localhost:80/api/v1/health?scope=public}"
BACKUP_DIR="${PROJECT_ROOT}/data/backups"
STATE_DIR="${PROJECT_ROOT}/.deploy/swarm"
GENERATED_SECRETS_FILE="${STATE_DIR}/generated-secrets.env"
CURRENT_VERSION_FILE="${STATE_DIR}/current-version"
PREVIOUS_VERSION_FILE="${STATE_DIR}/previous-version"
TARGET_VERSION_FILE="${STATE_DIR}/target-version"
PENDING_BACKUP_FILE_MARKER="${STATE_DIR}/pending-backup-file"
ROLLBACK_BACKUP_FILE_MARKER="${STATE_DIR}/rollback-backup-file"
DB_SERVICE_NAME="${STACK_NAME}_db"
DB_BACKUP_FILE=""
DOCKER_APT_REPO_SIGNING_FINGERPRINT="9DC858229FC7DD38854AE2D88D81803C0EBFCD88"

log()  { echo "${LOG_PREFIX} $(date +%H:%M:%S) $*"; }
warn() { echo "${LOG_PREFIX} $(date +%H:%M:%S) [WARN] $*" >&2; }
die()  { echo "${LOG_PREFIX} $(date +%H:%M:%S) [FATAL] $*" >&2; exit 1; }

load_deploy_env() {
  if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a; source "${PROJECT_ROOT}/.env"; set +a
  fi
  if [[ -f "${GENERATED_SECRETS_FILE}" ]]; then
    set -a; source "${GENERATED_SECRETS_FILE}"; set +a
  fi
}

persist_generated_secret() {
  local var_name="${1:?var name required}"
  local value="${2:?value required}"

  mkdir -p "${STATE_DIR}"
  touch "${GENERATED_SECRETS_FILE}"
  chmod 600 "${GENERATED_SECRETS_FILE}"
  if grep -q "^${var_name}=" "${GENERATED_SECRETS_FILE}"; then
    return 0
  fi
  printf '%s=%q\n' "${var_name}" "${value}" >> "${GENERATED_SECRETS_FILE}"
}

ensure_secret_var() {
  local var_name="${1:?var name required}"
  local default_value="${2:-}"
  local current_value="${!var_name:-}"

  if [[ -n "${current_value}" ]]; then
    return 0
  fi
  if [[ -n "${default_value}" ]]; then
    export "${var_name}=${default_value}"
  else
    export "${var_name}=$(openssl rand -hex 32)"
  fi
  persist_generated_secret "${var_name}" "${!var_name}"
  log "Generated ${var_name} in ${GENERATED_SECRETS_FILE}"
}

check_swarm() {
  docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q "active" \
    || die "Docker Swarm is not active. Run with --init first."
}

check_manager() {
  docker info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null | grep -q "true" \
    || die "This node is not a Swarm manager."
}

stack_exists() {
  docker stack services "${STACK_NAME}" >/dev/null 2>&1
}

get_db_container_id() {
  docker ps \
    --filter "label=com.docker.swarm.service.name=${DB_SERVICE_NAME}" \
    --format '{{.ID}}' | head -n 1
}

wait_for_db_ready() {
  local container_id="${1:-}"
  local attempts=10

  [[ -n "${container_id}" ]] || return 1

  while [[ "${attempts}" -gt 0 ]]; do
    if docker exec "${container_id}" pg_isready -U spectra -d spectra >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 3
  done

  return 1
}

run_health_check() {
  "${HEALTH_CHECK_SCRIPT}" "${HEALTH_URL}" 5 2
}

require_file_value() {
  local file_path="${1:-}"
  local label="${2:-value}"
  local value=""

  [[ -s "${file_path}" ]] || die "Missing ${label}: ${file_path}"
  value="$(tr -d '\n' < "${file_path}")"
  [[ -n "${value}" ]] || die "Empty ${label}: ${file_path}"

  printf '%s\n' "${value}"
}

extract_version_from_image() {
  local image_ref="${1:-}"
  local image_ref_without_digest=""
  local image_name_with_tag=""
  local tag=""

  [[ -n "${image_ref}" ]] || return 1

  image_ref_without_digest="${image_ref%@*}"
  if [[ "${image_ref}" != *"@"* ]]; then
    image_ref_without_digest="${image_ref}"
  fi

  image_name_with_tag="${image_ref_without_digest##*/}"
  [[ "${image_name_with_tag}" == *:* ]] || return 1

  tag="${image_name_with_tag##*:}"
  [[ -n "${tag}" ]] || return 1

  printf '%s\n' "${tag}"
}

get_current_stack_version() {
  local image_ref=""

  if ! stack_exists; then
    return 0
  fi

  image_ref="$(docker service inspect "${STACK_NAME}_app" --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}' 2>/dev/null || true)"
  extract_version_from_image "${image_ref}"
}

wait_for_stack_services() {
  local max_wait="${1:-120}"
  local elapsed=0

  while [[ "${elapsed}" -lt "${max_wait}" ]]; do
    local ready=0
    local total=0
    local replicas=""

    while IFS= read -r replicas; do
      local current=""
      local desired=""

      [[ -n "${replicas}" ]] || continue
      total=$((total + 1))
      current="${replicas%%/*}"
      desired="${replicas##*/}"
      if [[ "${current}" == "${desired}" ]]; then
        ready=$((ready + 1))
      fi
    done < <(docker stack services "${STACK_NAME}" --format '{{.Replicas}}' 2>/dev/null || true)

    log "Services ready: ${ready}/${total}"
    if [[ "${total}" -gt 0 && "${ready}" -eq "${total}" ]]; then
      return 0
    fi

    sleep 5
    elapsed=$((elapsed + 5))
  done

  return 1
}

backup_database() {
  local container_id=""
  local size=""

  mkdir -p "${BACKUP_DIR}" "${STATE_DIR}"
  DB_BACKUP_FILE=""

  if ! stack_exists; then
    log "No existing stack detected — skipping pre-deploy database backup"
    return 0
  fi

  container_id="$(get_db_container_id)"
  [[ -n "${container_id}" ]] || die "Cannot locate the Swarm database container — refusing deploy without a rollback restore target."

  wait_for_db_ready "${container_id}" || die "Database container is not ready — refusing deploy without a verified backup."

  DB_BACKUP_FILE="${BACKUP_DIR}/spectra_pre_deploy_$(date -u '+%Y%m%d_%H%M%S').sql.gz"
  log "Creating pre-deploy database backup: ${DB_BACKUP_FILE}"
  if docker exec "${container_id}" pg_dump -U spectra -d spectra 2>/dev/null | gzip > "${DB_BACKUP_FILE}"; then
    size="$(du -h "${DB_BACKUP_FILE}" | cut -f1)"
    printf '%s\n' "${DB_BACKUP_FILE}" > "${PENDING_BACKUP_FILE_MARKER}"
    log "Database backup complete: ${DB_BACKUP_FILE} (${size})"
    return 0
  fi

  rm -f "${DB_BACKUP_FILE}"
  rm -f "${PENDING_BACKUP_FILE_MARKER}"
  DB_BACKUP_FILE=""
  die "Database backup failed — refusing deploy because rollback state would be incomplete."
}

restore_database() {
  local backup_file="${1:-}"
  local container_id=""

  [[ -n "${backup_file}" ]] || die "No rollback backup file was provided."
  [[ -f "${backup_file}" ]] || die "Rollback backup file not found: ${backup_file}"

  container_id="$(get_db_container_id)"
  [[ -n "${container_id}" ]] || die "Cannot locate the Swarm database container for restore."

  wait_for_db_ready "${container_id}" || die "Database container is not ready — restore aborted."

  log "Restoring database from: ${backup_file}"
  if gunzip -c "${backup_file}" | docker exec -i "${container_id}" psql --single-transaction --set ON_ERROR_STOP=1 -U spectra -d spectra; then
    log "Database restored successfully"
    return 0
  fi

  die "Database restore failed — manual intervention required."
}

record_target_version() {
  local target_version="${1:-}"
  mkdir -p "${STATE_DIR}"
  printf '%s\n' "${target_version}" > "${TARGET_VERSION_FILE}"
}

record_previous_version() {
  local current_version="${1:-}"
  mkdir -p "${STATE_DIR}"
  printf '%s\n' "${current_version}" > "${CURRENT_VERSION_FILE}"
  printf '%s\n' "${current_version}" > "${PREVIOUS_VERSION_FILE}"
}

mark_current_version() {
  local current_version="${1:-}"
  mkdir -p "${STATE_DIR}"
  printf '%s\n' "${current_version}" > "${CURRENT_VERSION_FILE}"
  if [[ -f "${PENDING_BACKUP_FILE_MARKER}" ]]; then
    mv -f "${PENDING_BACKUP_FILE_MARKER}" "${ROLLBACK_BACKUP_FILE_MARKER}"
  else
    rm -f "${ROLLBACK_BACKUP_FILE_MARKER}"
  fi
  rm -f "${TARGET_VERSION_FILE}"
}

clear_rollback_state() {
  rm -f \
    "${PREVIOUS_VERSION_FILE}" \
    "${TARGET_VERSION_FILE}" \
    "${PENDING_BACKUP_FILE_MARKER}" \
    "${ROLLBACK_BACKUP_FILE_MARKER}"
}

mark_rolled_back_version() {
  local current_version="${1:-}"

  mkdir -p "${STATE_DIR}"
  printf '%s\n' "${current_version}" > "${CURRENT_VERSION_FILE}"
  clear_rollback_state
}

deploy_stack_version() {
  local version="${1:-}"
  VERSION="${version}" docker stack deploy -c "${COMPOSE_FILE}" "${STACK_NAME}" --with-registry-auth
}

rollback_to_version() {
  local rollback_version="${1:-}"
  local backup_file="${2:-}"

  [[ -n "${rollback_version}" ]] || die "No rollback version is recorded — refusing unsafe rollback."
  [[ -n "${backup_file}" && -f "${backup_file}" ]] || die "No rollback database backup is available — refusing unsafe rollback."

  log "Rolling back stack to version ${rollback_version}"
  deploy_stack_version "${rollback_version}"

  log "Waiting for rollback services to converge..."
  wait_for_stack_services || die "Rollback services did not converge in time."

  restore_database "${backup_file}"

  log "Running rollback health check against ${HEALTH_URL}..."
  if run_health_check; then
    log "Rollback complete"
    return 0
  fi

  die "Rollback health check failed — manual intervention required."
}

cmd_init() {
  log "Initializing Docker Swarm..."
  local advertise_addr="${1:-}"
  local node_id=""

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
  docker swarm update --task-history-limit 3 >/dev/null 2>&1 || warn "Could not set task-history-limit"

  log "Label this node:"
  node_id=$(docker info --format '{{.Swarm.NodeID}}')
  echo "  docker node update --label-add spectra.app=true ${node_id}"
  echo "  docker node update --label-add spectra.db=true  ${node_id}"
  echo "  docker node update --label-add spectra.ai=true  ${node_id}"
  echo "  docker node update --label-add spectra.worker=true ${node_id}"
}

cmd_label() {
  local node="${1:-}"
  local role="${2:-}"

  [[ -n "${node}" && -n "${role}" ]] || die "Usage: --label NODE ROLE"
  check_swarm
  check_manager
  docker node update --label-add "spectra.${role}=true" "${node}"
  log "Node ${node} labeled with spectra.${role}=true"
}

cmd_secrets() {
  local secrets_created=0

  log "Creating Docker Swarm secrets..."

  load_deploy_env

  ensure_secret_var "POSTGRES_PASSWORD"
  ensure_secret_var "SERVICE_AUTH_SECRET"
  ensure_secret_var "JWT_SECRET_KEY"
  ensure_secret_var "SECRET_KEY"
  ensure_secret_var "ENCRYPTION_KEY"
  ensure_secret_var "REDIS_PASSWORD"
  ensure_secret_var "GARAGE_ACCESS_KEY" "GK$(openssl rand -hex 12)"
  ensure_secret_var "GARAGE_SECRET_KEY"
  ensure_secret_var "GARAGE_RPC_SECRET"
  ensure_secret_var "GARAGE_ADMIN_TOKEN"
  ensure_secret_var "CLICKHOUSE_PASSWORD"
  ensure_secret_var "OPENAI_API_KEY" "not-configured"
  ensure_secret_var "ANTHROPIC_API_KEY" "not-configured"

  create_secret() {
    local name="$1"
    local value="$2"

    if docker secret inspect "${name}" >/dev/null 2>&1; then
      log "Secret '${name}' already exists — skipping"
    else
      echo -n "${value}" | docker secret create "${name}" - >/dev/null
      log "Created secret: ${name}"
      secrets_created=$((secrets_created + 1))
    fi
  }

  create_secret "db_password"         "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"
  create_secret "db_url"              "postgresql+asyncpg://spectra:${POSTGRES_PASSWORD}@db:5432/spectra"
  create_secret "service_auth"        "${SERVICE_AUTH_SECRET:?SERVICE_AUTH_SECRET not set}"
  create_secret "jwt_secret"          "${JWT_SECRET_KEY:?JWT_SECRET_KEY not set}"
  create_secret "secret_key"          "${SECRET_KEY:?SECRET_KEY not set}"
  create_secret "encryption_key"      "${ENCRYPTION_KEY:?ENCRYPTION_KEY not set}"
  create_secret "redis_password"      "${REDIS_PASSWORD:?REDIS_PASSWORD not set}"
  create_secret "garage_access_key"   "${GARAGE_ACCESS_KEY:?GARAGE_ACCESS_KEY not set}"
  create_secret "garage_secret_key"   "${GARAGE_SECRET_KEY:?GARAGE_SECRET_KEY not set}"
  create_secret "garage_rpc_secret"   "${GARAGE_RPC_SECRET:?GARAGE_RPC_SECRET not set}"
  create_secret "garage_admin_token"  "${GARAGE_ADMIN_TOKEN:?GARAGE_ADMIN_TOKEN not set}"
  create_secret "clickhouse_password" "${CLICKHOUSE_PASSWORD:?CLICKHOUSE_PASSWORD not set}"
  create_secret "openai_api_key"      "${OPENAI_API_KEY:-}"
  create_secret "anthropic_api_key"   "${ANTHROPIC_API_KEY:-}"

  log "Secrets ready (${secrets_created} created)"
}

cmd_preflight() {
  local role=""
  local count=""
  local secret=""
  local required_roles=(app db ai worker)
  local required_secrets=(
    db_password
    db_url
    service_auth
    jwt_secret
    secret_key
    encryption_key
    redis_password
    garage_access_key
    garage_secret_key
    garage_rpc_secret
    garage_admin_token
    clickhouse_password
    openai_api_key
    anthropic_api_key
  )

  check_swarm
  check_manager

  [[ -f "${COMPOSE_FILE}" ]] || die "Swarm compose file not found: ${COMPOSE_FILE}"
  [[ -f "${PROJECT_ROOT}/.env" || -f "${GENERATED_SECRETS_FILE}" ]] || die ".env or generated secrets file not found"
  load_deploy_env
  VERSION="${VERSION:?VERSION must be set in ${PROJECT_ROOT}/.env for swarm deploys}" docker compose -f "${COMPOSE_FILE}" config >/dev/null

  log "Checking required node labels..."
  for role in "${required_roles[@]}"; do
    count=$(docker node ls -f "node.label.spectra.${role}=true" --format '{{.ID}}' | wc -l)
    [[ "${count}" -gt 0 ]] || die "No Ready node has required label spectra.${role}=true"
    log "Label spectra.${role}=true: ${count} node(s)"
  done

  log "Checking required Docker secrets..."
  for secret in "${required_secrets[@]}"; do
    docker secret inspect "${secret}" >/dev/null 2>&1 || die "Missing Docker secret: ${secret}. Run ${0} --secrets."
  done

  docker network ls --filter name="${STACK_NAME}_frontend" --format '{{.Name}}' >/dev/null 2>&1 || true
  [[ -S /var/run/docker.sock ]] || die "Docker socket is not available on manager; scheduler placement requires it"
  log "Swarm preflight passed"
}

cmd_deploy() {
  local nodes_with_roles=""
  local role=""
  local count=""
  local max_wait=120
  local target_version=""
  local previous_version=""
  local had_existing_stack=false

  check_swarm
  check_manager

  [[ -f "${COMPOSE_FILE}" ]] || die "Swarm compose file not found: ${COMPOSE_FILE}"
  [[ -f "${PROJECT_ROOT}/.env" || -f "${GENERATED_SECRETS_FILE}" ]] || die ".env or generated secrets file not found"
  [[ -x "${HEALTH_CHECK_SCRIPT}" ]] || die "Health check script not found or not executable: ${HEALTH_CHECK_SCRIPT}"

  mkdir -p "${BACKUP_DIR}" "${STATE_DIR}"

  load_deploy_env
  : "${VERSION:?VERSION must be set in ${PROJECT_ROOT}/.env for swarm deploys}"
  target_version="${VERSION}"
  VERSION="${target_version}" docker compose -f "${COMPOSE_FILE}" config >/dev/null

  log "Deploying ${STACK_NAME} stack..."
  cmd_secrets
  cmd_preflight

  nodes_with_roles=$(docker node ls --format '{{.Hostname}} {{.Status}}' | grep -c "Ready" || true)
  log "Active nodes: ${nodes_with_roles}"

  for role in app db ai worker; do
    count=$(docker node ls -f "node.label.spectra.${role}=true" --format '{{.ID}}' | wc -l)
    if [[ "${count}" -eq 0 ]]; then
      warn "No nodes labeled with spectra.${role}=true. Services may not schedule."
      warn "Fix: docker node update --label-add spectra.${role}=true <node-id>"
    fi
  done

  record_target_version "${target_version}"
  if stack_exists; then
    had_existing_stack=true
    previous_version="$(get_current_stack_version)"
    [[ -n "${previous_version}" ]] || die "Cannot determine the currently deployed version — refusing update without an authoritative rollback target."
    record_previous_version "${previous_version}"
    backup_database
  else
    rm -f "${PREVIOUS_VERSION_FILE}" "${CURRENT_VERSION_FILE}"
    log "No existing stack detected — proceeding as a fresh deploy"
  fi

  deploy_stack_version "${target_version}"

  log "Stack deployed. Waiting for services to converge..."
  if ! wait_for_stack_services "${max_wait}"; then
    warn "Some services did not converge within ${max_wait}s"
    docker stack services "${STACK_NAME}" --format 'table {{.Name}}\t{{.Replicas}}\t{{.Image}}'
    if [[ "${had_existing_stack}" == true ]]; then
      rollback_to_version "${previous_version}" "${DB_BACKUP_FILE}"
      mark_rolled_back_version "${previous_version}"
      die "Deploy failed during convergence; automatic rollback restored version ${previous_version}."
    fi
    die "Deploy failed during convergence and no rollback target exists for this fresh stack."
  fi

  log "All services converged!"
  log "Running health check against ${HEALTH_URL}..."
  sleep 5
  if run_health_check; then
    mark_current_version "${target_version}"
    log "Deployment successful!"
    return 0
  fi

  warn "Health check failed — deploy is not healthy"
  if [[ "${had_existing_stack}" == true ]]; then
    rollback_to_version "${previous_version}" "${DB_BACKUP_FILE}"
    mark_rolled_back_version "${previous_version}"
    die "Deploy failed health checks; automatic rollback restored version ${previous_version}."
  fi
  die "Fresh deploy failed health checks and no authoritative rollback target exists."
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
  local requested_version="${1:-}"
  local recorded_version=""
  local rollback_version=""
  local backup_file=""

  check_swarm
  check_manager

  [[ -f "${PROJECT_ROOT}/.env" ]] || die ".env file not found"
  [[ -x "${HEALTH_CHECK_SCRIPT}" ]] || die "Health check script not found or not executable: ${HEALTH_CHECK_SCRIPT}"

  set -a; source "${PROJECT_ROOT}/.env"; set +a
  VERSION="${VERSION:-$(get_current_stack_version)}" docker compose -f "${COMPOSE_FILE}" config >/dev/null

  recorded_version="$(require_file_value "${PREVIOUS_VERSION_FILE}" "rollback target version marker")"
  rollback_version="${requested_version:-${recorded_version}}"

  if [[ "${rollback_version}" != "${recorded_version}" ]]; then
    die "Explicit rollback version ${rollback_version} does not match the recorded rollback marker ${recorded_version}; refusing unsafe rollback."
  fi

  VERSION="${rollback_version}" docker compose -f "${COMPOSE_FILE}" config >/dev/null

  backup_file="$(require_file_value "${ROLLBACK_BACKUP_FILE_MARKER}" "rollback backup marker")"
  [[ -f "${backup_file}" ]] || die "Recorded rollback backup file not found: ${backup_file}"

  rollback_to_version "${rollback_version}" "${backup_file}"
  mark_rolled_back_version "${rollback_version}"
}

main() {
  local action="${1:-}"

  shift || true

  case "${action}" in
    --init)    cmd_init "$@";;
    --join)    docker swarm join --token "$@";;
    --label)   cmd_label "$@";;
    --secrets) cmd_secrets;;
    --preflight) cmd_preflight;;
    --deploy)  cmd_deploy;;
    --status)  cmd_status;;
    --rollback) cmd_rollback "$@";;
    provision)
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
      log "Hardening server..."
      scp "${SCRIPT_DIR}/harden_server.sh" "${TARGET_HOST}:/tmp/harden_server.sh"
      ssh "${TARGET_HOST}" "chmod +x /tmp/harden_server.sh && sudo /tmp/harden_server.sh --yes"

      log "Installing Docker..."
      ssh "${TARGET_HOST}" 'bash -se' <<'REMOTE_DOCKER_INSTALL'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
DOCKER_APT_REPO_SIGNING_FINGERPRINT="9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
sudo apt-get update -qq
sudo apt-get install -y -qq ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
docker_key_tmp="$(mktemp)"
trap 'rm -f "${docker_key_tmp}"' EXIT
curl -fsSL "https://download.docker.com/linux/$(. /etc/os-release && echo "${ID}")/gpg" -o "${docker_key_tmp}"
docker_key_fingerprint="$(gpg --batch --show-keys --with-colons "${docker_key_tmp}" | awk -F: '/^fpr:/ {print $10; exit}')"
if [[ "${docker_key_fingerprint}" != "${DOCKER_APT_REPO_SIGNING_FINGERPRINT}" ]]; then
  echo "Unexpected Docker signing key fingerprint: ${docker_key_fingerprint}" >&2
  exit 1
fi
sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg "${docker_key_tmp}"
sudo chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME:-${UBUNTU_CODENAME:-}} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker "$(id -un)"
REMOTE_DOCKER_INSTALL

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
      echo "  --preflight        Validate labels, secrets, compose config, and manager Docker socket"
      echo "  --deploy           Deploy or update the stack"
      echo "  --status           Show stack status"
      echo "  --rollback [VER]   Redeploy the recorded previous version or an explicit version"
      echo "  provision HOST     Provision a new node (harden + Docker + join)"
      exit 1
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
