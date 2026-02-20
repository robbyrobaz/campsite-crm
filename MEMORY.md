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
- **Use the kanban board** — don't discount visual tools. Markdown files are not enough for project tracking.
- **Be a COO** — prioritize and execute autonomously between conversations. Don't wait idle.

## Infrastructure Reference
- **Claw-Kanban:** port 8787, systemd `claw-kanban.service`, SQLite DB at `kanban-dashboard/kanban.sqlite`
- **Agent files:** `.claude/agents/` — ml-engineer, dashboard-builder, devops-engineer, qa-sentinel, crypto-researcher
- **Numerai "medium" feature set = 740 features** (misleading). v2_equivalent = 304. Full dataset OOMs with 740 on 32GB RAM.
