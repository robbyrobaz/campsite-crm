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

## Model Strategy

**Cost-efficiency rule:** Use Haiku for regular automated tasks, Sonnet for heavy reasoning.

- **Default (Haiku):** All cron jobs, heartbeats, periodic checks, routine automation
- **Heavy tasks (Sonnet):** Complex reasoning, code reviews, strategy analysis, research — override with `model=sonnet` when you know it needs depth
- **Alias:** Use `sonnet` shorthand instead of full `anthropic/claude-sonnet-4-5`

Apply this to all new automation: default to haiku unless the task explicitly requires nuanced thinking.

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

## Blofin Pipeline Status (Feb 16 COMPLETE) ✅🚀

**Status:** FULLY OPERATIONAL — Real data flowing, strategies scoring, dashboard live

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
