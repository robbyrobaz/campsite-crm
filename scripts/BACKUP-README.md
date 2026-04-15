# OpenClaw Backup System

## Overview

Two complementary backup systems run on omen-claw:

| System | Script | Destination | Schedule |
|--------|--------|-------------|----------|
| Full workspace snapshot | `full-restore-backup.sh` | GitHub (`robbyrobaz/openclaw-full-restore`) | **Daily at midnight** |
| Database + data backup | `backup-all.sh` | `/mnt/data/backups/` (2nd HDD) | **Daily at 4am + Weekly Sunday 4am** |

The hourly `openclaw-backup.timer` was removed Apr 15 2026 — daily + weekly coverage is sufficient
and the hourly runs were filling the primary SSD.

---

## System 1: Full Workspace Snapshot (`full-restore-backup.sh`)

### What's backed up

Everything needed to rebuild OpenClaw from scratch:

| Path | Contents |
|------|----------|
| `workspace/` | All projects, scripts, memory, configs |
| `openclaw.json` | Gateway configuration |
| `identity/` | Device keys |
| `agents/` | Agent configs |
| `cron/` | Scheduled jobs |
| `credentials/` | Stored credentials |
| `exec-approvals.json` | Exec approval rules |

**Excluded:** `.git`, `.venv`, `node_modules`, `__pycache__`, `completions`, `subagents`, `backups`,
and repos that have their own GitHub remotes (blofin-stack, campsite-crm, NQ-Trading-PIPELINE, etc.)

### Schedule

Runs **daily at midnight** via systemd timer. Keeps last 5 snapshots locally.
Pushes to GitHub: [robbyrobaz/openclaw-full-restore](https://github.com/robbyrobaz/openclaw-full-restore)

### Known issue: archive size

The workspace snapshot is ~2.5GB compressed. GitHub pushes may timeout at 180s.
The prune (keep last 5) runs AFTER tar — if systemd kills the service before prune, old snapshots
accumulate and fill the SSD. Service timeout is set to 900s to mitigate this.

If snapshots pile up again: `ls -1t snapshots/*.tar.gz | tail -n +6 | xargs rm -f`

### Systemd units

```
~/.config/systemd/user/openclaw-full-restore-backup.timer    (daily at midnight)
~/.config/systemd/user/openclaw-full-restore-backup.service
~/.config/systemd/user/openclaw-full-restore-backup.service.d/timeout.conf  (900s)
```

---

## System 2: Database + Data Backup (`backup-all.sh`)

### What's backed up

**Daily (4am):** All SQLite + DuckDB databases + config archive
- NQ pipeline, blofin moonshot v2, blofin paper/live trading
- Go-trader state, OpenClaw memory (all profiles), Hermes state
- IBKR DuckDB feeds, SP500 pipeline DuckDB
- Config archive: openclaw.json, credentials, agent configs, .env files, session logs, systemd units

**Weekly (Sunday 4am):** Above + ML models + blofin_tickers/ohlcv parquet data + reef.db + blofin_monitor.db (29GB)

### Destination

All backups go to `/mnt/data/backups/` on the **secondary HDD** (916GB, ~16% full).

```
/mnt/data/backups/
  databases/
    hourly/    ← NOTE: hourly DB backup disabled Apr 15 2026
    daily/     ← active (keep 7 days)
    weekly/    ← active (keep 4 weeks)
    monthly/   ← promoted automatically (keep 3 months)
  config/
    daily/     ← active (keep 30 days)
  models/
    weekly/    ← active (keep 8 weeks)
  data/
    weekly/    ← blofin_tickers, blofin_ohlcv, reef.db (keep 4 weeks)
  manifest.json
  backup.log
```

### GFS Rotation (Grandfather-Father-Son)

- **Son (hourly):** disabled
- **Father (daily):** 7 days
- **Grandfather (weekly):** 4 weeks
- **Great-grandfather (monthly):** 3 months

Old hourly sets are automatically promoted to daily before deletion.

### Systemd units

```
~/.config/systemd/user/openclaw-backup-daily.timer     (daily at 4am)
~/.config/systemd/user/openclaw-backup-weekly.timer    (weekly Sunday 4am)
```

---

## Scripts

| Script | Purpose |
|--------|---------|
| `full-restore-backup.sh` | Creates workspace snapshot, pushes to GitHub |
| `full-restore-restore.sh` | Restores workspace from latest or specific snapshot |
| `backup-all.sh` | Comprehensive DB + data backup to /mnt/data |
| `backup-verify.sh` | Verifies backup integrity |
| `install-full-restore-backup-timer.sh` | (Re)installs full-restore systemd timer |

---

## Restoring

### Full workspace restore (from GitHub snapshot)
```bash
./scripts/full-restore-restore.sh
openclaw gateway restart
```

### From a specific local snapshot
```bash
./scripts/full-restore-restore.sh ~/.openclaw/backups/full-restore/repo/snapshots/workspace-20260413T193301Z.tar.gz
openclaw gateway restart
```

### Database restore
```bash
./scripts/blofin-db-restore.sh   # for blofin_monitor.db
# For others: gunzip the .db.gz and copy to original path
```

---

## Checking status

```bash
# Timer status
systemctl --user list-timers | grep backup

# Run full-restore backup manually
./scripts/full-restore-backup.sh

# Run database backup manually
./scripts/backup-all.sh --daily
./scripts/backup-all.sh --weekly

# Check backup log
tail -50 /mnt/data/backups/backup.log

# If snapshots pile up on SSD (check first):
du -sh ~/.openclaw/backups/full-restore/repo/snapshots/
ls -1t ~/.openclaw/backups/full-restore/repo/snapshots/*.tar.gz | wc -l
# Clean (keep 5 newest):
cd ~/.openclaw/backups/full-restore/repo
ls -1t snapshots/*.tar.gz | tail -n +6 | xargs rm -f
```

---

## History of changes

| Date | Change |
|------|--------|
| Feb 2026 | Initial backup system built |
| Mar 21 2026 | Full-restore snapshot last successfully pushed to GitHub |
| Apr 11 2026 | Full-restore timer restarted; git branch bug (master vs main) caused all pushes to fail silently |
| Apr 13 2026 | Branch bug fixed (`git init -b main`); orphan commit to clear 15GB of bloated git objects; snapshot excludes reverted to original |
| Apr 15 2026 | Hourly `openclaw-backup.timer` disabled; full-restore changed from every-2h to daily; service timeout raised 300s→900s |
