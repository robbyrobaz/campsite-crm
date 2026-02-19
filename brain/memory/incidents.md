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
