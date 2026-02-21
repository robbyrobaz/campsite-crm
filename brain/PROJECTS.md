# PROJECTS.md — Active Project Board

> **Strategic project overview.** Kanban board (:8787) is the live work queue.
> This file is the high-level view — project status, architecture, what matters.
> Update both when creating/completing projects. Keep it scannable.

---

## 🟢 ACTIVE

### 1. Blofin Trading Pipeline
**Repo:** `blofin-stack/` | **Dashboard:** http://127.0.0.1:8888
**Status:** Running hourly. Post-bug-fix rebuild phase.
**Last update:** Feb 19 — BUY/SELL bug fixed, all strategies demoted to T0, 12 promoted to T1
**Current state:** 2 T2s (ml_gbt_5m, mtf_trend_align), 10 T1, 19 T0
**Next actions:**
- [ ] Fix 3 breakout strategies with syntax error (line 41)
- [ ] Bump smoke test from 5K to 50K ticks
- [ ] Monitor T1→T2 promotions
- [ ] Phase 2 ML retrain triggers ~March 1
- [ ] Analyze paper trading slippage patterns and propose mitigation (queued)
- [ ] Add unit tests for feature library core functions (queued)
- [ ] Optimize backtester memory usage with chunked processing (queued)
**Blockers:** None

### 2. Numerai Tournament
**Repo:** `numerai-tournament/` | **Models:** robbyrobml, robbyrob2, robbyrob3
**Status:** Submissions working (round 1207). Performance is poor. Era-boosting promising.
**Last update:** Feb 19 — Medium era-boost: Sharpe +284%. Full run died, needs restart.
**Next actions:**
- [ ] Restart full era-boost run (2.7M rows)
- [ ] Set up persistent systemd service for daily submissions
- [ ] Investigate pickle deploy to Numerai compute
- [ ] If era-boost beats baselines → retrain all 3 models
**Blockers:** Full run keeps dying (memory/timeout?)

### 3. HedgeEngine (Sports Betting Dashboard)
**Repo:** `arb-dashboard/` | **Live:** GitHub Pages
**Status:** ✅ Deployed. Presets feature shipped.
**Last update:** Feb 19 — Save/load presets with localStorage
**Next actions:**
- [ ] Waiting on Rob for more features
**Blockers:** None

### 4. Sports Betting Arb Scanner
**Repo:** github.com/robbyrobaz/sports-betting-arb
**Status:** Hourly GitHub Actions running. Scanning 15+ sportsbooks.
**Last update:** Feb 18 — Full rebuild and deploy
**Next actions:**
- [ ] Phase 2: Bonus bet input form → auto-calculate best hedge
**Blockers:** None

### 5. Agent Stack / Jarvis Infrastructure
**Status:** Claw-Kanban installed and running at :8787. Agent files created. Enforcement hook active.
**Last update:** Feb 19 — Full stack deployment
**Components deployed:**
- ✅ Claw-Kanban dashboard (systemd: claw-kanban.service, port 8787)
- ✅ 5 agent files in `.claude/agents/` (ml-engineer, dashboard-builder, devops-engineer, qa-sentinel, crypto-researcher)
- ✅ Enforcement hook (enforce-tracking.sh)
- ✅ PROJECTS.md as data backbone
**Next actions:**
- [ ] Configure Claw-Kanban role routing and Telegram integration
- [ ] Integration test: create card → dispatch → verify flow
- [ ] Bake GSD principles into delegation workflow
**Blockers:** None

---

## 🟡 WAITING / STAGED

### 6. Phase 2 ML Retrain (Blofin)
**Status:** Code written, staged for ~March 1
**Gate:** 2 weeks from Feb 15 + regime diversity check
**Next:** Auto-triggers or manual acceleration

---

## ✅ COMPLETED (last 7 days)
- Claw-Kanban + agent stack deployment (Feb 19)
- Blofin BUY/SELL bug fix + strategy cleanup (Feb 19)
- HedgeEngine presets feature (Feb 19)
- Blofin audit bug fixes — 5 critical (Feb 17)
- Blofin dashboard rebuild at :8888 (Feb 18)
- Strategy ranking overhaul to EEP scoring (Feb 17)
- Sports betting arb scanner full rebuild (Feb 18)
- Gilbert PD radio trainer app scaffold (Feb 21)

---

## 🔴 KNOWN ISSUES
- **Git LFS backup failing** — >2GB objects rejected by GitHub
- **Disk at 53%** — Numerai parquet files (~6GB)

---

## 📋 BACKLOG (mentioned but not started)
- Campsite CRM
- Rob's "5 more projects" once tracking is clean
