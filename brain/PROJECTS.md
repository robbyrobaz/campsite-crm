# PROJECTS.md — Active Project Board

> **This is the truth store for all projects.** Read on every session boot. Update after every work session.
> Rob and Jarvis both reference this to know what's happening across all projects.
> Keep it scannable. No essays. Status + Next Action for each project.

---

## 🟢 ACTIVE

### 1. Blofin Trading Pipeline
**Repo:** `blofin-stack/` | **Dashboard:** http://127.0.0.1:8888
**Status:** Running hourly. Pipeline healthy. Post-bug-fix rebuild phase.
**Last update:** Feb 19 — BUY/SELL normalization bug fixed, all 31 strategies demoted to T0 (clean slate), 12 promoted to T1 with honest metrics
**Current state:** 2 T2s (ml_gbt_5m, mtf_trend_align), 10 T1, 19 T0
**Next actions:**
- [ ] Fix 3 breakout strategies with syntax error (line 41)
- [ ] Bump smoke test from 5K to 50K ticks (strategies need 25+ candle warmup)
- [ ] Monitor T1→T2 promotions over next week
- [ ] Phase 2 ML retrain triggers ~March 1
**Blockers:** None

### 2. Numerai Tournament
**Repo:** `numerai-tournament/` | **Models:** robbyrobml, robbyrob2, robbyrob3
**Status:** Submissions working (round 1207). Performance is poor. Era-boosting experiment promising.
**Last update:** Feb 19 — Medium era-boost run: Sharpe 0.145→0.557 (+284%). Full run (2.7M rows) died silently, needs restart.
**Current state:**
- All 3 models submitting daily (~6AM MST) via `multi_model_daily_bot.py` — but NO systemd service exists (unclear how it's running)
- Performance: robbyrobml 27% win rate, robbyrob2 0% win rate. Bad.
- Era-boosting looks promising but needs full dataset validation
**Next actions:**
- [ ] Restart full era-boost run (2.7M rows) and monitor to completion
- [ ] Set up persistent systemd service for daily submissions
- [ ] Investigate pickle deploy to Numerai compute (Rob wants this)
- [ ] If full era-boost beats baselines → retrain all 3 models with it
**Blockers:** Full run keeps dying (memory? timeout?)

### 3. HedgeEngine (Sports Betting Dashboard)
**Repo:** `arb-dashboard/` | **Live:** GitHub Pages
**Status:** ✅ Deployed and working. Presets feature shipped.
**Last update:** Feb 19 — Save/load presets with localStorage, dark theme UI
**Next actions:**
- [ ] Rob may request more features (waiting on direction)
**Blockers:** None

### 4. Sports Betting Arb Scanner
**Repo:** github.com/robbyrobaz/sports-betting-arb
**Status:** Hourly GitHub Actions running. Scanning 15+ sportsbooks.
**Last update:** Feb 18 — Full rebuild and deploy
**Next actions:**
- [ ] Phase 2: Bonus bet input form → auto-calculate best hedge
**Blockers:** None (running autonomously)

---

## 🟡 WAITING / STAGED

### 5. Agent Stack Improvement (this project)
**Status:** Research done (4-phase docs in `/docs/agent-stack/`). Rob hasn't reviewed yet.
**Recommendation:** 5 agent definition files + QA sentinel + enforcement hooks
**Next:** Rob reviews → decide what to implement

### 6. Phase 2 ML Retrain (Blofin)
**Status:** Code written, staged for ~March 1 trigger
**Gate:** 2 weeks from Feb 15 + regime diversity check
**Next:** Auto-triggers or manual acceleration

---

## ✅ COMPLETED (last 7 days)
- Blofin BUY/SELL bug fix + strategy cleanup (Feb 19)
- HedgeEngine presets feature (Feb 19)
- Blofin audit bug fixes — 5 critical (Feb 17)
- Blofin dashboard rebuild at :8888 (Feb 18)
- Strategy ranking overhaul to EEP scoring (Feb 17)
- Sports betting arb scanner full rebuild (Feb 18)
- Claude Code Agent Teams setup (Feb 18)

---

## 🔴 KNOWN ISSUES
- **Git LFS backup failing** — >2GB objects rejected by GitHub. Need to split DB or exclude parquets.
- **Disk at 49%** — Numerai parquet files (~6GB). May need cleanup.

---

## 📋 BACKLOG (Rob mentioned but not started)
- Campsite CRM
- "5 more projects" once tracking is clean
