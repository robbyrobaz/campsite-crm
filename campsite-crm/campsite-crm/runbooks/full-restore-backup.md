# Runbook: Full Restore Backup (GitHub snapshots)

## Purpose
Create real full-workspace snapshots and ensure restore works on a new laptop.

## Repo
- Private backup repo: `https://github.com/robbyrobaz/openclaw-full-restore`

## Scripts
- Backup: `scripts/full-restore-backup.sh`
- Restore: `scripts/full-restore-restore.sh`
- Timer install: `scripts/install-full-restore-backup-timer.sh`

## Setup / enable
```bash
cd /home/rob/.openclaw/workspace
chmod +x scripts/full-restore-backup.sh scripts/full-restore-restore.sh scripts/install-full-restore-backup-timer.sh
./scripts/install-full-restore-backup-timer.sh
```

## Manual backup now
```bash
./scripts/full-restore-backup.sh
```

## Restore test (required)
```bash
./scripts/full-restore-restore.sh /tmp/openclaw-restore-test
```

## Cadence
- Auto backup every 2 hours via user timer
- Also run manual backup before major changes

## Notes
- Snapshot excludes common cache/build dirs (`.git`, `.venv`, `node_modules`, `__pycache__`, `*.pyc`)
- Keeps latest 7 snapshot archives + checksums in backup repo
