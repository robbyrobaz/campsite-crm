# Runbook: 2nd Brain Offsite Backup (knowledge-base)

## Purpose
Maintain a real offsite copy of `knowledge-base/` with verification so this laptop is not the single point of failure.

## What this uses
- Transport: `rsync` over `ssh`
- Script: `knowledge-base/scripts/offsite-backup.sh`
- Config template: `knowledge-base/scripts/offsite-backup.env.example`
- Local config (not committed): `knowledge-base/scripts/offsite-backup.env`

## 1) One-time setup

1. Copy template and edit values:
   ```bash
   cp knowledge-base/scripts/offsite-backup.env.example knowledge-base/scripts/offsite-backup.env
   ${EDITOR:-nano} knowledge-base/scripts/offsite-backup.env
   ```
2. Fill required fields:
   - `OFFSITE_SSH_USER`
   - `OFFSITE_SSH_HOST`
   - `OFFSITE_DEST_BASE`
3. Optional hardening:
   - Set `OFFSITE_SSH_KEY` to dedicated backup key.
   - Set `OFFSITE_KNOWN_HOSTS` to pin host key checking.
4. Confirm config parses correctly:
   ```bash
   ./knowledge-base/scripts/offsite-backup.sh check-config
   ```

## 2) Run backup

- Normal sync:
  ```bash
  ./knowledge-base/scripts/offsite-backup.sh backup
  ```

- Preview only (no writes):
  ```bash
  ./knowledge-base/scripts/offsite-backup.sh backup --dry-run
  ```

## 3) Verify backup integrity

Use checksum verification to confirm remote files match local content:

```bash
./knowledge-base/scripts/offsite-backup.sh verify
```

Expected success line:

- `[verify] OK: offsite copy matches local checksums`

If drift is detected, re-run backup, then verify again.

## 4) Restore test (quarterly)

Run a real restore drill to a throwaway directory.

1. Create restore destination:
   ```bash
   mkdir -p /tmp/kb-restore-test
   ```
2. Pull from offsite:
   ```bash
   source knowledge-base/scripts/offsite-backup.env
   rsync -a -e "ssh -p ${OFFSITE_SSH_PORT:-22}" \
     "${OFFSITE_SSH_USER}@${OFFSITE_SSH_HOST}:${OFFSITE_DEST_BASE}/${OFFSITE_BACKUP_LABEL:-$(hostname -s)}/" \
     /tmp/kb-restore-test/
   ```
3. Compare restored copy with local source:
   ```bash
   rsync -a --delete --checksum --dry-run knowledge-base/ /tmp/kb-restore-test/
   ```
4. Pass criteria:
   - No file drift reported by checksum comparison.
5. Clean up test restore:
   ```bash
   rm -rf /tmp/kb-restore-test
   ```

## Operational cadence
- After major note updates: run `backup`.
- Daily/weekly: run `verify`.
- Quarterly: run restore test.

## Troubleshooting quick hits
- SSH auth errors: validate key path/permissions and host reachability.
- Host key warnings: configure `OFFSITE_KNOWN_HOSTS` and update pinned key.
- Unexpected deletes: always run `backup --dry-run` before first run against a new remote path.
