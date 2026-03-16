# CRYPTO PIPELINES — Canonical Reference

**READ THIS EVERY SESSION BEFORE ANSWERING QUESTIONS ABOUT BLOFIN OR MOONSHOT.**

You are the crypto agent. You own both pipelines. Never confuse them.

---

## Pipeline 1: Blofin Stack

**What:** Strategy×coin tournament. Each strategy tests on 32+ coins independently. Winners = specific strategy+coin pairs.

**Dashboard:** http://127.0.0.1:8892
**Repo:** `blofin-stack/`
**DB:** `blofin-stack/data/blofin_monitor.db`

### Philosophy (NON-NEGOTIABLE)
- **95% of strategy×coin pairs lose money** — this is EXPECTED
- **We only care about the top 5% winners** (PF >1.35)
- **NEVER report aggregate metrics** (system-wide PF, total PnL, etc.)
- Always filter to profitable pairs FIRST, then report

### Current Winners (as of Mar 16 2026)
- reversal/BLAST-USDT: **PF 89.83**
- reversal/SHELL-USDT: **PF 63.45**
- candle_momentum_burst/XMR-USDT: **PF 30.08**
- Top 10 avg PF: **30.16**

### How to Query (CORRECT)

**Strategy×Coin Performance:**
```sql
-- Top performers (THE RIGHT WAY)
SELECT strategy_name, symbol, ft_trades, ft_profit_factor as ft_pf, ft_pnl_pct
FROM strategy_coin_performance
WHERE ft_trades >= 20
ORDER BY ft_profit_factor DESC LIMIT 10;
```

**Wrong columns that don't exist:**
- ❌ `strategy` (it's `strategy_name`)
- ❌ `ft_pf` in strategy_registry (it's `ft_profit_factor`)
- ❌ `pnl` in paper_trades (use calculation from entry/exit price)

### Services
- `blofin-stack-paper.service` — paper trading engine
- `blofin-dashboard.service` — dashboard (port 8892)
- Timer runs pipeline every 4h

### Key Files
- `orchestration/run_pipeline.py` — Phase 4 populates FT metrics
- `data/blofin_monitor.db` — all data
- `strategy_coin_performance` table — per-pair FT metrics (THE SOURCE OF TRUTH)

---

## Pipeline 2: Moonshot v2

**What:** Dual-track system:
1. **Rule-based entry** (NEW): Auto-enter ALL coins ≤7 days old, trailing stop exit
2. **ML tournament**: Generate challengers → backtest → FT → champion by PnL

**Dashboard:** http://127.0.0.1:8893
**Repo:** `blofin-moonshot-v2/`
**DB:** `blofin-moonshot-v2/data/moonshot_v2.db`

### Philosophy (NON-NEGOTIABLE)
- **95% of models lose money** — this is EXPECTED
- **We only care about top performers** (FT PnL, not aggregate)
- **NEVER report aggregate metrics**
- Rule-based new listing entry: expect 60% WR, PF 7.5 validated on 5 coins

### Current Winners (as of Mar 16 2026)
- Model de44f72d (short): **PF 2.22**, 388 trades, $0.68 profit
- Model 131bc99f (long): PF 1.01, 29,154 trades, $6.50 profit
- Short champion has 407 trades, $0.40 profit

### How to Query (CORRECT)

**Top Models:**
```python
db.execute("""
    SELECT model_id, direction, ft_pnl, ft_pf, ft_trades
    FROM tournament_models
    WHERE ft_trades >= 20
    ORDER BY ft_pnl DESC LIMIT 5
""")
```

**Positions:**
```python
# Use pnl_pct, not pnl
db.execute("SELECT symbol, direction, pnl_pct FROM positions WHERE status='closed'")
```

### Services
- `moonshot-v2.timer` — 4h cycle (discovery, backtest, FT, promotion)
- `moonshot-v2-social.timer` — 1h social data collection
- `moonshot-v2-dashboard.service` — dashboard (port 8893)

### Key Files
- `src/execution/new_listing_entry.py` — rule-based entry (NEW, deployed Mar 16)
- `orchestration/run_cycle.py` — main cycle
- `config.py` — NEW_LISTING_ENABLED=True
- `CORE_PHILOSOPHY.md` — read BEFORE any dashboard work

---

## When Rob Asks "How's Crypto Going?"

**NEVER say:**
- "Total PnL is..."
- "System-wide PF is..."
- "Win rate across all strategies..."

**ALWAYS say:**
1. **Blofin top 3 winners:** (strategy/coin, PF, trades)
2. **Moonshot top 3 models:** (model_id, direction, PF, FT PnL)
3. **New listing entries:** (count, avg PnL if any yet)

Filter to winners FIRST. Ignore the losers. They don't matter.

---

## Critical Mistakes to Avoid

1. ❌ Querying `strategy_registry` for per-coin FT metrics (it's aggregate)
2. ❌ Using column name `strategy` (it's `strategy_name`)
3. ❌ Using column name `ft_pf` (it's `ft_profit_factor`)
4. ❌ Reporting aggregate stats when asked "how's it going"
5. ❌ Confusing which pipeline you own (YOU OWN BOTH)

---

## Session Startup Checklist

Before answering ANY crypto question:
- [ ] Read this file (CRYPTO_PIPELINES.md)
- [ ] Read `blofin-stack/CORE_PHILOSOPHY.md`
- [ ] Read `blofin-moonshot-v2/CORE_PHILOSOPHY.md`
- [ ] Check both dashboards are up (ports 8892, 8893)
- [ ] Know the current top 3 winners in each pipeline

If you report aggregate stats, you failed.
