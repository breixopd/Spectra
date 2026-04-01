#!/usr/bin/env bash
# Garage bootstrap script — run once after first start to set up layout, keys, and buckets.
# Usage: ./docker/garage-init.sh
set -euo pipefail

GARAGE_CONTAINER="${GARAGE_CONTAINER:-spectra-garage}"
GARAGE_ADMIN="http://localhost:3903"
BUCKETS=(spectra-missions spectra-sessions spectra-knowledge spectra-backups)

garage_exec() {
    docker exec "${GARAGE_CONTAINER}" /garage "$@"
}

echo "=== Garage S3 Bootstrap ==="

# ── Step 1: Wait for Garage to be healthy ──
echo "Waiting for Garage to be healthy..."
for i in $(seq 1 30); do
    if docker exec "${GARAGE_CONTAINER}" wget -qO- http://localhost:3903/health >/dev/null 2>&1; then
        echo "  Garage is healthy (attempt ${i})"
        break
    fi
    if [ "${i}" -eq 30 ]; then
        echo "ERROR: Garage did not become healthy in time" >&2
        exit 1
    fi
    sleep 2
done

# ── Step 2: Get node ID and assign layout ──
echo "Assigning layout..."
NODE_ID="$(garage_exec node id 2>/dev/null | head -1 | awk '{print $1}')"
if [ -z "${NODE_ID}" ]; then
    echo "ERROR: Could not determine Garage node ID" >&2
    exit 1
fi
garage_exec layout assign -z dc1 -c 1G "${NODE_ID}" 2>/dev/null || true

# ── Step 3: Apply layout ──
echo "Applying layout..."
garage_exec layout apply --version 1 2>/dev/null || echo "  Layout already applied or version conflict (non-fatal)"

# ── Step 4: Create access key ──
echo "Creating access key..."
KEY_OUTPUT="$(garage_exec key create spectra-app 2>/dev/null || true)"
if echo "${KEY_OUTPUT}" | grep -q "Key name: spectra-app"; then
    ACCESS_KEY="$(echo "${KEY_OUTPUT}" | grep 'Key ID:' | awk '{print $NF}')"
    SECRET_KEY="$(echo "${KEY_OUTPUT}" | grep 'Secret key:' | awk '{print $NF}')"
else
    echo "  Key 'spectra-app' may already exist, retrieving info..."
    KEY_OUTPUT="$(garage_exec key info spectra-app 2>/dev/null)"
    ACCESS_KEY="$(echo "${KEY_OUTPUT}" | grep 'Key ID:' | awk '{print $NF}')"
    SECRET_KEY="$(echo "${KEY_OUTPUT}" | grep 'Secret key:' | awk '{print $NF}')"
fi

# ── Step 5: Create buckets ──
echo "Creating buckets..."
for bucket in "${BUCKETS[@]}"; do
    garage_exec bucket create "${bucket}" 2>/dev/null || echo "  ${bucket} already exists"
    echo "  ✓ ${bucket}"
done

# ── Step 6: Grant key permissions on all buckets ──
echo "Granting permissions..."
for bucket in "${BUCKETS[@]}"; do
    garage_exec bucket allow --read --write --owner "${bucket}" --key spectra-app 2>/dev/null || true
    echo "  ✓ ${bucket} → spectra-app"
done

# ── Step 7: Output credentials for .env ──
echo ""
echo "=== Garage Bootstrap Complete ==="
echo ""
echo "Add these to your .env file:"
echo "  GARAGE_ACCESS_KEY=${ACCESS_KEY}"
echo "  GARAGE_SECRET_KEY=${SECRET_KEY}"
echo ""
