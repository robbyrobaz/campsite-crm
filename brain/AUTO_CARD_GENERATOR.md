# Auto Card Generator — Cron Prompt Instructions

> Runs hourly at :00. Model: Sonnet. Creates 2 NQ + 1 Blofin card in Planned.
> This file is the complete operating context. Read it fully before generating cards.

---

## PIPELINE PLANS & GUARDRAILS (Read before deciding what to build)

### NQ Futures Pipeline — Overall Goal
Build an always-running, self-improving NQ futures pipeline that:
1. Ingests live 1-min bars from SMB share (`/mnt/nt_bridge/bars.csv`) via `nq-smb-watcher.service`
2. Runs expert strategies through the God Model dispatcher on every bar
3. Papers trades on live data (DRY_RUN=True), logs to `data/nq_pipeline.db` run_id=`smb_live_forward_test`
4. Graduates experts to live trading via TradersPost → Tradovate → Lucid prop accounts (Rob approves each go-live)

**Target:** Pass Lucid 100K Flex eval ($6K profit, <$3K max DD, min 10 trades, consistency 50%).

**The God Model** is an ensemble dispatcher — NOT a single model. Each expert strategy scores every bar independently. Highest-confidence unblocked signal wins. More experts = more opportunity across sessions and market conditions. Experts earn their slot by passing forward test gates (PF≥1.3, trades≥20, DD<$3K).

**Expert lifecycle:**
```
Research Idea → Backtest (WF: PF≥1.5, trades≥50, DD<$3K, eval_pass≥40%) → Forward Test → God Model Live
```

**Strategy registry (current, all tier=1 gate_status=pass):**
- equal_tops_bottoms: PF 3.02, Sharpe 7.97 — ⚠️ NOT YET in live inference (high priority gap)
- orb: PF 2.92, Sharpe 7.59
- momentum: PF 2.82 — carrying live forward test (+$5,900 live)
- vwap_fade: PF 2.17 — bleeding live (11% WR, -$2,750)
- gap_fill: PF 2.07 — bleeding live (14% WR, -$2,565)
- vol_contraction: PF 1.96 — small but clean live (62% WR)
- prev_day: PF 2.03
- psych_levels: PF 1.92

**Key paths:**
- Repo: `/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/`
- DB: `data/nq_pipeline.db`
- Watcher: `pipeline/smb_watcher.py` + `pipeline/god_model_dispatcher.py`
- Strategies: `strategies/*.py`
- ML features: `ml/features.py` — use `build_session_aware_features()` ONLY (not `build_features()` — RTH-only, wrong)
- Models: `models/<strategy>/<strategy>_live_v1.pkl`
- Status: `pipeline/logs/smb_status.json`
- Forward test log: `pipeline/logs/forward_test_signals.csv`
- Services: `nq-smb-watcher.service`, `nq-dashboard.service`

**NQ hard constraints (never violate):**
- ⛔ DRY_RUN=True always — NEVER enable live trading or fire TradersPost webhooks without Rob's explicit approval
- ⛔ Never write to `/mnt/nt_bridge/` — read-only SMB mount
- ⛔ God Model = single unified ensemble — do NOT treat individual strategies as the live model
- ⛔ Only `build_session_aware_features()` for any new/retrained model — never `build_features()`
- ⛔ All timestamps internal = UTC. ET→UTC conversion happens once in `smb_watcher._validate_bar()`

**What good NQ cards look like:**
- Register ETB (equal_tops_bottoms) in the live God Model dispatcher so it generates real signals
- Investigate why gap_fill has 14% live WR vs 62% backtest — find root cause and add a fix
- Add psych_levels forward test validation — is it actually generating signals or just registered?
- Improve walk-forward evaluation for a specific strategy with new features
- Add a new strategy to the library (document, backtest, validate)
- Fix signal frequency issues (Feb 26 had 100 trades in one day — investigate cap logic)
- Improve dashboard: add tournament table, model drift indicators, session breakdown

**What bad NQ cards look like (do not create):**
- ❌ "Enable live trading" — Rob approves this, not auto-generated
- ❌ Anything touching `/mnt/nt_bridge/` with writes
- ❌ Using `build_features()` (RTH-only) for any new model training
- ❌ Creating per-session models (model must be session-aware / 24/7)
- ❌ Vague: "improve the NQ pipeline" with no specific target

---

### Blofin Pipeline — Overall Goal
Autonomous crypto strategy research and paper trading engine targeting consistent positive PF across multiple coins and strategies. Goal is eventually T3 (live trading) on top performers.

**Architecture (do not change these fundamentals):**
- **Global ML models** — trained on all coins combined. NEVER per-coin models.
- **Per-coin eligibility** — `strategy_coin_eligibility` table tracks which coin+strategy pairs respond well to global models. Only winning pairs trade. This is the correct approach.
- **3-tier lifecycle:** T0 (library/backtest) → T1 (backtested, monitoring) → T2 (forward test / paper trading) → T3 (live, future)
- **Ranking:** Strategies ranked by `bt_pnl_pct` (compounded PnL %). Top N by PnL that pass all gates get promoted. No EEP scoring — that was removed.
- **Promotion gates (T0→T1):** min 100 trades, PF ≥ 1.35, max drawdown < 50%, PnL > 0
- **Demotion gates (T2 FT):** after 20 FT trades — PF < 1.1 or MDD > 50% triggers demotion. Early crash-stop: PF < 0.5 with ≥5 FT trades = immediate demotion.
- **Pipeline runs every 4h** via `orchestration/run_pipeline.py`

**Current state:**
- T2: 12 strategies (forward test / paper trading)
- T1: 9 strategies
- T0: 7 strategies
- T-1: 3 demoted

**Top performers (FT PF, min 20 trades):**
- vwap_volatility_rebound: FT PF 2.21, T2 ✅
- volume_volatility_mean_reversion: FT PF 1.51, T2 ✅
- cross_asset_correlation: FT PF 1.40, T2 ✅

**Failing gate_status despite T2 tier (investigate these):**
- momentum_v1: T2, gate=fail, no FT data
- volatility_regime_switch: T2, gate=fail, no FT data
- atr_contraction_breakout: T2, gate=fail, no FT data

**Key paths:**
- Repo: `/home/rob/.openclaw/workspace/blofin-stack/`
- DB: `data/blofin_monitor.db`
- Strategy files: `strategies/*.py`
- ML pipeline: `orchestration/run_ml_trainer.py`, `ml/`
- Backtester: `orchestration/run_backtester.py`
- Ranker: `orchestration/run_ranker.py`
- Strategy designer (LLM): `orchestration/strategy_designer.py`
- Per-coin data: `strategy_coin_eligibility`, `strategy_coin_performance` tables
- Services: `blofin-stack-ingestor.service`, `blofin-stack-paper.service`, `blofin-dashboard.service`
- Dashboard: port 8892

**Blofin hard constraints:**
- ⛔ Never build per-coin ML models — global models only, per-coin eligibility handles selection
- ⛔ Dashboard must never show aggregate/system-wide PF or WR — always top-N pairs by FT PF
- ⛔ Phase 2 ML retrain gate: ~March 1 + 2 weeks of regime diversity. Don't trigger early.
- ⛔ T3 (live trading) requires Rob's explicit approval

**What good Blofin cards look like:**
- Diagnose why momentum_v1/volatility_regime_switch/atr_contraction_breakout are T2 with no FT data
- Design a new strategy variant using the LLM designer for a specific market pattern not covered
- Retrain ML models for the top FT performer using latest tick data
- Expand the top FT pair (vwap_volatility_rebound) to additional coin pairings
- Analyze slippage patterns in paper trades — are SL/TP targets realistic?
- Improve bt_pnl_pct or sharpe for strategies stuck between T1/T2 via config tuning or feature work
- Add new features to the feature library for a specific market regime

**What bad Blofin cards look like (do not create):**
- ❌ Per-coin model training
- ❌ "Enable live trading" — Rob approves
- ❌ Showing system-wide aggregate metrics on dashboard
- ❌ Triggering Phase 2 ML retrain before March 1

---

## STEP 1 — GATE CHECK
```bash
PLANNED=$(curl -s "http://127.0.0.1:8787/api/cards?status=Planned" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
IN_PROGRESS=$(curl -s "http://127.0.0.1:8787/api/cards?status=In%20Progress" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
TOTAL=$((PLANNED + IN_PROGRESS))
echo "Queue: $PLANNED planned + $IN_PROGRESS in-progress = $TOTAL total"
```
**If TOTAL >= 2: print "GATE: queue has $TOTAL cards, skipping" and STOP.**

---

## STEP 2 — READ NQ LIVE STATE
```bash
cat /home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/pipeline/logs/smb_status.json

python3 << 'EOF'
import sqlite3
db = '/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/data/nq_pipeline.db'
c = sqlite3.connect(db)
print("=== Forward Test — Last 7d by strategy ===")
for r in c.execute("""
    SELECT strategy_name, COUNT(*) trades,
           SUM(CASE WHEN pnl_pts>0 THEN 1 ELSE 0 END) wins,
           ROUND(SUM(pnl_pts),1) pts, ROUND(SUM(pnl_usd),0) usd
    FROM paper_trades
    WHERE run_id='smb_live_forward_test' AND date >= date('now','-7 days')
    GROUP BY strategy_name ORDER BY SUM(pnl_usd) DESC
"""):
    print(r)
print("\n=== Strategy Registry ===")
for r in c.execute("SELECT strategy_name, tier, gate_status, bt_profit_factor FROM strategy_registry ORDER BY bt_profit_factor DESC"):
    print(r)
EOF
```

---

## STEP 3 — READ BLOFIN LIVE STATE
```bash
python3 << 'EOF'
import sqlite3
db = '/home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db'
c = sqlite3.connect(db)
print("=== Tier Summary ===")
for r in c.execute("SELECT tier, COUNT(*) FROM strategy_registry WHERE archived=0 GROUP BY tier ORDER BY tier DESC"):
    print(r)
print("\n=== Failing T2 strategies ===")
for r in c.execute("SELECT strategy_name, tier, bt_profit_factor, ft_profit_factor, gate_status, gate_failures FROM strategy_registry WHERE archived=0 AND gate_status='fail' AND tier>=2"):
    print(r)
print("\n=== Top 5 FT performers (min 20 FT trades) ===")
for r in c.execute("""
    SELECT coin, strategy, ft_profit_factor, ft_trade_count
    FROM strategy_coin_eligibility WHERE ft_trade_count >= 20
    ORDER BY ft_profit_factor DESC LIMIT 5
"""):
    print(r)
print("\n=== Recent paper PnL (last 24h) ===")
for r in c.execute("""
    SELECT symbol, COUNT(*), ROUND(SUM(pnl_usdt),2)
    FROM paper_trades WHERE opened_ts_iso > datetime('now','-24 hours')
    GROUP BY symbol ORDER BY SUM(pnl_usdt) DESC LIMIT 5
"""):
    print(r)
EOF
```

---

## STEP 4 — DECIDE WHAT TO BUILD

Use the pipeline plans above as your compass. Pick work that moves the pipelines forward in the right direction.

**NQ priority order:**
1. Is equal_tops_bottoms generating live signals? If not → add it to god_model_dispatcher.py
2. Is gap_fill or vwap_fade still bleeding (WR < 40%)? → Investigate signal conditions, propose fix
3. Is trade frequency for any strategy abnormal (>20/day)? → Investigate session cap logic
4. Is psych_levels generating signals? Verify it's in dispatcher with correct model path
5. Is there a strategy with 0 live trades despite being registered? → Debug model loading
6. Default: analyze winning vs losing trades for top strategy, propose a feature improvement

**Blofin priority order:**
1. Any T2 strategy with gate_status=fail and no FT data → diagnose why FT isn't running for it
2. Top FT performer — can it be expanded to more coin pairs via eligibility table?
3. Is paper trading PnL positive or negative today? If negative → dig into which strategy/coin is losing
4. Design a new strategy for an unaddressed market pattern (use `strategy_designer.py`)
5. Default: retrain ML entry model for top FT performer with latest 30 days of tick data

---

## STEP 5 — CREATE CARDS

Create **2 NQ cards + 1 Blofin card** in **Planned** (not Inbox):

```bash
# Step A: Create in inbox to get ID
CARD=$(curl -s -X POST http://127.0.0.1:8787/api/inbox \
  -H "content-type: application/json" \
  -d '{"text":"TITLE","source":"auto-generator","project_path":"PROJECT_PATH"}')
CARD_ID=$(echo "$CARD" | python3 -c "import sys,json; print(json.load(sys.stdin)['card']['id'])")

# Step B: Enrich and move to Planned
curl -s -X PATCH "http://127.0.0.1:8787/api/cards/$CARD_ID" \
  -H "content-type: application/json" \
  -d '{
    "status": "Planned",
    "assignee": "claude",
    "description": "FULL DESCRIPTION with file paths, DB queries for context, what to build, success criteria, deploy steps, constraints"
  }'
```

**Description must include:**
- Exact file paths to read and modify
- Relevant DB queries to get current state first
- What to build/fix/investigate (specific, not vague)
- Success criteria ("done when X")
- Deploy step: `systemctl --user restart <services>`
- Verify step: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<port>/`
- Constraints: DRY_RUN only, no live orders, no per-coin ML models, etc.

**Project paths:**
- NQ: `/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE`
- Blofin: `/home/rob/.openclaw/workspace/blofin-stack`

---

## STEP 6 — SUMMARY
Print:
```
AUTO-GENERATOR: Created 3 cards
- [NQ] <title>
- [NQ] <title>
- [Blofin] <title>
```

---

## ABSOLUTE RULES
- Gate: Planned + In Progress >= 2 → skip, do nothing
- Cards go to Planned (not Inbox) — dispatcher picks up within 30min
- assignee = always "claude"
- NEVER enable live trading, fire TradersPost webhooks, or activate prop firm evals
- NEVER suggest per-coin ML models for Blofin
- NEVER use `build_features()` for NQ model training (RTH-only) — use `build_session_aware_features()`
- Be specific — name the strategy, file, metric. No vague "improve the pipeline" cards.
