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

## Feb 20, 10:19 AM MST — Runaway Python Process (CPU 90°C)

**Severity:** CRITICAL
**PID:** 1028773 (python)
**CPU Usage:** 100% continuous for 76+ minutes
**CPU Temp:** 90°C (high threshold = 100°C, danger zone)
**Status:** Alerting Rob — awaiting kill/investigate decision

**Impact:** System thermal stress, risk of throttling or shutdown if continues
**Dispatcher action:** Sent alert via Telegram, halting dispatch until resolved

---

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


---

## Feb 19, 08:00 MST - Backup Service Still Failed (Persistent Git LFS Issue)

**Service:** openclaw-full-restore-backup.service
**Status:** Still FAILED (no change since 06:41 MST)
**Error:** Git LFS size limit exceeded
**Details:**
- Last failure: 2026-02-19 06:41:43 MST (1h 19min ago at heartbeat check)
- Same 4 objects still exceeding 2GB limit each
- Service remains in failed state; timer will retry next cycle

**Heartbeat Check:** 08:00 MST — Verified failure persists, status.json updated with warning.

**Note:** This is a persistent issue requiring manual intervention. Local snapshots continue, but GitHub backup is blocked.


---

## Feb 19, 14:00 MST - Heartbeat Check: Backup FAILED, API Service Missing

**Heartbeat Time:** 2026-02-19 09:00 MST (Arizona actual time)

**Issues Detected:**
1. **openclaw-full-restore-backup.service** — FAILED (persistent from 06:41 MST)
   - Error: Git LFS objects >2GB rejected by GitHub
   - Last run: 18 min ago, CPU time 4m 41s
   - Multiple objects (a1e7d5ad, 2383d07f, 1977a177, 2f4b925434) all rejected with "Size must be <= 2147483648"
   
2. **blofin-stack-api.service** — NOT INSTALLED
   - Unit file doesn't exist (exit code 5 on restart attempt)
   - Earlier query returned "inactive" — this is normal for non-existent services
   - Confirm: is this service supposed to be installed?

**System Status (OK):**
- CPU temp: 70.0°C ✓
- Disk: 53% ✓
- Gateway: active ✓
- Blofin ingestor: active ✓
- Blofin paper trading: active ✓
- Critical alerts: none ✓

**Action Taken:** status.json updated with warning flags. Backup service requires manual intervention (split large objects or prune DB). API service requires verification of intended config.

---

## Feb 19, 22:00 MST - Heartbeat Check: System OK, Numerai Process Exited

**Timestamp:** 2026-02-19T22:00:12Z

**Issues Detected:**
1. **Numerai era-boost process (PID 401561)** — exited or completed
   - Started at 21:01 UTC (14:01 MST)
   - No longer running; check if training completed or crashed
   - Last status: Training vanilla model on 304 features (v2_equivalent set)
   
2. **openclaw-full-restore-backup.service** — FAILED (persistent from 14:41)
   - Git LFS 2GB limit — expected, requires manual fix
   
3. **Minor failures (benign):**
   - gnome-remote-desktop.service (masked)
   - update-notifier-crash.service (notification spam)

**System Status (OK):**
- CPU temp: 59.0°C ✓
- Disk: 62% ✓
- Gateway: active ✓
- Blofin ingestor: active ✓
- Blofin paper trading: active ✓
- Critical alerts: none ✓

**Action Taken:** status.json updated. Numerai process moved to recentlyCompleted; awaiting verification of success/failure.

## Feb 19, 19:00 MST - Heartbeat: Backup Service Still Failed (Git LFS 2GB Limit)

**Timestamp:** 2026-02-19T19:00:00Z  
**Check Type:** Lightweight hourly heartbeat

**Issue Detected:**
- **Service:** openclaw-full-restore-backup.service
- **Status:** FAILED (persistent since 18:41 MST, ~19 min)
- **Error:** Git LFS size limit exceeded (2GB per-object limit)
- **Objects blocked:** Multiple large files (2383d07f, 1977a177, 2f4b925434, etc.)
- **CPU time:** 4m 50s before failure

**System Status (NOMINAL):**
- CPU temp: 63.0°C ✓
- Disk usage: 66% ✓
- Gateway: active ✓
- Blofin ingestor: active ✓
- Blofin paper trading: active ✓
- Critical alerts: none ✓

**Context:**  
This is a known issue (MEMORY.md: "Git LFS rejects >2GB objects"). Backup captures local snapshots but cannot push to GitHub due to per-object size limits. This was first logged Feb 19 at 06:41 MST and remains unresolved.

**Recommendation:** 
Manual intervention needed to either:
1. Prune old/large data from the repository
2. Update .gitattributes to exclude large files from Git LFS
3. Move large artifacts to separate storage (S3/GCS)

**Action Taken:** Alert sent to Rob. Monitoring continues on next heartbeat cycle.

## Feb 20, 2026 11:04 AM MST - CPU Temperature Critical

**Incident:** CPU temp reached 87°C (threshold: 85°C). Runaway Python process detected.

**Details:**
- CPU temp: 87.0°C (high = 100°C)
- Runaway process: PID 1100155, 100% CPU utilization, 1:15 runtime
- Load average: 2.30
- All core services active (gateway, ingestor, paper trading)
- Disk: 37% (OK)
- Critical alerts: none

**Action taken:**
- Alerted Rob via ntfy.sh (urgent priority)
- Updated status.json with critical flag
- Did NOT kill process (awaiting Rob's instruction)
- Continuing dispatcher work (system still operational)

**Follow-up:** Rob to investigate and kill runaway process manually. Monitor next cycles.

## Feb 20, 22:20 MST - numerai-daily-bot restart attempted during heartbeat

**Service:** numerai-daily-bot.service
**Status before action:** failed
**Action taken:** `systemctl --user restart numerai-daily-bot.service --no-block`
**Immediate result:** service entered `activating` state, but prior failure cause remains (`FileNotFoundError: models_elite` / missing `manifest_*`).
**Follow-up needed:** restore `numerai-tournament/models_elite/manifest_*` artifacts so daily submission can complete.

## Feb 20, 22:42 MST - heartbeat restart: numerai-daily-bot

**Service:** numerai-daily-bot.service
**State detected:** failed during heartbeat
**Action:** restarted with `systemctl --user restart numerai-daily-bot.service --no-block`
**Immediate state:** activating (known blocker may persist: missing models_elite manifests)

## Feb 21, 06:15 MST - numerai-daily-bot restart during heartbeat

**Service:** numerai-daily-bot.service
**Detected state:** failed
**Action:** restarted with `systemctl --user restart numerai-daily-bot.service --no-block`
**Immediate result:** activating

## Jarvis Google Account (2026-02-22)
- Email: jarvis.is.my.coo@gmail.com
- Password: is$$sseljs21
- Has gcloud CLI access (already authenticated)
- Has Google Cloud Console access via browser
- Projects: ml-trading-431520, campsite-crm-app
- NOTE: Rob gave this account to Jarvis. Stop asking Rob for help with it.

## 2026-02-28 09:13 MST — nq-dashboard orphan process
nq-dashboard.service was inactive because dashboard/app.py was running as an orphan process (PID 2755259) outside systemd control, holding port 8891. Dashboard was serving 200 OK but not managed by systemd. Killed orphan, restarted service — now active under systemd.

## 2026-03-01 07:05 MST — Stale Card Recovery + nq-smb-watcher restart
- **nq-smb-watcher.service** was inactive — restarted, now active
- **2 stale In Progress cards** (both ~82 min since update, no builder processes running):
  - c_258010dbe46fd: "Test local LLM models..." — recovered to Planned, redispatched (pid 6092)
  - c_a535fc5537933: "moonshot data..." — recovered to Planned, redispatched (pid 5939)
- Blofin services all active, dashboard 200 OK
- Critical alert check: EXIT 0 (no alerts)

## 2026-03-01 08:04 MST — nq-smb-watcher Down (Expected)
- Service: nq-smb-watcher.service
- Reason: /mnt/nt_bridge not mounted (NinjaTrader bridge disconnected)
- Action: Restart attempted, failed with exit code 1
- Status: Expected on weekends when NT not running
- No action needed unless Rob wants live forward testing

## 2026-03-01 09:34 MST — nq-smb-watcher Recovery (SMB Mount Restored)
- Service: nq-smb-watcher.service — was in auto-restart loop (475 attempts), exit code 1
- Root cause: /mnt/nt_bridge mount point was stale/unmounted
- Action: Remounted SMB share via `sudo mount /mnt/nt_bridge` (fstab configured with nofail)
- Result: Mount restored, service restarted successfully, now active
- Status: nq-smb-watcher.service = active, nq-dashboard.service = active

## 2026-03-01 10:04 MST — NQ Services Found Inactive, Restarted
- **Incident Time:** Jarvis Pulse (Dispatch) cycle at 10:04 AM MST
- **Services:** nq-smb-watcher.service and nq-dashboard.service were INACTIVE
- **Action:** Restarted both services: `systemctl --user restart nq-smb-watcher.service nq-dashboard.service`
- **Verification:** Both services now ACTIVE after restart
- **Dashboard:** HTTP 200 OK (verified)
- **Note:** Services may have been killed/crashed between 09:34 and 10:04 (30-min cycle), or systemd restart from overnight. Cause unclear. Monitoring next cycles.
- **Impact:** Trading dashboards briefly unavailable during restart (~2-3 sec), but no data loss (ingestor independent)

---

## Dispatch Cycle — Sunday, March 1st 10:34 AM

**Status:** HEALTHY

- **Health Check:** CPU 79°C, disk 36%, all 5 services ACTIVE
- **Critical Alerts:** 0
- **Dispatch:** Jarvis home energy analysis card → dispatched (PID 335162)
- **Stale Recovery:** none (0 In Progress at start)
- **Deployment Verification:**
  - Moonshot Feature Engineering (9.5 min old): DEPLOYED ✓
  - ML Training Overhaul (12.4 min old): DEPLOYED ✓
  - Jarvis home cache (13.2 min old): **jarvis-home-energy.service WAS INACTIVE** → restarted, dashboard 200 ✓
- **Action:** Restarted `jarvis-home-energy.service` (was inactive despite code change 13 min prior)
- **Impact:** Energy service briefly restarted; data collection continuous

## Dispatch Cycle — Sunday, March 1st 6:05 PM

**Status:** HEALTHY (post-restart)

- **Health Check:** CPU 67°C, disk 36%, services: gateway/blofin-ingestor/blofin-paper/nq-dashboard ACTIVE, **nq-smb-watcher INACTIVE**
- **Action:** Restarted nq-smb-watcher.service — now ACTIVE
- **Critical Alerts:** EXIT 0 (none)
- **Proceeding to Phase 3 (board state fetch)**


## Mar 1, 2026 21:35 MST - Moonshot Dashboard Service Inactive After Deployment

**Incident:** Card `c_7dd2153801f0c_19cacb5843e` completed (4h cycle timer fix). Dispatcher Phase 7 verification found `blofin-moonshot-dashboard.service` inactive, dashboard unreachable (HTTP 0).

**Root cause:** Service killed or crashed after code deployment. Cause unknown — no logs checked yet.

**Action taken:**
- Restarted `blofin-moonshot-dashboard.service` (now active)
- Verified HTTP 200 on http://127.0.0.1:8893/
- Card now deployed successfully

**Impact:** 30-minute gap where dashboard was offline. Live models may not have been updated until restart.

**Follow-up:** Check journalctl for why it exited: `journalctl --user -u blofin-moonshot-dashboard.service -n 50 --since "30 min ago"`

## 2026-03-03 09:09 — Moonshot Timer Inactive

**Service:** blofin-moonshot.timer
**Severity:** Medium (impacts automated model retraining)
**Root Cause:** Timer stopped running after Moonshot retraining completed (card c_b959bee463d4d_19cb3ca9af6)
**Action Taken:** Restarted and enabled blofin-moonshot.timer
**Status:** ✓ Resolved

The timer was not active, which would have prevented the 4h training cycle from running. This was caught during deployment verification and fixed.

## 2026-03-03 19:16 MST — Moonshot Service Missing + Strategy Registration Failures

**Incident Time:** Jarvis Pulse (Dispatch) — 19:16 MST (7:16 PM)

**Issues Detected:**

1. **blofin-moonshot.service** — NOT ACTIVE
   - Service unit file missing (not-found)
   - Process killed 2h 45min ago (16:31 MST) with SIGTERM
   - Service was running but terminated, unit file no longer exists
   - Status: FAILED (Result: signal) — will not restart automatically
   - **Impact:** Moonshot model training stopped; positions may not be updating

2. **Strategy Registration Failures (Silent Deployments):**
   - Card: "[NQ] New Strategy: zscore_from_vwap — WR=89.7%, PF~8.74"
     - Status: Done (updated 1 sec ago)
     - Registry check: **NOT FOUND** in strategy_registry
     - Deployment failed silently; card marked Done but work not deployed
   
   - Card: "[Blofin] New Strategy: mtf_ensemble_gate — WR=56.0%, PF=1.27"
     - Status: Done (updated 1 sec ago)
     - Registry check: **NOT FOUND** in strategy_registry
     - Deployment failed silently; card marked Done but work not deployed

3. **Moonshot FT Scorer Fix** — Partial Deployment
   - Card: "[Moonshot] Fix FT scorer: 'could not convert string to float: price_vs_52w_high'"
   - Status: Done (updated 1 sec ago)
   - Service status: Inactive (no service unit to verify)
   - Impact: Code changes may exist but not running due to missing service

**System Status (Otherwise Healthy):**
- CPU: 86°C (within limits)
- Disk: 48% (OK)
- Gateway: active ✓
- Blofin ingestor: active ✓
- Blofin paper: active ✓
- NQ dashboard: HTTP 200 ✓
- Critical alerts: EXIT 0 ✓

**Action Required:**
1. Recreate or restore blofin-moonshot.service unit file
2. Investigate why strategy registrations complete without actually registering (likely builder deployment step failing silently)
3. Verify the 2 builder outputs — code may exist but not deployed to registry

**Dispatcher Decision:** All 3 In Progress cards still active (last updated 5 min ago). Awaiting Rob's guidance on service restoration before restarting builders.

## 2026-03-03 20:55 MST — Dispatch Cycle: Moonshot Service Still Missing

**Verification Phase:** Deployment verification attempted for completed card "[Moonshot] Analyze position exit efficiency"

**Finding:** blofin-moonshot.service still missing (unit file not found, service not installed)
- Attempted restart: Failed with "Unit not found" (exit code 5)
- Attempted unmask: Service was masked, unmasking succeeded but revealed unit file completely absent
- Timer status: blofin-moonshot.timer also inactive

**Impact:** 
- Card marked Done but deployment could not be verified
- Moonshot training/position management offline
- Related Planned card ("[Moonshot] Verify 4h cycle timer") dispatched (PID 604380) to investigate root cause

**Status:** Escalating to Rob via ntfy. Dispatcher continuing with 2 additional builders active (at 3-builder cap).

## 2026-03-03 23:55 — Moonshot Service Restart
**Card:** c_fa2d2eebc7f31_19cb7704398 (4h cycle timer validation)  
**Issue:** Service was inactive post-deployment, restarted.  
**Status:** Now initializing (Phase 2 running), dashboard HTTP 200.  
**Action:** None needed, service recovering normally.

- 2026-03-04 06:26 MST — Dispatcher deployment verification found recently Done cards completed without post-completion service reloads. Restarted: nq-smb-watcher.service, nq-dashboard.service, blofin-stack-ingestor.service, blofin-stack-paper.service, blofin-dashboard.service. Verified dashboards HTTP 200.
- 2026-03-04 06:27 MST — Dispatcher attempted to run 6 planned cards; kanban runner sessions immediately failed with Claude seven_day rate-limit rejection ("You've hit your limit · resets Mar 5, 9pm"). Cards auto-returned to Planned; no active builders.

- 2026-03-04T20:40:35 Recovered stale card to Planned: [NQ] Sweep eight_am_break_retest variants to increase trade frequency and select… (c_93c123e59eaec_19cbb574d19) after 39.6m without updates.
2026-03-04T21:40:47.201597 Restarted Jarvis Home service for done card c_1891fc4059522_19cb5bc7bb1
2026-03-04T21:40:52.937490 Deployment verification: attempted restart of jarvis-home.service but unit not found; needs service name/path validation.
