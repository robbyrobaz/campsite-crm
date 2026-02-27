# Auto Card Generator — Cron Prompt Instructions

> This file is the canonical instructions for the hourly Auto Card Generator cron.
> Cron reads this file at runtime to get the latest instructions.
> Update this file to change behavior — no cron edit needed.

## Purpose
Generate actionable kanban cards every hour to keep the NQ futures and Blofin trading pipelines moving forward autonomously. Cards go directly to **Planned** status so the dispatcher picks them up within 30 minutes.

## STEP 1 — GATE CHECK
```bash
PLANNED=$(curl -s "http://127.0.0.1:8787/api/cards?status=Planned" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
IN_PROGRESS=$(curl -s "http://127.0.0.1:8787/api/cards?status=In%20Progress" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
echo "Planned: $PLANNED, In Progress: $IN_PROGRESS"
TOTAL=$((PLANNED + IN_PROGRESS))
echo "Total queued: $TOTAL"
```
**If TOTAL >= 2: print "GATE: queue has $TOTAL cards, skipping this cycle" and STOP. Do not create cards.**

## STEP 2 — READ NQ PIPELINE STATE
```bash
cat /home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/pipeline/logs/smb_status.json

python3 << 'EOF'
import sqlite3
db = '/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/data/nq_pipeline.db'
c = sqlite3.connect(db)
print("=== Strategy Registry ===")
for r in c.execute("SELECT strategy_name, tier, gate_status, bt_profit_factor, bt_sharpe FROM strategy_registry ORDER BY bt_profit_factor DESC"):
    print(r)
print("\n=== Forward Test — Last 7d by strategy ===")
for r in c.execute("""
    SELECT strategy_name,
           COUNT(*) trades,
           SUM(CASE WHEN pnl_pts>0 THEN 1 ELSE 0 END) wins,
           ROUND(SUM(pnl_pts),1) pts,
           ROUND(SUM(pnl_usd),0) usd
    FROM paper_trades
    WHERE run_id='smb_live_forward_test'
      AND date >= date('now','-7 days')
    GROUP BY strategy_name
    ORDER BY SUM(pnl_usd) DESC
"""):
    print(r)
print("\n=== Today's signal count ===")
for r in c.execute("SELECT strategy_name, COUNT(*) FROM paper_trades WHERE run_id='smb_live_forward_test' AND date=date('now') GROUP BY strategy_name"):
    print(r)
EOF
```

## STEP 3 — READ BLOFIN PIPELINE STATE
```bash
python3 << 'EOF'
import sqlite3
db = '/home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db'
c = sqlite3.connect(db)
print("=== Tier Summary ===")
for r in c.execute("SELECT tier, COUNT(*) FROM strategy_registry WHERE archived=0 GROUP BY tier ORDER BY tier DESC"):
    print(r)
print("\n=== Top 5 by FT PF ===")
for r in c.execute("""
    SELECT coin, strategy, ft_profit_factor, ft_trade_count
    FROM strategy_coin_eligibility
    WHERE ft_trade_count >= 20
    ORDER BY ft_profit_factor DESC LIMIT 5
"""):
    print(r)
print("\n=== Failing gate_status strategies (tier >= 1) ===")
for r in c.execute("SELECT strategy_name, tier, bt_profit_factor, ft_profit_factor, gate_status, gate_failures FROM strategy_registry WHERE archived=0 AND gate_status='fail' AND tier>=1 ORDER BY tier DESC LIMIT 5"):
    print(r)
print("\n=== Recent paper trade PnL (last 24h) ===")
for r in c.execute("""
    SELECT symbol, COUNT(*), ROUND(SUM(pnl_usdt),2) pnl
    FROM paper_trades
    WHERE opened_ts_iso > datetime('now','-24 hours')
    GROUP BY symbol ORDER BY pnl DESC LIMIT 8
"""):
    print(r)
EOF
```

## STEP 4 — DECIDE WHAT TO BUILD

Read the data carefully. Think about what's most impactful. Do NOT generate generic cards.

**NQ decision tree (pick 2 most impactful):**
- Is a strategy bleeding on live forward test (win rate < 40% with 10+ trades)? → Investigate signal filter conditions for that strategy
- Are signals_today == 0 during RTH hours? → Debug signal generation pipeline
- Is equal_tops_bottoms (ETB) not in tournament or not generating signals? → Register it, run tournament update
- Is the God Model ensemble not being updated? → Update tournament with latest walk-forward results
- Is any high-PF strategy (PF > 2.0) not generating live signals? → Investigate session filter or model loading
- Is trade frequency too high for one strategy (>20 trades/day)? → Tighten confidence threshold
- Is there a strategy with 0 live trades in 7 days? → Check if model is loaded and registered for live inference
- Are psych_levels or equal_tops_bottoms missing from live inference? → Add them to god model dispatcher
- Default research: Analyze last 100 forward test trades for the top strategy — what are the best/worst entry conditions? Add new feature to improve precision.

**Blofin decision tree (pick 1 most impactful):**
- Is a T2 strategy failing gate_status? → Diagnose: run backtest, check recent FT trades, propose fix
- Is any T1/T2 strategy with ft_profit_factor > 1.5 missing a coin pairing? → Expand to new coin pairs
- Are paper trades showing consistent losses on a specific strategy? → Tune SL/TP or add confidence filter
- Is FT win rate diverging badly from BT win rate for any strategy? → Investigate regime change or overfitting
- Default: Run ML pipeline retraining for the strategy with the most FT data (highest ft_trades count) — compare new model vs current champion on OOS metrics

## STEP 5 — CREATE THE CARDS

Create **exactly 2 NQ cards and 1 Blofin card**. Each card needs:
1. POST to inbox to get the ID
2. PATCH to set status=Planned, assignee, description, project_path

```bash
# Create card
CARD=$(curl -s -X POST http://127.0.0.1:8787/api/inbox \
  -H "content-type: application/json" \
  -d '{"text":"TITLE HERE","source":"auto-generator","project_path":"/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE"}')
echo "$CARD"
CARD_ID=$(echo "$CARD" | python3 -c "import sys,json; print(json.load(sys.stdin)['card']['id'])")

# Set to Planned with full description
curl -s -X PATCH "http://127.0.0.1:8787/api/cards/$CARD_ID" \
  -H "content-type: application/json" \
  -d '{
    "status": "Planned",
    "assignee": "claude",
    "description": "FULL DETAILED TASK DESCRIPTION — this is the prompt the builder agent receives. Include: what to investigate/build, file paths, success criteria, what NOT to do (no live trading, no real orders)."
  }'
```

For Blofin cards: `"project_path":"/home/rob/.openclaw/workspace/blofin-stack"`

## STEP 6 — SUMMARY
Print exactly:
```
AUTO-GENERATOR: Created 3 cards
- [NQ] <card 1 title>
- [NQ] <card 2 title>  
- [Blofin] <card title>
```

## HARD RULES
- **Gate is non-negotiable**: if Planned + In Progress >= 2, do nothing and exit
- **Planned, not Inbox**: cards must be in Planned status so dispatcher picks them up
- **assignee must be "claude"** — always
- **Never duplicate**: check what's In Progress before deciding what to create
- **NEVER enable live trading, fire TradersPost webhooks, touch prop firm accounts, or activate any eval** — ever, under any circumstances
- **NQ paper trading only**: all NQ work is DRY_RUN / paper only — the smb_live_forward_test run_id
- **No live orders**: NQ God Model is for observation and paper trading, not execution
- **Be specific**: "Analyze gap_fill signal quality on live data and add a session volatility gate" not "improve gap_fill"
- **Include success criteria** in description so the builder knows when it's done
