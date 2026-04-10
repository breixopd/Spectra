#!/usr/bin/env bash
# Database Maintenance Script
# Usage: ./scripts/ops/db_maintenance.sh [vacuum|analyze|reindex|stats|sizes|all]
# ⚠ DEPRECATED (auto-maintenance) — The scheduler runs VACUUM ANALYZE
# automatically. Use this script for manual diagnostics, REINDEX, or
# one-off maintenance when the scheduler is unavailable.
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-spectra-db}"
DB_USER="${DB_USER:-spectra}"
DB_NAME="${DB_NAME:-spectra}"

run_sql() {
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "$1"
}

case "${1:-all}" in
    vacuum)
        echo "Running VACUUM ANALYZE..."
        run_sql "VACUUM ANALYZE;"
        ;;
    analyze)
        echo "Running ANALYZE..."
        run_sql "ANALYZE;"
        ;;
    reindex)
        echo "Running REINDEX DATABASE..."
        run_sql "REINDEX DATABASE $DB_NAME;"
        ;;
    stats)
        echo "Active connections:"
        run_sql "SELECT pid, usename, application_name, state, query_start, NOW() - query_start AS duration FROM pg_stat_activity WHERE datname = '$DB_NAME' ORDER BY query_start;"
        echo ""
        echo "Connection counts by state:"
        run_sql "SELECT state, count(*) FROM pg_stat_activity WHERE datname = '$DB_NAME' GROUP BY state;"
        echo ""
        echo "Table statistics:"
        run_sql "SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum, last_analyze FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 20;"
        ;;
    sizes)
        echo "Table sizes:"
        run_sql "SELECT tablename, pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size FROM pg_tables WHERE schemaname = 'public' ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC;"
        echo ""
        echo "Database size:"
        run_sql "SELECT pg_size_pretty(pg_database_size('$DB_NAME'));"
        ;;
    all)
        echo "=== Database Maintenance ==="
        "$0" stats
        echo ""
        "$0" sizes
        echo ""
        "$0" vacuum
        echo "=== Done ==="
        ;;
    *)
        echo "Usage: $0 [vacuum|analyze|reindex|stats|sizes|all]"
        exit 1
        ;;
esac
