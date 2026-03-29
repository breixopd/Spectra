#!/usr/bin/env bash
# Backup and Restore CLI
# Usage: ./scripts/ops/backup_restore.sh <command>
set -euo pipefail

APP_CONTAINER="${APP_CONTAINER:-spectra-app}"

usage() {
    cat <<EOF
Spectra Backup & Restore CLI

Usage: $0 <command>

Commands:
  create              Create a new database backup (pg_dump → S3)
  list                List all backups stored in S3
  restore <backup_id> Restore database from an S3 backup (e.g. backup_20260329_120000)
  verify <backup_id>  Download and verify a backup file integrity
EOF
}

case "${1:-}" in
    create)
        echo "Creating database backup..."
        docker exec "$APP_CONTAINER" python3 -c "
import asyncio
from app.services.infrastructure.backup import BackupService
async def run():
    svc = BackupService()
    result = await svc.create_backup()
    print(f\"Status: {result['status']}\")
    if result['status'] == 'success':
        print(f\"Backup ID: {result['backup_id']}\")
        print(f\"S3 Key: {result['s3_key']}\")
        print(f\"Size: {result['size_bytes'] / 1024 / 1024:.1f} MB\")
    else:
        print(f\"Error: {result.get('error', 'unknown')}\")
asyncio.run(run())
"
        ;;
    list)
        echo "Backups in S3:"
        docker exec "$APP_CONTAINER" python3 -c "
import asyncio
from app.services.infrastructure.backup import BackupService
async def run():
    svc = BackupService()
    backups = await svc.list_backups()
    if not backups:
        print('  No backups found.')
        return
    for b in backups:
        print(f\"  {b['backup_id']}  {b['s3_uri']}\")
asyncio.run(run())
"
        ;;
    restore)
        [[ -z "${2:-}" ]] && echo "Usage: $0 restore <backup_id>" && exit 1
        BACKUP_ID="$2"
        echo "⚠  This will RESTORE the database from backup: $BACKUP_ID"
        echo "   All current data will be REPLACED."
        read -rp "Type 'restore' to confirm: " CONFIRM
        if [[ "$CONFIRM" != "restore" ]]; then
            echo "Aborted."
            exit 1
        fi
        echo "Restoring..."
        docker exec "$APP_CONTAINER" python3 -c "
import asyncio
from app.services.infrastructure.backup import BackupService
async def run():
    svc = BackupService()
    result = await svc.restore_backup('$BACKUP_ID')
    print(f\"Status: {result['status']}\")
    if result.get('error'):
        print(f\"Error: {result['error']}\")
    if result.get('restored_from'):
        print(f\"Restored from: {result['restored_from']}\")
asyncio.run(run())
"
        ;;
    verify)
        [[ -z "${2:-}" ]] && echo "Usage: $0 verify <backup_id>" && exit 1
        echo "Verifying backup: $2"
        docker exec "$APP_CONTAINER" python3 -c "
import asyncio, tempfile
from pathlib import Path
from app.services.storage.service import get_storage_service
from app.core.config import settings
async def run():
    storage = get_storage_service()
    key = f'backups/$2.dump'
    exists = await storage.exists(settings.S3_BUCKET_BACKUPS, key)
    if not exists:
        print(f'  Backup $2 not found in S3')
        return
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / 'verify.dump'
        await storage.download_file(settings.S3_BUCKET_BACKUPS, key, str(dest))
        size = dest.stat().st_size
        print(f'  Backup found: {size / 1024 / 1024:.1f} MB')
        # pg_restore --list to verify format
        import asyncio as aio
        proc = await aio.create_subprocess_exec(
            'pg_restore', '--list', str(dest),
            stdout=aio.subprocess.PIPE, stderr=aio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode == 0:
            table_count = sum(1 for l in out.decode().splitlines() if 'TABLE DATA' in l)
            print(f'  Format: valid custom dump ({table_count} tables)')
        else:
            print(f'  Format: INVALID — {err.decode()[:200]}')
asyncio.run(run())
"
        ;;
    *)
        usage
        ;;
esac
