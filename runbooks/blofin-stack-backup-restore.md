# Runbook: Blofin Stack Backup / Restore

## Backup
```bash
cd /home/rob/.openclaw/workspace
chmod +x scripts/blofin-db-backup.sh
./scripts/blofin-db-backup.sh
```
Output files are written to:
- `/home/rob/.openclaw/workspace/blofin-stack/backups/`

## Restore
```bash
cd /home/rob/.openclaw/workspace
chmod +x scripts/blofin-db-restore.sh
./scripts/blofin-db-restore.sh /home/rob/.openclaw/workspace/blofin-stack/backups/blofin_monitor_YYYYMMDDTHHMMSSZ.sqlite3.gz
```
This procedure:
1. Stops `blofin-stack-api` and `blofin-stack-ingestor`
2. Restores DB file
3. Clears stale WAL/SHM sidecars
4. Restarts services

## Integrity check
```bash
sqlite3 /home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db 'PRAGMA integrity_check;'
curl -sS http://127.0.0.1:8780/api/summary | jq '.signals_total_window'
```
