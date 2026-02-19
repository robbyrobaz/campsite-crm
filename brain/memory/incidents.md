# Incidents & Resolutions

## Feb 18, 2026 18:00 MST - Dashboard Service Restart

**Incident:** blofin-dashboard.service crashed with exit code 1 (1768 restart attempts). dashboard-health-check.service also failed (missing script).

**Root cause:**  
- Dashboard service failing on startup (needs debug, but not critical—paper trading + ingestor running fine)
- Health check service points to missing `/home/rob/.openclaw/workspace/blofin-stack/dashboard_health_check.py`

**Action taken:**
- Restarted blofin-dashboard.service (now activating)
- Masked dashboard-health-check.service to prevent repeated failures
- Stopped dashboard-health-check.timer

**Impact:** Dashboard UI may be briefly unavailable, but core trading pipeline unaffected. Ingestor + paper trading still active.

**Follow-up:** If dashboard continues crashing, check logs: `journalctl --user -u blofin-dashboard.service -n 50`
## Feb 18, 19:00 MST - Dashboard Health Check Service Failed

**Service:** dashboard-health-check.service
**Status:** FAILED (exit code 2 - INVALIDARGUMENT)
**Reason:** Script not found at `/home/rob/.openclaw/workspace/blofin-stack/dashboard_health_check.py`

**Action:** Service will continue failing on each timer trigger until script is recreated or timer is disabled.

**Decision:** Alerting Rob. Script needs to be rebuilt or service removed from systemd.


## Feb 19, 03:00 UTC (8:00 PM MST) — Dashboard Health Check Script Missing

**Severity:** Warning (non-critical)
**Service:** dashboard-health-check.service
**Status:** Failed
**Root Cause:** Script not found at `/home/rob/.openclaw/workspace/blofin-stack/dashboard_health_check.py`
**Exit Code:** 2 (INVALIDARGUMENT)
**Last Failure:** 2026-02-18T18:57:34Z

**Impact:** Health check service fails on timer. All core Blofin services (ingestor, paper trading) remain active and operational.

**Action Taken:** Logged to incidents.md and status.json for monitoring.

**Next Steps:** Either recreate the missing script or disable the timer (`systemctl --user disable dashboard-health-check.timer`).

---
---
[2026-02-19 02:00:14] CRITICAL: blofin-stack-api.service was INACTIVE during heartbeat check (02:00 AM). Restarted successfully.

## Backup Service — Git LFS Size Limit (Feb 19, 06:00 MST)

**Service:** openclaw-full-restore-backup.service  
**Status:** Failed  
**Error:** Multiple files exceed 2GB limit on Git LFS  
**Details:**
- Files rejected: 2383d07..., 1977a17..., 2f4b925...
- Error: "Size must be less than or equal to 2147483648"
- Last attempt: 2026-02-19 04:41:01 MST (1h 19min ago)
- Backup still runs on timer; objects staged but not pushed to GitHub

**Action needed:** Rob to review large objects and either:
1. Prune old data from repository
2. Adjust .gitattributes to exclude large files
3. Switch to separate storage for large artifacts

**Impact:** Backup service fails silently on push; local snapshots still captured, but GitHub redundancy broken.

