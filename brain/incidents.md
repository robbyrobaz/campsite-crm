# Incidents Log

## 2026-03-27 20:06 MST — Moonshot Systemd Timeout (Fixed)

**Issue:** Cycle 195 killed by systemd after 4h timeout (TimeoutStartSec=14400)
- Cycle was working normally (fold 2 completed 19:46, killed 20:04)
- CPU time: 16h 34min over 4h wall time (4x from ML parallelism)
- Not a hang — continuous progress in logs

**Root cause:** Timeout too short for current ML workload (backtest folds taking >4h)

**Fix:** Increased TimeoutStartSec from 14400 (4h) to 21600 (6h)
- File: `/home/rob/.config/systemd/user/moonshot-v2.service`
- Applied: `systemctl --user daemon-reload`

**Validation:** Cycle 206 auto-restarted at 20:05, running normally

**Action:** Monitor next few cycles to confirm 6h is sufficient. If cycles still timeout, consider:
1. Increasing to 8h
2. Optimizing backtest fold performance
3. Reducing coin count or feature dimensionality

**Owner:** Jarvis (COO-level service health issue, Crypto Agent offline)
