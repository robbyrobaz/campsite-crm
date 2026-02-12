# Runbook: Auto Code Backup Sync

## Purpose
Continuously back up active code/docs to `robbyrobaz/openclaw-2nd-brain` so in-progress work is recoverable.

## What it syncs
- `blofin-stack/`
- `scripts/`
- `systemd/`
- `runbooks/`
- `projects/`
- `memory/`
- `README.md`, `.gitignore`

## Services
- `auto-code-backup-sync.service`
- `auto-code-backup-sync.timer` (every 10 minutes)

## Install/enable
```bash
cd /home/rob/.openclaw/workspace
chmod +x scripts/auto-code-backup-sync.sh
./scripts/install-blofin-stack-services.sh
```

## Manual run now
```bash
/home/rob/.openclaw/workspace/scripts/auto-code-backup-sync.sh
```

## Verify
```bash
systemctl --user status auto-code-backup-sync.timer --no-pager
journalctl --user -u auto-code-backup-sync.service -n 100 --no-pager
```
