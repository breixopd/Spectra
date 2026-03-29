#!/usr/bin/env bash
# User Management CLI
# Usage: ./scripts/ops/user_management.sh <command> [options]
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-spectra-db}"
DB_USER="${DB_USER:-spectra}"
DB_NAME="${DB_NAME:-spectra}"
APP_CONTAINER="${APP_CONTAINER:-spectra-app}"

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

run_sql_result() {
    local query
    query="${1}"
    printf '%s\n' "${query}" | docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_NAME}" -tA
}

_hash_password() {
    local password
    password="${1}"

    printf '%s' "${password}" | docker exec -i "${APP_CONTAINER}" python3 -c "import sys; from app.core.security import get_password_hash; print(get_password_hash(sys.stdin.read()))"
}

prompt_for_password() {
    local context
    local password
    local password_confirm

    context="${1}"

    read -rsp "${context}: " password
    echo
    read -rsp "Confirm ${context,,}: " password_confirm
    echo

    if [[ -z "${password}" ]]; then
        echo "Error: password cannot be empty." >&2
        exit 1
    fi

    if [[ "${password}" != "${password_confirm}" ]]; then
        echo "Error: passwords do not match." >&2
        exit 1
    fi

    printf '%s' "${password}"
}

usage() {
    cat <<EOF
Spectra User Management CLI

Usage: $0 <command> [options]

Commands:
  list                                      List all users (id, username, email, role, active)
  info <username>                           Show detailed user info
    create-admin <user> <email>               Create a new admin user
  set-role <username> <role>                Change user role (admin|operator|viewer)
    reset-password <username>                 Reset user password
  disable-mfa <username>                    Disable MFA for a user (emergency recovery)
  delete <username>                         Delete a user account (requires confirmation)
EOF
}

case "${1:-}" in
    list)
        run_sql "SELECT id, username, email, role, is_active, mfa_enabled, created_at FROM users ORDER BY created_at;"
        ;;
    info)
        [[ -z "${2:-}" ]] && echo "Usage: ${0} info <username>" && exit 1
        USERNAME="${2}"
        ESCAPED_USERNAME="$(sql_escape "${USERNAME}")"
        RESULT="$(run_sql_result "SELECT username FROM users WHERE username = '${ESCAPED_USERNAME}';")"
        if [[ -z "${RESULT}" ]]; then
            echo "User '${USERNAME}' not found." >&2
            exit 1
        fi
        run_sql "SELECT id, username, email, role, is_active, mfa_enabled, email_verified, is_superuser, last_login, created_at, invalidated_before, failed_login_attempts FROM users WHERE username = '${ESCAPED_USERNAME}';"
        ;;
    create-admin)
        [[ -z "${3:-}" ]] && echo "Usage: ${0} create-admin <username> <email>" && exit 1
        USERNAME="${2}"
        EMAIL="${3}"
        PASSWORD="$(prompt_for_password "Admin password")"
        ESCAPED_USERNAME="$(sql_escape "${USERNAME}")"
        ESCAPED_EMAIL="$(sql_escape "${EMAIL}")"
        # Hash password using the app's Python hasher
        HASH="$(_hash_password "${PASSWORD}")"
        ESCAPED_HASH="$(sql_escape "${HASH}")"
        UUID="$(python3 -c "import uuid; print(str(uuid.uuid4()))")"
        run_sql "INSERT INTO users (id, username, email, hashed_password, role, is_active, is_superuser, email_verified) VALUES ('${UUID}', '${ESCAPED_USERNAME}', '${ESCAPED_EMAIL}', '${ESCAPED_HASH}', 'admin', true, true, true);"
        echo "Admin user '${USERNAME}' created."
        ;;
    set-role)
        [[ -z "${3:-}" ]] && echo "Usage: ${0} set-role <username> <admin|operator|viewer>" && exit 1
        USERNAME="${2}"
        ROLE="${3}"
        RESULT=""
        ESCAPED_USERNAME="$(sql_escape "${USERNAME}")"
        if [[ "${ROLE}" != "admin" && "${ROLE}" != "operator" && "${ROLE}" != "viewer" ]]; then
            echo "Error: role must be admin, operator, or viewer"
            exit 1
        fi
        IS_SUPER="false"
        [[ "${ROLE}" == "admin" ]] && IS_SUPER="true"
        RESULT="$(run_sql_result "UPDATE users SET role = '${ROLE}', is_superuser = ${IS_SUPER} WHERE username = '${ESCAPED_USERNAME}' RETURNING username;")"
        if [[ -z "${RESULT}" ]]; then
            echo "User '${USERNAME}' not found." >&2
            exit 1
        fi
        echo "User '${RESULT}' role set to '${ROLE}'."
        ;;
    reset-password)
        [[ -z "${2:-}" ]] && echo "Usage: ${0} reset-password <username>" && exit 1
        USERNAME="${2}"
        PASSWORD="$(prompt_for_password "New password")"
        RESULT=""
        ESCAPED_USERNAME="$(sql_escape "${USERNAME}")"
        HASH="$(_hash_password "${PASSWORD}")"
        ESCAPED_HASH="$(sql_escape "${HASH}")"
        RESULT="$(run_sql_result "UPDATE users SET hashed_password = '${ESCAPED_HASH}', invalidated_before = NOW(), failed_login_attempts = 0 WHERE username = '${ESCAPED_USERNAME}' RETURNING username;")"
        if [[ -z "${RESULT}" ]]; then
            echo "User '${USERNAME}' not found." >&2
            exit 1
        fi
        echo "Password reset for '${RESULT}'. All sessions invalidated."
        ;;
    disable-mfa)
        [[ -z "${2:-}" ]] && echo "Usage: ${0} disable-mfa <username>" && exit 1
        USERNAME="${2}"
        RESULT=""
        ESCAPED_USERNAME="$(sql_escape "${USERNAME}")"
        RESULT="$(run_sql_result "UPDATE users SET mfa_enabled = false, mfa_secret = NULL WHERE username = '${ESCAPED_USERNAME}' RETURNING username;")"
        if [[ -z "${RESULT}" ]]; then
            echo "User '${USERNAME}' not found." >&2
            exit 1
        fi
        echo "MFA disabled for '${RESULT}'."
        ;;
    delete)
        [[ -z "${2:-}" ]] && echo "Usage: ${0} delete <username>" && exit 1
        USERNAME="${2}"
        RESULT=""
        ESCAPED_USERNAME="$(sql_escape "${USERNAME}")"
        echo "⚠  This will permanently delete user '${USERNAME}' and all their data."
        read -rp "Type the username to confirm: " CONFIRM
        if [[ "${CONFIRM}" != "${USERNAME}" ]]; then
            echo "Aborted."
            exit 1
        fi
        RESULT="$(run_sql_result "DELETE FROM users WHERE username = '${ESCAPED_USERNAME}' RETURNING username;")"
        if [[ -z "${RESULT}" ]]; then
            echo "User '${USERNAME}' not found." >&2
            exit 1
        fi
        echo "User '${RESULT}' deleted."
        ;;
    *)
        usage >&2
        exit 1
        ;;
esac
