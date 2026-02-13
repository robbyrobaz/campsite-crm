# OpenClaw Full Backup & Restore

## What's backed up

Everything needed to rebuild OpenClaw from scratch:

| Path | Contents |
|------|----------|
| `workspace/` | Files, memory, skills, projects, scripts |
| `openclaw.json` | Gateway configuration |
| `identity/` | Device keys |
| `agents/` | Agent configs |
| `cron/` | Scheduled jobs |
| `credentials/` | Stored credentials |
| `exec-approvals.json` | Exec approval rules |

**Excluded:** `.git`, `.venv`, `node_modules`, `__pycache__`, `completions`, `subagents`, `backups`

## Schedule

Backups run automatically **every 2 hours** via systemd timer.

- Snapshots stored locally in `~/.openclaw/backups/full-restore/snapshots/` (keeps last 12)
- Pushed to GitHub: [robbyrobaz/openclaw-full-restore](https://github.com/robbyrobaz/openclaw-full-restore) (keeps last 7)
- Uses Git LFS for large snapshot files

## Scripts

| Script | Purpose |
|--------|---------|
| `full-restore-backup.sh` | Creates snapshot and pushes to GitHub |
| `full-restore-restore.sh` | Restores from latest or specific snapshot |
| `install-full-restore-backup-timer.sh` | Sets up the systemd timer |

## Restoring

### From latest GitHub snapshot
```bash
./scripts/full-restore-restore.sh
openclaw gateway restart
```

### From a specific local snapshot
```bash
./scripts/full-restore-restore.sh ~/.openclaw/backups/full-restore/snapshots/workspace-20260212T181550Z.tar.gz
openclaw gateway restart
```

The restore script automatically backs up your current state before overwriting, so you can roll back if needed.

## Checking status

```bash
# Timer status
systemctl --user status openclaw-full-restore-backup.timer

# When next backup runs
systemctl --user list-timers openclaw-full-restore-backup.timer

# Run backup manually
./scripts/full-restore-backup.sh
```

## First-time setup

```bash
# Install git-lfs (required for snapshots >100MB)
sudo apt install git-lfs

# Install the systemd timer
./scripts/install-full-restore-backup-timer.sh
```
