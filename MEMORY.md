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

## Jarvis Infrastructure (Feb 16 Evening)

**Status:** Fully bootstrapped and operational

**What's in place:**
- All persona files loaded (SOUL.md, IDENTITY.md, USER.md, AGENTS.md)
- Brain directory structure (status.json, STANDARDS.md, CONTEXT.md)
- Daily memory logs (memory/YYYY-MM-DD.md)
- Backup infrastructure working: auto-syncs to github.com/robbyrobaz/openclaw-2nd-brain.git every 10 minutes
- All Blofin services running (ingestor, API)
- System health good: CPU 61°C, disk 18%, gateway active

**Disaster recovery:** If laptop breaks, entire setup recoverable from GitHub (coin data can be redownloaded, stored separately in gitignore)
