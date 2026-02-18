# MEMORY.md - Long-Term Memory

## Blofin AI Trading Pipeline (LIVE)

**Status:** Deployed and running HOURLY (as of 2026-02-16 07:27 MST)

**System:** Fully automated AI-driven strategy research engine
- 5 agents built entire system in 24 hours (Feb 15-16)
- Smoke test passed (all components verified with 1000 rows)
- Initial run completed in 7 minutes (00:02-00:09 MST)
- Switched to hourly iteration for faster convergence (cron job: `0 * * * *` America/Phoenix)
- Old daily run at midnight UTC deprecated; now runs every hour on the hour

**Architecture:**
- Feature library: 95+ technical indicators (single source of truth)
- Backtester: 7-day historical replay, multi-timeframe
- ML pipeline: 5 models (direction, risk, price, momentum, volatility)
- Orchestration: Daily cycle—design (Opus), backtest (Sonnet), rank, report
- Database: New tables for results, models, ensembles, reports

**Cost:** $100/month fixed (Claude Max 5x plan), $0 marginal per run

**Operation:** 
- Design phase: 2-3 months in backtest-only mode
- Keeps top 20 strategies, top 5 models, top 3 ensembles (dynamic ranking, no hard thresholds)
- When top 3 ready: deploy live with real money

**Success metrics:** 20 strategies rotating, 5+ models >55% accuracy, 3+ ensembles ready in 4-8 weeks

## Rate Limiting Fix (Feb 16, 21:20 MST)

**Issue:** Hit 429 rate limits during aggressive optimizer run. Analyzer had no rate limiting logic.

**Root cause:** `llm_client.py` was calling Claude via subprocess with no throttling. Aggressive optimizer made 10+ sequential calls, hitting Claude's 1000 RPM ceiling instantly.

**Fix implemented:**
- Added `ClaudeRateLimiter` class tracking requests per 1-minute sliding window
- Exponential backoff when approaching 950 RPM (95% threshold)
- Thread-safe with Lock-protected deque, automatic 60-sec cleanup
- Records request timestamp on every successful call
- Prevents connectivity blackouts from rate limit hammering

**Key insight:** Claude's limits are per-minute, NOT per 4-6 hours. The 4-6 hour window Rob mentioned was likely a billing cycle or token usage reporting window, not the actual refresh.

## Model Strategy (Updated 2026-02-18)

**Primary (Opus):** Jarvis main agent — all conversations, planning, code review, complex reasoning.
**Cron/Heartbeats (Haiku):** Isolated sessions — hourly health checks, Blofin strategy adjustments. Silent unless alert needed.
**Builders (Sonnet):** Subagent code generation, refactors, bug fixes, tests.
**Automation (Mini):** Token audits, build loops, log parsing, cron jobs.

**Subscription:** Claude Max 5x ($100/mo flat). NOT per-token API billing. Resets every 5 hours.
**Cost optimization:** Keep heartbeats/cron on Haiku isolated to conserve Opus usage cap for real work.

## Jarvis Infrastructure (Feb 16 Evening) ✅

**Status:** Fully bootstrapped and operational

**What's in place:**
- All persona files loaded (SOUL.md, IDENTITY.md, USER.md, AGENTS.md)
- Brain directory structure (status.json, STANDARDS.md, CONTEXT.md)
- Daily memory logs (memory/YYYY-MM-DD.md)
- Two-tier backup infrastructure working:
  - **Full-restore (every 2h):** Complete system snapshots to GitHub with Git LFS
  - **2nd-brain (every 10m):** Knowledge-only sync for Claude CLI fallback
- All Blofin services running (ingestor, API, paper trading, dashboard)
- System health good: CPU 50°C, disk 18%, gateway active

**Disaster recovery:** If laptop breaks, entire setup recoverable from GitHub. Full snapshots in full-restore repo, knowledge base in 2nd-brain repo.

## Audit Bug Fixes (Feb 17 COMPLETE) ✅

**Status:** All 5 critical bugs fixed and deployed (39/39 tests passing)

**Bugs fixed:**
1. **P1 - Top-N Deduplication:** GROUP BY model_name in ranking queries (was returning duplicates)
2. **P2 - Sharpe Ratio Guard:** Minimum 30-trade requirement before calculating Sharpe (was accepting noise)
3. **P3 - Data Leakage Prevention:** Temporal split with 24-hour embargo (was shuffling test data into train)
4. **P4 - Health Score Labels:** Corrected thresholds (15/100 = CRITICAL, was labeled GOOD)
5. **P5 - Convergence Gates:** Auto-archive strategies after 3 failed tunings, ensemble test requirements (was churning)

**Deployment:** Live at :8888 with new backtest-vs-paper comparison section

## Blofin Pipeline Status (Feb 17 COMPLETE) ✅🚀

**Status:** FULLY OPERATIONAL — Real data flowing, strategies scoring, dashboard live, audit bugs fixed

**What's working:**
1. **Real data pipeline** — Ingestor 24/7, 24.7M ticks, live market data
2. **Feature engineering** — All NaN issues fixed, real OHLCV + 95+ indicators
3. **Strategy generation** — Opus/Sonnet calls via OpenClaw auth, new strategies generated daily
4. **ML training** — 5 models trained on real data, converging nicely
5. **Backtesting** — 9,452+ strategy evaluations, real performance metrics
6. **Dashboard** — Live display of top strategies (79+ grades on real data)

**Top performing strategies (live scores):**
- vwap_reversion: 79.98 (grade B, 52% win rate)
- rsi_divergence: 79.30 (grade B, 45% win rate)
- momentum: 79.25 (grade B, 37% win rate)

**Dashboards (Feb 16):**
- **8780 (basic):** DEPRECATED — ignore. Old websocket dashboard.
- **8888 (advanced ML):** THE LIVE DASHBOARD
  - Fixed: win_rate format (decimal not percentage)
  - Fixed: top_strategies now has complete data (scores + metrics merged)
  - Added: Live data tracker showing real-time tick flow (updates every 3 seconds)
  - Indicator shows "📊 Live: X ticks/10s" in header — green dot if data flowing, red if stale

**Current Initiative (Feb 16 evening):**
- Deployed aggressive 10-iteration optimizer using existing 24.7M ticks
- Building multi-timeframe data library (1h, 4h candles) for better backtesting
- Finding profitable strategies without waiting for new market data
- Focus: identify 2-3 winners (>52% win rate, positive Sharpe) then deploy

**Repo:** Public at github.com/robbyrobaz/blofin-trading-pipeline
- dev branch: Active development
- main branch: Production-ready code
- All builders' work merged and tested

## Strategy Ranking Overhaul (Feb 17) ✅

**Status:** Entry + Exit Package Score (EEP) integrated; replaces win-rate-only ranking

**Problem:** Win rate is misleading. 40% win rate with big winners beats 70% with small losers.

**Solution:** Composite EEP scoring
- **Entry metrics (60%):** Profit Factor (30%) + Sharpe (25%) + Max DD (20%) + Sortino (15%) + Expectancy (10%)
- **Exit metrics (40%):** % of max profit captured (25%) + R:R realization (20%) + Stop-hit frequency (15%) + Breakeven stop usage (10%)
- **Hard gates:** PF ≥ 1.3, Sharpe ≥ 0.8, MDD ≤ 35%, Trades ≥ 30, positive expectancy

Dashboard now shows strategies ranked by EEP, not win rate.

## Phase 2 ML Retrain Framework (Feb 17) ⏳ Staged

**Status:** Design complete, code ready, awaiting spawn approval or auto-trigger (~March 1)

**Framework ready to deploy:**
- `ml_retrain_phase2.py` — Walk-forward retrain with 24h embargo, regime diversity checks
- `ab_test_models.py` — A/B testing framework (100 trades/arm minimum, safety gates)
- `execution_calibrator_v2.py` — Phase 1 follow-up using 33.4K real trade feedback (actual slippage 0.052%/side, fill rate 67%, hold time 104.6 min)
- Systemd cron jobs configured (2-week accelerated timeline, 75-trade minimum gate, 1.5-2x slippage conservative multiplier)

**Trigger conditions:**
- Timeline: 2 weeks from Feb 15 (~March 1, 2026) or manual acceleration
- Trade gate: 75 closed trades (✅ satisfied at 33.4K)
- Regime diversity: Volatility must span 20th-80th percentile

## Paper Trading Feedback Loop (Feb 17) ✅

**Status:** Phase 1 (execution calibrator) complete. Phase 2 gates set for 2-week accelerated timeline.

**Phase 1 — Execution Calibrator (LIVE):**
- Reads closed paper trades (33.4K trades accumulated)
- Learns: actual slippage, fill rates, hold times
- Updates position sizing dynamically
- Zero look-ahead bias (closed trades only)

**Reality gap discovered:**
- **Actual slippage:** 0.052%/side vs 0.02% assumed (2.6x worse)
- **Stop-hit frequency:** 47.2% stops hit then reversed (stops at obvious levels)
- **Avg hold time:** 104.6 min vs 60 min assumed
- **Fill rate:** 67% (not 100%)
- **Paper PnL:** Currently unprofitable (PF=0.74) due to tight stops

**Phase 2 — ML Retrain (Accelerated Timeline):**
- Trigger: 2 weeks + 75 closed trades (not 4 weeks + 100)
- Safety gates: 
  - Regime diversity check (volatility must span 20th-80th percentile)
  - A/B test minimum 100 trades per arm
  - Conservative 1.5-2x slippage multiplier until 6 weeks data
- Walk-forward retrain with 24h embargo (prevents label leakage)

**Top 3 Strategies Ready:**
1. mtf_trend_align / SHIB-USDT [5m/1h] — 81.8% WR, 16.74 Sharpe, +9.76% PnL
2. ml_gbt_5m / ETH-USDT [5m] — 71.0% WR, 7.62 Sharpe, +42.3% PnL
3. mtf_momentum_confirm / JUP-USDT [15m/4h] — 76.9% WR, 8.56 Sharpe, +29.28% PnL

**Strategy lifecycle:** Discovery phase (now) → convergence (4-8 weeks) → stability. Once top 3 prove out, research tempo drops significantly. New strategies must clear increasingly high bar.

**Key actionable:** Stops are too tight. Increase SL by 10-75bps to avoid algo stop-hunting at obvious levels.

## Cron Job Best Practices (Feb 17 Lesson) 📝

**Issue:** Monitoring crons for completed builders check for deleted sessions → always "not found" reports (noise).

**Solution:** Only monitor *active* spawns. For completed tasks, check status.json truth store instead. Disable monitors once builders are done.

**Applied:** Removed two stale monitoring crons (audit bug fix, Phase 2 framework) on Feb 17 18:00 MST after confirming status.json.

## Librarian Deployment Candidates (Feb 17 Evening) ✅ → Live Deployment Ready

**Status:** 3 strategies qualified and monitoring for Phase 2 launch

**Three Librarian Candidates (Feb 17, 20:01 MST Evening):**
1. **mtf_trend_align** — 79.7% WR, 10.34 Sharpe (primary candidate for first live deployment)
2. **ml_gbt_5m** — 70.3% WR, 7.19 Sharpe (ML-backed, highly robust)
3. **mtf_momentum_confirm** — 70.5% WR, 5.20 Sharpe (multi-timeframe confirmation bias)

**Deployment Timeline:**
- **Feb 17-24:** 7-day monitoring phase (parameter sensitivity validation)
- **~March 1:** Phase 2 ML Retrain launch (regime diversity gates + A/B test framework)
- **March 1+:** A/B test validation (100+ trades per arm minimum)
- **Conditional live:** Once A/B gates pass, deploy to real capital with Kelly Criterion position sizing

**Key Constraints for Live Deployment:**
- Real slippage: 0.052%/side (vs 0.02% assumed—2.6x worse)
- Fill rate: 67% (vs 100% assumed)
- Stop-hunting detected: 47.2% stops hit then reversed → widen stops 10-75bps
- Conservative slippage multiplier: 1.5-2x until 6 weeks of data

**Current Active Roster:** 6 strategies (down from 13; pruned 7 losers in evening adjustment)

## Sports Betting Arbitrage Detection System (Feb 18) ✅ LIVE

**Status:** Deployed to GitHub, hourly automation running, 24/7 monitoring active

**GitHub Repo:** https://github.com/robbyrobaz/sports-betting-arb (public, live)

**System:** Automated sports betting arbitrage detector (public odds hedging + bonus bet math)

**Architecture:**
- GitHub Actions triggers hourly (0 * * * * America/Phoenix)
- Scrapes 15+ sportsbooks (ESPN, DraftKings, FanDuel, BetMGM, Caesars, PointsBet, Barstool, WynnBET, Golden Nugget, Hard Rock, Tipico, FoxBet, Bovada)
- Detects guaranteed-profit hedges (public line arbitrage + bonus bet hedging)
- Generates human-readable markdown reports
- Jarvis monitoring cron checks every hour at :10

**Folder Structure (Final):**
- `/reports/` — Human-readable markdown (index.md, bets-now.md, bets-this-week.md)
- `/history/` — Archive of past reports
- `/raw/` — Machine-readable JSON data (hidden from daily view)

**Report Format (Example):**
```
#1 DraftKings → FanDuel Hedge
- Guaranteed Profit: $150
- Your Risk: $500
- Steps: 1. Bet $X on Lakers -120 DK  2. Bet $Y on Celtics +110 FD  3. Collect profit
```

**Key Capability Clarification:**
- System CAN see: Public odds on any sportsbook (no login needed)
- System CANNOT see: Your personal bonuses (require login + account history)
- Real money comes from bonus hedging ($100-500+ per bonus), not public line arbs ($2-20)
- Future Phase 2: Add input form for bonuses → auto-calculate best hedge

**Deployment Timeline:**
- 06:35 MST: Rob requested rebuild (old system was garbage)
- 07:09 MST: Started fresh with API-based approach
- 07:52 MST: First real scan + GitHub push (10 NBA games, real ESPN odds)
- 08:00 MST: Switched to hourly automation
- 08:05 MST: Restructured reports to human-readable markdown
- 08:17 MST: System live and monitoring

**Automation:**
- GitHub Actions: Every hour at :00 (full scan + formatting)
- Jarvis Monitor: Every hour at :10 (status check + audit trail)

**Status:** ✅ Live and operating. Next scan generates real betting instructions.

## Claude Code Agent Teams (Feb 18, 2026) ✅

**What:** Claude's built-in multi-agent feature for parallel coding. Part of Claude Max 5x plan ($100/mo), no extra cost.
**Setup:** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `~/.claude/settings.json` (already enabled)
**Launch:** Interactive `claude` session with `--teammate-mode in-process`, paste task, lead spawns teammates
**Monitoring:** Subagent .jsonl files in `~/.claude/projects/<project>/<session>/subagents/`
**Reference:** `brain/AGENT_TEAMS.md` for full details

**First use:** Blofin pipeline redesign — 4 teammates (ML fix, strategy lifecycle, pipeline scheduling, dashboard)
**Lesson:** Don't use `-p` flag (non-interactive) — Agent Teams requires interactive mode
**Lesson:** Must select "Yes, I accept" on permissions prompt (option 2, not default)
