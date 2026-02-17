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

## Blofin Pipeline Status (Feb 16 Evening) 🚀

**Critical blockers being cleared:**

1. **Strategy generation (FIXED)** — Builder-A completed refactor of strategy_designer.py + strategy_tuner.py
   - Replaced broken `openclaw chat` subprocess calls with direct Anthropic SDK
   - Code ready to use after API key added to `.env`
   - Deployed on dev branch, ready to merge

2. **Feature engineering (IN PROGRESS)** — Builder-B stripping synthetic data, using real 24.7M ticks
   - Real data confirmed: Blofin websocket ingesting 24/7, 24.7M ticks in database
   - Features will pull from `ticks` table (real market data)
   - Dashboard will display real values instead of zeros

3. **Real data available** ✅ — No synthetic data shortcut needed
   - Ingestor running continuously since Feb 16 19:13 MST
   - Live coin data flowing in from Blofin API
   - Stored in local SQLite database

**Repo status:** Public repo at github.com/robbyrobaz/blofin-trading-pipeline, dev/main branch strategy in place.
