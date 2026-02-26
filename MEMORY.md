# MEMORY.md — Learnings & Reference

> Project status lives in `brain/PROJECTS.md`. This file is for lessons learned, preferences, and reference info only.

## Architecture Reference

### Blofin Stack
- Feature library: 95+ technical indicators
- Backtester: 7-day historical replay, multi-timeframe
- ML pipeline: 5 models (direction, risk, price, momentum, volatility)
- EEP scoring: Entry (60%) + Exit (40%) composite. Hard gates: PF≥1.3, Sharpe≥0.8, MDD≤35%, Trades≥30
- Paper trading reality gap: slippage 0.052%/side (2.6x worse than assumed), fill rate 67%, stops too tight (47% hit then reversed)

### Numerai
- 3 models: robbyrobml, robbyrob2, robbyrob3
- API keys in `.env` in numerai-tournament/
- Era-boosting: 300 trees × 4 rounds, fixed tree count (no early stopping on boost rounds)
- Baselines: robbyrobml val_corr=0.02916 Sharpe=1.40

### Model Strategy
- Subscription: Claude Max 5x ($100/mo flat). Resets every 5 hours.
- Model routing table is in AGENTS.md (opus/sonnet/haiku/mini/codex)

## Lessons Learned

- **Subagents die on heavy data tasks.** Multi-GB parquet loads → run in main session, not builders.
- **Builders die silently.** Always check sessions_list after spawn. 3 Numerai builders died with 0 messages (Feb 19).
- **Monitoring crons for completed tasks = noise.** Only monitor active spawns. Check status.json for completed work.
- **Claude rate limits are per-minute** (1000 RPM), not per billing window.
- **Volume column in Blofin ticks is tick count, not real volume.** All volume-spike thresholds need ≤0.8 multiplier to bypass.
- **Smoke test uses 5K ticks (~10 candles)** — too few for strategies needing 25+ candle warmup.
- **Agent Teams need interactive mode** — no `-p` flag. Must accept permissions prompt (option 2).
- **Git LFS rejects >2GB objects** — exclude large data files from backup sweeps.
- **Numerai full dataset OOMs with 740 features on 32GB RAM.** Use v2_equivalent (304 features). OOM also kills OTHER processes (gateway died as collateral).
- **pandas dropna() breaks index alignment with numpy.** Always `reset_index(drop=True)` after dropna before passing to model.predict().

## Rob's Preferences
- Concise updates, not walls of text
- Tell him what you did, not what you're about to do
- Lead with bad news
- Hates: babysitting AI, temp files in repos, being asked questions he already answered
- Wants: clear project visibility, autonomous execution, honest opinions
- **NEVER block main session** — spawn work and stay available. Rob got angry when I was unavailable 5 min (Feb 19)
- **24/7 means 24/7** — The dispatcher must NEVER stop working overnight. "Late night" only means don't alert Rob, NOT stop dispatching. Lost 8 hours of productivity overnight Feb 19-20 because of a "quiet mode" that nobody asked for.
- **Rate limit strategy:** 5h window is the real constraint (caused the crash). 7-day has never actually throttled us even at 92%. Only go to "super light mode" (Haiku/Mini only) if 7-day hits 99%. Token tracker now pulls real utilization % from Anthropic OAuth API.
- **Opus is BANNED (Feb 25, 2026):** Discovered main session was silently running Opus the whole time despite notes saying Sonnet. Gateway config `openclaw.json` `.agents.defaults.model.primary` must be `anthropic/claude-sonnet-4-6`. Fallback is Haiku only. Opus removed from routing entirely. Rob was very angry about this — never let Opus back in.
- **Use the kanban board** — don't discount visual tools. Markdown files are not enough for project tracking.
- **Be a COO** — prioritize and execute autonomously between conversations. Don't wait idle.

## Infrastructure Reference
- **Claw-Kanban:** port 8787, systemd `claw-kanban.service`, SQLite DB at `kanban-dashboard/kanban.sqlite`
- **Agent files:** `.claude/agents/` — ml-engineer, dashboard-builder, devops-engineer, qa-sentinel, crypto-researcher
- **Numerai "medium" feature set = 740 features** (misleading). v2_equivalent = 304. Full dataset OOMs with 740 on 32GB RAM.

## OpenClaw Ops Memory (Feb 21, 2026)

- Canonical OpenClaw install is user-global only: `/home/rob/.npm-global/lib/node_modules/openclaw` (`2026.2.19-2`).
- Removed stale ghost install `/usr/lib/node_modules/openclaw` (`2026.2.9`), which had created duplicate binaries.
- After ghost cleanup, gateway service failed because systemd unit still pointed at `/usr/lib/node_modules/openclaw/dist/index.js`.
- Fixed by reinstalling service with force so `ExecStart` points to `/home/rob/.npm-global/lib/node_modules/openclaw/dist/index.js`.
- Cron model cleanup: replaced disallowed `model=sonnet` overrides with `model=openai-codex/gpt-5.3-codex` in `~/.openclaw/cron/jobs.json`.
- Default model strategy: primary is `openai-codex/gpt-5.3-codex`, with stronger-first fallbacks.
- Freeze symptom after ~15h uptime: gateway appeared alive but bot responsiveness degraded.
- Working recovery sequence:
- `systemctl --user restart openclaw-gateway.service openclaw-browser.service`
- `openclaw health`
- `openclaw cron run 36f47279-520f-4ce7-8f9c-a7c44be0771a --expect-final --timeout 180000`
- Post-fix validation: Jarvis cron resumed with `status=ok` and model `gpt-5.3-codex`.

## NQ Pipeline Reference (Updated Feb 24, 2026)

### Definitive Phase 2 Leaderboard (All Filters Corrected)
1. momentum: PF 2.91, Sharpe 7.68, Calmar 808, ~9 trades/day
1. orb: PF 2.92, Sharpe 7.59, ~3 trades/day  ← TIED #1 (target_horizon=10, confirmed Feb 25)
3. gap_fill: PF 2.10, Sharpe 5.56, ~5.6 trades/day
4. vwap_fade: PF 2.08, Sharpe 5.56, ~8.6 trades/day
5. prev_day: PF 2.03, Sharpe 5.33, ~0.84 trades/day
6. vol_contraction: PF 1.86, Sharpe 4.70, ~4.1 trades/day
All 6 pass Lucid gates. Phase 3 Tier 1: momentum + orb.
ORB improvement: target_horizon 5→10 bars = +14.6% PF, +14.6% Sharpe, +2.9pp WR. 10/10 folds pass Lucid sim.

### NQ Filter Inflation Bug (Fixed)
- `_CANDIDATE_CFG` in `run_phase2.py` was overriding `max_trades_per_session=100` for all strategies
- gap_fill: 49K → 6.9K signals after fix (+25% PF)
- momentum: 18K → 7.5K signals (+2.4% PF)
- Any new strategy must have correct session cap in `_CANDIDATE_CFG`, not 100

### ML Exit God-Model — Key Findings
- Dominant feature: `pnl_drawdown_from_peak` at 73% — model IS a trailing stop
- Failed to improve PF on test period (losing regime for all strategies)
- Better alternative: ATR trailing stop (simpler, same behavior)
- Code is in `pipeline/exit_ml_engine.py` + `strategies/exit_ml_strategy.py` for future reference

### Home Energy Dashboard Credentials (jarvis-home-energy/config.py)
- Wyze: KEY_ID=ec0dd323-1db4-4e81-8cd4-a4feab256bae, API_KEY=Fn1phBRix8ifLx0t5f3ktIyVfz2uRBSWdipswwjAiEJ0Z8SIAmVnaCNZLoOL
- Nest SDM project_id=edc12ede-0076-42d4-86d8-c87f49aec4b4, refresh_token saved in config.py
- 3 Wyze cameras: Front Side (D03F275A9799), Upstairs (2CAA8E813AE9), Downstairs (2CAA8E813B36)
- 2 Nest thermostats: Downstairs + Loft upstairs (both COOLING)
- wyze-sdk 2.2.0 has NO snapshot method — cameras show status only, no live feed
- Ring invite: jarvis.is.my.coo@gmail.com — 14-day window (received Feb 23 9:50 PM)

## Ops Lessons (Feb 24, 2026)
- **Kanban discipline**: spawn → PATCH In Progress → update status.json — must happen atomically. Rob called this out.
- **Dispatch immediately**: don't wait for "ideal conditions" — when data supports a test, run it. Rob called out delay on ML exit re-run.
- **CPU spikes 85°C at 6 AM**: ambient temps + sustained multi-process load; transient, not persistent

## NQ Live Trading Architecture (Feb 24, 2026)

### Final Architecture (locked)
```
DATA:       Tradovate API WS → wss://md.tradovateapi.com/v1/websocket
            → pipeline/data_feed/tradovate_feed.py
            → processed_data/NQ_continuous_1min.csv (single source of truth)

EXECUTION:  Signal engine → TradersPost webhook → Tradovate → Lucid prop accounts
            Webhook: https://webhooks.traderspost.io/trading/webhook/51e37934-7a18-4e37-9dc5-33416a36d579/...
            NOTE: Rotate webhook URL — was shared in chat Feb 24

INTERIM:    IBKR paper account (DUH860616) used for delayed (~15 min) data via
            pipeline/data_feed/ib_gap_fill.py → nq-bar-feed.service (active)
            Switch to Tradovate when live creds arrive
```

### Key Architecture Decisions
- **Data and execution are decoupled**: Tradovate for data (personal acct), TradersPost→Tradovate for execution (Lucid prop accts)
- **TradersPost is execution-only**: does NOT provide market data outward. Tradovate integration only routes orders, no data feed
- **IBKR direct API**: requires partner approval (gated). Don't pursue for personal accounts
- **TradeStation API**: also gated. Rob doesn't qualify as individual developer
- **Tradovate data feed**: open to account holders. Needs CID (int) + SEC (str) from developer portal + username/password
- **signalPrice is MANDATORY** in TradersPost webhooks when using Tradovate broker — Tradovate doesn't provide quotes to TradersPost

### Tradovate Credentials Needed (Rob getting tomorrow Feb 25)
- `TRADOVATE_CID`  — integer, from tradovate.com → Settings → Developer → API Keys
- `TRADOVATE_SEC`  — string, same location
- `TRADOVATE_USER` — Tradovate email
- `TRADOVATE_PASS` — Tradovate password
- Store in: `ninja_trader_strategies/config_live.py` (gitignored)

### Services
- `nq-bar-feed.service`       — IB delayed feed (active, interim)
- `nq-tradovate-feed.service` — Tradovate live feed (pre-built, disabled until creds)
- Switch: `systemctl --user stop nq-bar-feed && systemctl --user enable --now nq-tradovate-feed`

### Data File
- `processed_data/NQ_continuous_1min.csv` — 400K+ rows, Jan 2025→present, updated every 60s (IB) or real-time (Tradovate)
- Schema: datetime(UTC ISO), open, high, low, close, volume, contract
- Contracts: NQ_2025H/M/U/Z, NQ_2026H (rolls quarterly, next: NQM6 on March 13 2026)

### Execution Details
- Lucid 100K Flex eval: max DD $3K, daily DD $2K, min 10 trades
- Top Phase 2 strategies ready: momentum PF 2.91, orb PF 2.92 (target_horizon=10), gap_fill PF 2.43
- TradersPost webhook fires: {ticker: "NQH6", action: "buy"/"sell"/"exit", signalPrice: float, stopLoss: {...}, takeProfit: {...}}
- Tradovate execution NOT through TradersPost for data — only for order routing on prop accounts
