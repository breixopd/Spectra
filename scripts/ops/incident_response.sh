#!/usr/bin/env bash
# Incident Response Script
# Usage: ./scripts/ops/incident_response.sh <command> [options]
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-spectra-db}"
DB_USER="${DB_USER:-spectra}"
DB_NAME="${DB_NAME:-spectra}"

sql_escape() {
    local value
    local quote
    value="${1}"
    quote="'"
    printf '%s' "${value//${quote}/${quote}${quote}}"
}

run_sql() {
    local query
    query="${1}"
    printf '%s\n' "${query}" | docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_NAME}"
}

usage() {
    cat <<EOF
Spectra Incident Response Toolkit

Usage: $0 <command>

Session Management:
  invalidate-all-sessions     Invalidate all user sessions (force re-login)
  invalidate-user <username>  Invalidate sessions for a specific user
  lock-user <username>        Lock a user account (prevent login)
  unlock-user <username>      Unlock a user account

Mission Control:
  kill-missions               Mark all running missions as cancelled
  kill-mission <id>           Cancel a specific mission

System:
  lockdown                    Emergency lockdown: disable registration + lock all non-admin users
  lift-lockdown               Reverse lockdown: unlock all users
  audit-recent [minutes]      Show recent audit log entries (default: 60 min)
  active-sessions             Show all active (non-expired) sessions
EOF
}

case "${1:-}" in
    invalidate-all-sessions)
        echo "⚠  Invalidating ALL user sessions..."
        run_sql "UPDATE users SET invalidated_before = NOW();"
        echo "Done. All users must re-login."
        ;;
    invalidate-user)
        [[ -z "${2:-}" ]] && echo "Usage: $0 invalidate-user <username>" && exit 1
        local safe_username
        safe_username=$(sql_escape "$2")
        echo "Invalidating sessions for user: $2"
        run_sql "UPDATE users SET invalidated_before = NOW() WHERE username = '${safe_username}';"
        echo "Done."
        ;;
    lock-user)
        [[ -z "${2:-}" ]] && echo "Usage: $0 lock-user <username>" && exit 1
        local safe_username
        safe_username=$(sql_escape "$2")
        echo "Locking user: $2"
        run_sql "UPDATE users SET is_active = false WHERE username = '${safe_username}';"
        echo "Done. User '$2' is now locked."
        ;;
    unlock-user)
        [[ -z "${2:-}" ]] && echo "Usage: $0 unlock-user <username>" && exit 1
        local safe_username
        safe_username=$(sql_escape "$2")
        echo "Unlocking user: $2"
        run_sql "UPDATE users SET is_active = true WHERE username = '${safe_username}';"
        echo "Done."
        ;;
    kill-missions)
        echo "⚠  Cancelling ALL running missions..."
        run_sql "UPDATE missions SET status = 'cancelled' WHERE status IN ('running', 'pending', 'paused');"
        echo "Done. Restart app to clean up in-memory state."
        ;;
    kill-mission)
        [[ -z "${2:-}" ]] && echo "Usage: $0 kill-mission <mission-id>" && exit 1
        local safe_id
        safe_id=$(sql_escape "$2")
        echo "Cancelling mission: $2"
        run_sql "UPDATE missions SET status = 'cancelled' WHERE id = '${safe_id}';"
        echo "Done."
        ;;
    lockdown)
        echo "🔒 EMERGENCY LOCKDOWN"
        echo "Disabling public registration..."
        run_sql "UPDATE runtime_settings SET value = 'false' WHERE key = 'ALLOW_REGISTRATION';"
        echo "Locking all non-admin users..."
        run_sql "UPDATE users SET is_active = false WHERE role != 'admin';"
        echo "Lockdown active. Only admin accounts can access the system."
        ;;
    lift-lockdown)
        echo "Lifting lockdown..."
        run_sql "UPDATE users SET is_active = true;"
        run_sql "UPDATE runtime_settings SET value = 'true' WHERE key = 'ALLOW_REGISTRATION';"
        echo "All users unlocked, registration re-enabled."
        ;;
    audit-recent)
        MINUTES="${2:-60}"
        if ! [[ "$MINUTES" =~ ^[0-9]+$ ]]; then
            echo "Error: MINUTES must be a positive integer" >&2
            exit 1
        fi
        echo "Audit log entries (last ${MINUTES} minutes):"
        run_sql "SELECT created_at, user_id, action, resource_type, details FROM audit_logs WHERE created_at > NOW() - INTERVAL '${MINUTES} minutes' ORDER BY created_at DESC LIMIT 100;"
        ;;
    active-sessions)
        echo "Users with valid sessions (not invalidated):"
        run_sql "SELECT id, username, email, role, CASE WHEN invalidated_before IS NULL THEN 'valid' ELSE 'relogin_required' END AS session_state, invalidated_before, login_fail_count, locked_until, created_at FROM users WHERE is_active = true ORDER BY invalidated_before NULLS FIRST, created_at DESC;"
        ;;
    *)
        usage
        ;;
esac
