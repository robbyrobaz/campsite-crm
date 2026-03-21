# OpenClaw Backup System

**Status:** ✅ Operational (deployed Mar 21, 2026)

## Overview

Comprehensive 3-tier backup system protecting all critical data on omen-claw:

- **Tier 1 (Hourly):** All databases (SQLite + DuckDB) — 9 databases, ~5GB compressed
- **Tier 1 (Daily):** System configs, brain files, agent configs, .env files — ~100MB
- **Tier 2 (Weekly):** ML models + market data archives — ~2GB

**Total backup footprint:** 6GB (budget: 500GB, 99% available)

## Architecture

### Backup Storage
- **Location:** `/mnt/data/backups/` on 1TB SSD (903GB free)
- **Structure:**
  - `databases/hourly/` — DB backups, keep 24
  - `databases/daily/` — Promoted hourly → daily, keep 30
  - `config/daily/` — Config tarballs, keep 30
  - `models/weekly/` — ML model archives, keep 8
  - `data/weekly/` — Market data archives, keep 4
  - `manifest.json` — Metadata, timestamps, file list
  - `backup.log` — Operational log

### Database Backup Strategy

**SQLite databases (WAL-safe):**
- Uses `sqlite3 "$db" ".backup '$dest'"` — atomic, safe with active writes
- Compressed with gzip after backup
- Databases backed up:
  - `moonshot_v2.db` (~5.7GB → ~1.2GB compressed)
  - `moonshot.db` (~400MB → ~80MB compressed)
  - `kanban.sqlite` (~5MB)
  - `nq_pipeline.db` (~500KB)
  - `energy_data.db` (~1MB)
  - `blofin_monitor.db` (varies)

**DuckDB databases (copy-based):**
- Uses `cp` with `fuser` check (DuckDB has no `.backup` API)
- Waits 5s if file is open, then proceeds
- Databases backed up:
  - `nq_feed.duckdb` (~1.1GB → ~200MB compressed)
  - `sp500_pipeline.duckdb` (~20MB)
  - `ibkr_options.duckdb` (~1MB)

### Config Backup Contents

Single tarball containing:
- `~/.openclaw/openclaw.json`
- `~/.openclaw/identity/`, `credentials/`, `cron/`
- All 4 agent configs: `~/.openclaw/agents/{main,nq,crypto,church}/agent/`
- Workspace brain: `brain/`, `memory/`, `scripts/`, `runbooks/`
- Workspace docs: `*.md` (SOUL, AGENTS, IDENTITY, USER, TOOLS, MEMORY, HEARTBEAT)
- Systemd units: `~/.config/systemd/user/*.{service,timer}`
- All `.env` files (excluding .venv/)

### Retention Policy

| Tier | Frequency | Retention | Disk Budget |
|------|-----------|-----------|-------------|
| Databases | Hourly | 24 backups (~1 day) | ~90GB max |
| Configs | Daily | 30 backups (~1 month) | ~3GB max |
| Models | Weekly | 8 backups (~2 months) | ~16GB max |
| Data | Weekly | 4 backups (~1 month) | ~8GB max |

**Promotion:** Oldest hourly DB backup is promoted to daily on each daily run.

## Systemd Timers

### openclaw-backup.timer (Hourly)
- **Schedule:** Every hour (OnUnitActiveSec=1h)
- **First run:** 5 minutes after boot
- **Executes:** `backup-all.sh --hourly`
- **Timeout:** 600s (10 min)
- **Backs up:** Databases only

### openclaw-backup-daily.timer (Daily)
- **Schedule:** Daily at 3:00 AM MST
- **Executes:** `backup-all.sh --daily`
- **Timeout:** 900s (15 min)
- **Backs up:** Databases + configs

### openclaw-backup-weekly.timer (Weekly)
- **Schedule:** Every Sunday at 4:00 AM MST
- **Executes:** `backup-all.sh --weekly`
- **Timeout:** 3600s (1 hour)
- **Backs up:** Databases + configs + models + data

## Scripts

### `/home/rob/.openclaw/workspace/scripts/backup-all.sh`

Main backup orchestrator. Modes:

- `--hourly` (default): Databases only
- `--daily`: Databases + configs
- `--weekly`: Databases + configs + models + data (or auto-triggers if 7+ days since last)
- `--full`: Everything (manual use)
- `--verify`: Runs verification without creating backups

**Features:**
- Atomic SQLite backups via `.backup` command
- Gzip compression on all backups
- Automatic retention cleanup
- JSON manifest tracking
- Detailed logging to `/mnt/data/backups/backup.log`
- Graceful handling of in-use DuckDB files

### `/home/rob/.openclaw/workspace/scripts/backup-verify.sh`

Verification script checking:

- **Recency:** Hourly <2h, daily <26h, weekly <8d
- **Integrity:** `PRAGMA integrity_check` on SQLite backups
- **Disk usage:** /mnt/data/backups/ < 500GB
- **Archive validity:** tar integrity checks on config backups

**Exit codes:**
- 0 = OK
- 1 = WARN
- 2 = FAIL

**JSON output format:**
```json
{
  "status": "OK|WARN|FAIL",
  "timestamp": "2026-03-21T08:17:12-07:00",
  "backup_size_gb": 6,
  "details": [
    {"level": "OK|WARN|FAIL", "message": "..."}
  ]
}
```

## Operations

### Manual Backup

```bash
# Full backup (all tiers)
bash /home/rob/.openclaw/workspace/scripts/backup-all.sh --full

# Daily backup (DBs + configs)
bash /home/rob/.openclaw/workspace/scripts/backup-all.sh --daily

# Verify latest backups
bash /home/rob/.openclaw/workspace/scripts/backup-verify.sh
```

### Check Timer Status

```bash
# List all backup timers
systemctl --user list-timers openclaw-backup*

# Check last run
journalctl --user -u openclaw-backup.service --since "2 hours ago" --no-pager

# Check daily backup logs
journalctl --user -u openclaw-backup-daily.service --since "1 day ago" --no-pager
```

### Restore from Backup

**Database restore:**
```bash
# Decompress and restore SQLite
gunzip -c /mnt/data/backups/databases/hourly/moonshot_v2_TIMESTAMP.db.gz > /path/to/restore/moonshot_v2.db

# DuckDB same process
gunzip -c /mnt/data/backups/databases/hourly/nq_feed_TIMESTAMP.duckdb.gz > /path/to/restore/nq_feed.duckdb
```

**Config restore:**
```bash
# Extract config tarball
tar xzf /mnt/data/backups/config/daily/openclaw_config_TIMESTAMP.tar.gz -C /tmp/restore/

# Review contents
ls -la /tmp/restore/

# Selectively restore files as needed
cp -r /tmp/restore/openclaw/* ~/.openclaw/
cp -r /tmp/restore/workspace/* ~/.openclaw/workspace/
```

**Model restore:**
```bash
# Extract model archive
tar xzf /mnt/data/backups/models/weekly/blofin-moonshot-v2_models_TIMESTAMP.tar.gz -C /tmp/restore/

# Review and copy
cp -r /tmp/restore/models/* ~/.openclaw/workspace/blofin-moonshot-v2/models/
```

### Maintenance

**Check disk usage:**
```bash
du -sh /mnt/data/backups/
du -sh /mnt/data/backups/*/
```

**Clean up old backups manually (if needed):**
```bash
# Remove backups older than 30 days
find /mnt/data/backups/databases/hourly/ -type f -mtime +30 -delete
```

**Force a weekly backup:**
```bash
systemctl --user start openclaw-backup-weekly.service
```

## Heartbeat Integration

The backup system is monitored by Jarvis heartbeat cron (`HEARTBEAT.md`):

- **Every heartbeat:** Check all 3 timers are active
- **Every heartbeat:** Verify latest hourly backup < 2h old
- **Every heartbeat:** Check /mnt/data/backups/ < 500GB
- **Alert Rob if:** Timer inactive, backup stale, or disk over budget

## First Deployment (Mar 21, 2026)

✅ **Completed:**
- Created `backup-all.sh` and `backup-verify.sh`
- Installed 3 systemd timers (hourly, daily, weekly)
- Ran first full backup: 15 files, 4.9GB compressed
- Verification passed: all backups healthy
- Timers active and scheduled:
  - Next hourly: 37 minutes
  - Next daily: Sunday 3:00 AM
  - Next weekly: Sunday 4:00 AM

**Current backup inventory:**
- 18 hourly database backups
- 1 daily promoted backup
- 5 model archives (weekly tier)
- 1 data archive (blofin_tickers)
- 1 config archive (daily tier)

**Known issues fixed:**
- ✅ JSON manifest syntax (missing quotes on timestamps) — fixed with jq
- ✅ Config backup tar failures (tilde expansion) — fixed with $HOME expansion

## Safety Notes

1. **NEVER use `cp` on SQLite databases** — always use `sqlite3 .backup` command
2. **Check `fuser` before copying DuckDB files** — wait if in use
3. **Gzip everything** — storage is limited
4. **Log all operations** — debugging requires visibility
5. **Atomic operations** — use temp files, then move
6. **Verify before trusting** — run `backup-verify.sh` periodically

## Future Enhancements

- [ ] Off-site replication (S3/B2 for disaster recovery)
- [ ] Backup encryption (GPG before upload to cloud)
- [ ] Telegram notifications on backup failures
- [ ] Automated restore testing (quarterly)
- [ ] Incremental model backups (only changed files)
