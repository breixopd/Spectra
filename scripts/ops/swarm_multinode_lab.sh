#!/usr/bin/env bash
# Multi-node Docker Swarm lab on a single host (Docker-in-Docker).
#
# Spins up one manager + N workers, deploys the Spectra stack, and prints join/status
# commands for validating cross-node scheduling, overlay networking, and admin
# server-pool flows without extra hardware.
#
# Usage:
#   ./scripts/ops/swarm_multinode_lab.sh up          # create cluster + deploy
#   ./scripts/ops/swarm_multinode_lab.sh status      # nodes, services, tasks
#   ./scripts/ops/swarm_multinode_lab.sh test-dns    # overlay DNS smoke
#   ./scripts/ops/swarm_multinode_lab.sh down        # tear down lab containers
#
# Requires: docker CLI, spectra images built (compose build or release images).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LAB_NET="${LAB_NET:-spectra-swarm-lab}"
MGR_NAME="${MGR_NAME:-spectra-dind-mgr}"
WORKER_PREFIX="${WORKER_PREFIX:-spectra-dind-w}"
WORKER_COUNT="${WORKER_COUNT:-2}"
DIND_IMAGE="${DIND_IMAGE:-docker:27-dind}"
STACK_NAME="${STACK_NAME:-spectra}"
COMPOSE_FILE="${PROJECT_ROOT}/deploy/docker/docker-compose.swarm.yml"
DEPLOY_SCRIPT="${PROJECT_ROOT}/scripts/ops/swarm_deploy.sh"

log() { echo "[swarm-lab] $*"; }
die() { echo "[swarm-lab] ERROR: $*" >&2; exit 1; }

docker_sock() {
  local name="$1"
  docker inspect -f '{{.Config.Env}}' "$name" 2>/dev/null | grep -q 'dockerd' || true
  echo "unix:///var/run/docker.sock"
}

dind_exec() {
  local name="$1"
  shift
  docker exec "$name" docker "$@"
}

lab_up() {
  docker network inspect "$LAB_NET" >/dev/null 2>&1 || docker network create "$LAB_NET" >/dev/null

  if ! docker ps -a --format '{{.Names}}' | grep -qx "$MGR_NAME"; then
    log "Starting manager $MGR_NAME"
    docker run -d --privileged --name "$MGR_NAME" --network "$LAB_NET" \
      -e DOCKER_TLS_CERTDIR= \
      -v "${MGR_NAME}-docker:/var/lib/docker" \
      "$DIND_IMAGE" >/dev/null
    sleep 8
  fi

  for i in $(seq 1 "$WORKER_COUNT"); do
    local wname="${WORKER_PREFIX}${i}"
    if docker ps -a --format '{{.Names}}' | grep -qx "$wname"; then
      continue
    fi
    log "Starting worker $wname"
    docker run -d --privileged --name "$wname" --network "$LAB_NET" \
      -e DOCKER_TLS_CERTDIR= \
      -v "${wname}-docker:/var/lib/docker" \
      "$DIND_IMAGE" >/dev/null
    sleep 5
  done

  if ! dind_exec "$MGR_NAME" info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q active; then
    log "Initializing Swarm on $MGR_NAME"
    dind_exec "$MGR_NAME" swarm init --advertise-addr "$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$MGR_NAME")" >/dev/null
  fi

  local token
  token="$(dind_exec "$MGR_NAME" swarm join-token worker -q)"
  local mgr_ip
  mgr_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$MGR_NAME")"

  for i in $(seq 1 "$WORKER_COUNT"); do
    local wname="${WORKER_PREFIX}${i}"
    if dind_exec "$wname" info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q active; then
      continue
    fi
    log "Joining $wname to Swarm"
    dind_exec "$wname" swarm join --token "$token" "${mgr_ip}:2377" >/dev/null || true
  done

  log "Nodes:"
  dind_exec "$MGR_NAME" node ls

  log "Deploy Spectra stack from manager DinD (images must exist in each daemon or use a registry)"
  log "Copy deploy env + run swarm_deploy inside manager:"
  echo "  docker cp ${PROJECT_ROOT}/.env ${MGR_NAME}:/tmp/spectra.env"
  echo "  docker exec ${MGR_NAME} sh -c 'apk add --no-cache bash curl openssl >/dev/null 2>&1 || true'"
  echo "  # Build/load images into each DinD or push to ${REGISTRY:-local} registry, then:"
  echo "  docker exec -e PROJECT_ROOT=/tmp ${MGR_NAME} ${DEPLOY_SCRIPT} --deploy"
}

lab_status() {
  dind_exec "$MGR_NAME" node ls || die "Manager $MGR_NAME not running"
  echo "--- services ---"
  dind_exec "$MGR_NAME" stack services "$STACK_NAME" 2>/dev/null || true
  echo "--- tasks (sample) ---"
  dind_exec "$MGR_NAME" stack ps "$STACK_NAME" --no-trunc 2>/dev/null | head -20 || true
}

lab_test_dns() {
  local svc
  svc="$(dind_exec "$MGR_NAME" service ls --filter "name=${STACK_NAME}_redis" --format '{{.Name}}' | head -1)"
  [[ -n "$svc" ]] || die "redis service not found — deploy the stack first"
  log "Running DNS probe task on overlay network"
  dind_exec "$MGR_NAME" run --rm --network "${STACK_NAME}_backend" alpine:3.20 \
    sh -c 'getent hosts redis || getent hosts tasks.redis || ping -c1 redis' || die "overlay DNS failed"
  log "Overlay DNS OK"
}

lab_down() {
  dind_exec "$MGR_NAME" stack rm "$STACK_NAME" 2>/dev/null || true
  for c in "$MGR_NAME" $(docker ps -a --format '{{.Names}}' | grep "^${WORKER_PREFIX}" || true); do
    docker rm -f "$c" 2>/dev/null || true
  done
  docker network rm "$LAB_NET" 2>/dev/null || true
  log "Lab torn down"
}

case "${1:-}" in
  up) lab_up ;;
  status) lab_status ;;
  test-dns) lab_test_dns ;;
  down) lab_down ;;
  *)
    echo "Usage: $0 {up|status|test-dns|down}"
    exit 1
    ;;
esac
