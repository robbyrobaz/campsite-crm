# Moonshot v2 — Autonomous Operation Plan

**Owner:** Jarvis (COO)  
**Last Updated:** 2026-03-14 07:40 MST

## Goal
Find 1-5 models that earn **The Vault** status (get real money allocation). The tournament runs 24/7 with 3x leverage on paper trades. 95% of models should fail — we only care about finding winners FAST.

## Current State (Post-Fixes)
- **146 FT models** (down from 156, cleanup working)
- **1 champion** (de44f72dbb01, short, FT PF 2.22)
- **Long direction disabled** (labels correct, but no models pass gates)
- **OOM fixes deployed** (batched backtest loading)
- **Champion promotion gates fixed** (must pass BT + FT gates)
- **Feature JSON fixed** (INVALIDATION exits working)

## Autonomous Monitoring (Every 2h via HEARTBEAT.md)

### Service Health
- `moonshot-v2-dashboard.service` must be active (port 8893)
- Dashboard must return HTTP 200

### Cycle Completion
- Check last 8h of logs for "Cycle started" + "Cycle done"
- If cycle started but never completed → **OOM or hang, alert Rob**

### FT Backlog
- Count FT models: should stay ≤30 after cleanup
- If >50 → **FLAG** "FT backlog growing, demotion not working"

### Champion Health
- Verify champion exists
- If champion FT PF <1.5 after 200+ trades → **FLAG** "Champion underperforming"

### DB Size
- Alert if >10GB (label/candle bloat)

## Cron Schedule

| Timer | Schedule | Purpose |
|-------|----------|---------|
| **moonshot-v2.timer** | Every 4h at :05 (00,04,08,12,16,20:05) | Main cycle: discovery → candles → features → labels → execution → tournament |
| **moonshot-v2-social.timer** | Every 1h at :30 | Social data collection (Fear & Greed, CoinGecko trending, RSS, Reddit, GitHub) |
| **moonshot-v2-dashboard.service** | Always-on | Flask dashboard on port 8893 |

## Config Changes Apply Automatically
All fixes deployed today (FT threshold, champion gates, OOM batching, long disabled) are in `config.py` and code. They apply on next cycle — no service restart needed.

**Next cycle with new config:** 8:05 AM MST (Saturday, March 14)

## Success Metrics (30 days)

| Metric | Current | Target |
|--------|---------|--------|
| **Vault candidates** | 1 (short champion) | 3-5 (long + short) |
| **FT models active** | 146 | 10-20 |
| **Champion FT PF** | 2.22 | 2.5+ |
| **Cycles without OOM** | 0/last 3 | 20/20 |
| **Avg FT PnL (top 5)** | +0.40 | +1.0 |

## What Jarvis Owns

1. **Daily health check** via HEARTBEAT.md (every 2h)
2. **Auto-restart failed services** (dashboard, timers)
3. **Flag stale FT models** if backlog grows
4. **Monitor champion performance** and flag if degrading
5. **Detect OOM kills** and create fix cards if recurring
6. **Git commit Moonshot changes** during periodic sweeps

## What Rob Owns

1. **Capital allocation** to Vault models (final approval)
2. **Live trading activation** (BLE)
3. **Long direction rebuild** (if/when desired)
4. **Dashboard design approval** (Agent Teams working on it now)

## Next Steps (Autonomous)

1. **Monitor next 20 cycles** (through March 18) — verify no OOM kills
2. **Track FT backlog** — should drop from 146 → <30 over next week
3. **Watch for new champion** — if current champ degrades, tournament should promote replacement
4. **Generate improvement cards** if Auto Card Generator detects gaps (e.g., "no long champion for 7 days")

## Escalation

If Jarvis detects:
- **3+ consecutive OOM kills** → create high-priority fix card
- **Champion FT PF drops below 1.0** → alert Rob, tournament may be broken
- **FT backlog grows to 200+** → demotion logic failed, needs debug
- **No cycles completing for 12h** → service dead, alert Rob immediately

---

**Bottom line:** Moonshot is now monitored every 2h. Jarvis owns day-to-day health, Rob owns capital allocation.
