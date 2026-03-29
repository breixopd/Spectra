#!/usr/bin/env bash
# User Management CLI
# Usage: ./scripts/ops/user_management.sh <command> [options]
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-spectra-db}"
DB_USER="${DB_USER:-spectra}"
DB_NAME="${DB_NAME:-spectra}"

run_sql() {
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "$1"
}

run_sql_result() {
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tA -c "$1"
}

usage() {
    cat <<EOF
Spectra User Management CLI

Usage: $0 <command> [options]

Commands:
  list                     List all users (id, username, email, role, active)
  info <username>          Show detailed user info
  create-admin <user> <email> <password>  Create a new admin user
  set-role <username> <role>              Change user role (admin|operator|viewer)
  reset-password <username> <new-password>  Reset user password
  disable-mfa <username>  Disable MFA for a user (emergency recovery)
  delete <username>        Delete a user account (requires confirmation)
EOF
}

case "${1:-}" in
    list)
        run_sql "SELECT id, username, email, role, is_active, mfa_enabled, created_at FROM users ORDER BY created_at;"
        ;;
    info)
        [[ -z "${2:-}" ]] && echo "Usage: $0 info <username>" && exit 1
        run_sql "SELECT id, username, email, role, is_active, mfa_enabled, email_verified, is_superuser, last_login, created_at, invalidated_before, failed_login_attempts FROM users WHERE username = '$2';"
        ;;
    create-admin)
        [[ -z "${4:-}" ]] && echo "Usage: $0 create-admin <username> <email> <password>" && exit 1
        USERNAME="$2"
        EMAIL="$3"
        PASSWORD="$4"
        # Hash password using the app's Python hasher
        HASH=$(docker exec spectra-app python3 -c "from app.core.security import get_password_hash; print(get_password_hash('$PASSWORD'))")
        UUID=$(python3 -c "import uuid; print(str(uuid.uuid4()))")
        run_sql "INSERT INTO users (id, username, email, hashed_password, role, is_active, is_superuser, email_verified) VALUES ('$UUID', '$USERNAME', '$EMAIL', '$HASH', 'admin', true, true, true);"
        echo "Admin user '$USERNAME' created."
        ;;
    set-role)
        [[ -z "${3:-}" ]] && echo "Usage: $0 set-role <username> <admin|operator|viewer>" && exit 1
        ROLE="$3"
        if [[ "$ROLE" != "admin" && "$ROLE" != "operator" && "$ROLE" != "viewer" ]]; then
            echo "Error: role must be admin, operator, or viewer"
            exit 1
        fi
        IS_SUPER="false"
        [[ "$ROLE" == "admin" ]] && IS_SUPER="true"
        run_sql "UPDATE users SET role = '$ROLE', is_superuser = $IS_SUPER WHERE username = '$2';"
        echo "User '$2' role set to '$ROLE'."
        ;;
    reset-password)
        [[ -z "${3:-}" ]] && echo "Usage: $0 reset-password <username> <new-password>" && exit 1
        HASH=$(docker exec spectra-app python3 -c "from app.core.security import get_password_hash; print(get_password_hash('$3'))")
        run_sql "UPDATE users SET hashed_password = '$HASH', invalidated_before = NOW(), failed_login_attempts = 0 WHERE username = '$2';"
        echo "Password reset for '$2'. All sessions invalidated."
        ;;
    disable-mfa)
        [[ -z "${2:-}" ]] && echo "Usage: $0 disable-mfa <username>" && exit 1
        run_sql "UPDATE users SET mfa_enabled = false, mfa_secret = NULL WHERE username = '$2';"
        echo "MFA disabled for '$2'."
        ;;
    delete)
        [[ -z "${2:-}" ]] && echo "Usage: $0 delete <username>" && exit 1
        echo "⚠  This will permanently delete user '$2' and all their data."
        read -rp "Type the username to confirm: " CONFIRM
        if [[ "$CONFIRM" != "$2" ]]; then
            echo "Aborted."
            exit 1
        fi
        run_sql "DELETE FROM users WHERE username = '$2';"
        echo "User '$2' deleted."
        ;;
    *)
        usage
        ;;
esac
