#!/usr/bin/env bash
# Garage bootstrap script — run once after first start to set up layout, keys, and buckets.
# Usage: ./docker/garage-init.sh
#
# NOTE: The app handles this automatically on first boot via StorageService._bootstrap_garage()
# when GARAGE_ADMIN_TOKEN is set.  This script is kept as a manual fallback / debugging tool.
set -euo pipefail

GARAGE_CONTAINER="${GARAGE_CONTAINER:-spectra-garage}"
BUCKETS=(spectra-missions spectra-sessions spectra-knowledge spectra-backups)
KEY_NAME="spectra-app"

garage_exec() {
    docker exec "${GARAGE_CONTAINER}" /garage "$@"
}

key_info() {
    garage_exec key info "$1" --show-secret 2>/dev/null || true
}

key_field() {
    printf '%s\n' "$1" | awk -F': ' -v field="$2" '$1 == field { sub(/^[[:space:]]+/, "", $2); print $2; exit }'
}

echo "=== Garage S3 Bootstrap ==="

# ── Step 1: Wait for Garage to be healthy ──
echo "Waiting for Garage to be healthy..."
for i in $(seq 1 30); do
    if garage_exec status >/dev/null 2>&1; then
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
NODE_ID="$(garage_exec status 2>/dev/null | awk '/^[0-9a-f]{16}[[:space:]]/ { print $1; exit }')"
if [ -z "${NODE_ID}" ]; then
    echo "ERROR: Could not determine Garage node ID" >&2
    exit 1
fi
garage_exec layout assign -z dc1 -c 1G "${NODE_ID}" >/dev/null 2>&1 || true

# ── Step 3: Apply layout ──
echo "Applying layout..."
for i in $(seq 1 30); do
    if garage_exec layout apply --version 1 >/dev/null 2>&1 || garage_exec key list >/dev/null 2>&1; then
        echo "  Layout is ready (attempt ${i})"
        break
    fi
    if [ "${i}" -eq 30 ]; then
        echo "ERROR: Garage layout did not become ready in time" >&2
        exit 1
    fi
    sleep 2
done

# ── Step 4: Create access key ──
if [ -n "${GARAGE_ACCESS_KEY:-}" ] && [ -n "${GARAGE_SECRET_KEY:-}" ]; then
    echo "Importing configured access key..."
    ACCESS_KEY="${GARAGE_ACCESS_KEY}"
    SECRET_KEY="${GARAGE_SECRET_KEY}"
    KEY_OUTPUT="$(key_info "${ACCESS_KEY}")"
    if [ -n "${KEY_OUTPUT}" ]; then
        if [ "$(key_field "${KEY_OUTPUT}" "Secret key")" != "${SECRET_KEY}" ]; then
            echo "ERROR: Garage access key ${ACCESS_KEY} already exists with a different secret" >&2
            exit 1
        fi
        if [ "${GARAGE_PRINT_CREDENTIALS:-1}" = "1" ]; then
            echo "  Access key ${ACCESS_KEY} already exists"
        else
            echo "  Access key already exists"
        fi
    else
        KEY_OUTPUT="$(key_info "${KEY_NAME}")"
        if [ -n "${KEY_OUTPUT}" ]; then
            if [ "$(key_field "${KEY_OUTPUT}" "Key ID")" != "${ACCESS_KEY}" ] || [ "$(key_field "${KEY_OUTPUT}" "Secret key")" != "${SECRET_KEY}" ]; then
                IMPORT_NAME="${KEY_NAME}-${ACCESS_KEY:0:8}"
                garage_exec key import --yes -n "${IMPORT_NAME}" "${ACCESS_KEY}" "${SECRET_KEY}" >/dev/null 2>&1 || true
                echo "  Imported configured access key with alternate name ${IMPORT_NAME}"
            else
                echo "  Key ${KEY_NAME} already matches configured credentials"
            fi
        else
            garage_exec key import --yes -n "${KEY_NAME}" "${ACCESS_KEY}" "${SECRET_KEY}" >/dev/null
            if [ "${GARAGE_PRINT_CREDENTIALS:-1}" = "1" ]; then
                echo "  Imported configured access key ${ACCESS_KEY}"
            else
                echo "  Imported configured access key"
            fi
        fi
    fi
else
    echo "Creating access key..."
    KEY_OUTPUT="$(garage_exec key create "${KEY_NAME}" 2>/dev/null || true)"
    if printf '%s\n' "${KEY_OUTPUT}" | grep -q "Key name: ${KEY_NAME}"; then
        ACCESS_KEY="$(key_field "${KEY_OUTPUT}" "Key ID")"
        SECRET_KEY="$(key_field "${KEY_OUTPUT}" "Secret key")"
    else
        echo "  Key '${KEY_NAME}' may already exist, retrieving info..."
        KEY_OUTPUT="$(key_info "${KEY_NAME}")"
        ACCESS_KEY="$(key_field "${KEY_OUTPUT}" "Key ID")"
        SECRET_KEY="$(key_field "${KEY_OUTPUT}" "Secret key")"
    fi
fi

# ── Step 5: Create buckets ──
echo "Creating buckets..."
for bucket in "${BUCKETS[@]}"; do
    garage_exec bucket create "${bucket}" >/dev/null 2>&1 || echo "  ${bucket} already exists"
    echo "  ✓ ${bucket}"
done

# ── Step 6: Grant key permissions on all buckets ──
echo "Granting permissions..."
for bucket in "${BUCKETS[@]}"; do
    garage_exec bucket allow --read --write --owner "${bucket}" --key "${ACCESS_KEY}" >/dev/null 2>&1 || true
    if [ "${GARAGE_PRINT_CREDENTIALS:-1}" = "1" ]; then
        echo "  ✓ ${bucket} → ${ACCESS_KEY}"
    else
        echo "  ✓ ${bucket}"
    fi
done

# ── Step 7: Output credentials for .env ──
echo ""
echo "=== Garage Bootstrap Complete ==="
echo ""
if [ "${GARAGE_PRINT_CREDENTIALS:-1}" = "1" ]; then
    echo "Add these to your .env file:"
    echo "  GARAGE_ACCESS_KEY=${ACCESS_KEY}"
    echo "  GARAGE_SECRET_KEY=${SECRET_KEY}"
    echo ""
else
    echo "Credentials suppressed (GARAGE_PRINT_CREDENTIALS=0)."
fi
