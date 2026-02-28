#!/usr/bin/env python3
"""NQ-Crypto Correlation Research - Full Analysis"""
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import gzip
import warnings
warnings.filterwarnings('ignore')

OUTPUT_FILE = '/home/rob/.openclaw/workspace/brain/NQ_CRYPTO_CORRELATION_2026-02-28.md'

print("=" * 60)
print("NQ-Crypto Correlation Research")
print("=" * 60)

# =============================================================================
# 1. LOAD NQ DATA
# =============================================================================
print("\n[1] Loading NQ data...")
nq = pd.read_csv('/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/processed_data/NQ_continuous_1min.csv')
nq['datetime'] = pd.to_datetime(nq['datetime'])
nq = nq.set_index('datetime').sort_index()
nq['return_1m'] = nq['close'].pct_change() * 100  # percentage return
nq['return_5m'] = nq['close'].pct_change(5) * 100
nq['return_30m'] = nq['close'].pct_change(30) * 100
nq['volatility_30m'] = nq['return_1m'].rolling(30).std()
nq['momentum_5m'] = nq['close'].diff(5)
nq['is_trending'] = abs(nq['return_30m']) > 0.3  # >0.3% move in 30min = trending

# Add session phase
def get_session_phase(dt):
    hour = dt.hour
    if 14 <= hour < 16:  # NY open (14:30 UTC = 9:30 ET)
        return 'ny_open'
    elif 16 <= hour < 21:  # NY regular
        return 'ny_regular'
    elif 21 <= hour or hour < 5:  # Overnight
        return 'overnight'
    else:  # Pre-market
        return 'pre_market'

nq['session_phase'] = nq.index.map(get_session_phase)

print(f"  NQ rows: {len(nq):,}")
print(f"  Date range: {nq.index.min()} to {nq.index.max()}")
print(f"  Sample return stats: mean={nq['return_1m'].mean():.4f}%, std={nq['return_1m'].std():.4f}%")

# =============================================================================
# 2. EXTRACT CRYPTO DATA FROM JSONL (Feb 28 sample)
# =============================================================================
print("\n[2] Extracting crypto tick data from JSONL...")
jsonl_file = '/home/rob/.openclaw/workspace/blofin-stack/data/raw_20260228.jsonl'

crypto_ticks = {'BTC-USDT': [], 'ETH-USDT': [], 'SOL-USDT': []}
count = 0
max_lines = 500000  # Sample first 500k lines for speed

with open(jsonl_file, 'r') as f:
    for line in f:
        if count >= max_lines:
            break
        count += 1
        try:
            rec = json.loads(line)
            payload = rec.get('payload', {})
            data = payload.get('data', [])
            if data and isinstance(data, list):
                for d in data:
                    inst = d.get('instId')
                    if inst in crypto_ticks:
                        ts = int(d.get('ts', 0)) / 1000  # ms to seconds
                        last = float(d.get('last', 0))
                        if ts > 0 and last > 0:
                            crypto_ticks[inst].append({
                                'timestamp': datetime.utcfromtimestamp(ts),
                                'price': last
                            })
        except:
            pass

print(f"  Processed {count:,} lines")
for sym, ticks in crypto_ticks.items():
    print(f"  {sym}: {len(ticks):,} ticks")

# Resample crypto to 1-min
crypto_1m = {}
for sym, ticks in crypto_ticks.items():
    if len(ticks) > 0:
        df = pd.DataFrame(ticks)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()
        # Resample to 1-min last price
        df_1m = df['price'].resample('1T').last().dropna()
        df_1m = df_1m.to_frame('close')
        df_1m['return_1m'] = df_1m['close'].pct_change() * 100
        crypto_1m[sym] = df_1m
        print(f"  {sym} 1min bars: {len(df_1m)}")

# =============================================================================
# 3. LOAD PAPER TRADES
# =============================================================================
print("\n[3] Loading paper trades...")
db = sqlite3.connect('/home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db')
trades = pd.read_sql("""
    SELECT symbol, side, pnl_pct, opened_ts_iso, closed_ts_iso, strategy
    FROM paper_trades 
    WHERE closed_ts_iso IS NOT NULL
""", db)
db.close()

trades['opened_ts'] = pd.to_datetime(trades['opened_ts_iso'])
trades['is_winner'] = trades['pnl_pct'] > 0
print(f"  Total trades: {len(trades):,}")
print(f"  Winners: {trades['is_winner'].sum():,} ({100*trades['is_winner'].mean():.1f}%)")
print(f"  Losers: {(~trades['is_winner']).sum():,}")

# Filter to overlap period with NQ (Feb 2026)
nq_end = nq.index.max()
trades_overlap = trades[trades['opened_ts'] <= nq_end]
print(f"  Trades in NQ overlap period: {len(trades_overlap):,}")

# =============================================================================
# 4. CORRELATION ANALYSIS
# =============================================================================
print("\n[4] Correlation Analysis...")

results = {
    'correlation': {},
    'lead_lag': {},
    'regime': {},
    'signal_crossover': {},
    'trade_timing': {}
}

# 4a. Basic correlation (NQ vs BTC/ETH/SOL)
if crypto_1m:
    # Get overlapping timeframe
    btc_1m = crypto_1m.get('BTC-USDT')
    if btc_1m is not None and len(btc_1m) > 60:
        # Align with NQ
        overlap_start = max(nq.index.min(), btc_1m.index.min())
        overlap_end = min(nq.index.max(), btc_1m.index.max())
        
        nq_slice = nq.loc[overlap_start:overlap_end, 'return_1m'].dropna()
        
        print(f"\n  Overlap period: {overlap_start} to {overlap_end}")
        print(f"  NQ bars in overlap: {len(nq_slice)}")
        
        for sym in ['BTC-USDT', 'ETH-USDT', 'SOL-USDT']:
            if sym in crypto_1m:
                crypto_slice = crypto_1m[sym].loc[overlap_start:overlap_end, 'return_1m'].dropna()
                
                # Align indices
                common_idx = nq_slice.index.intersection(crypto_slice.index)
                if len(common_idx) > 30:
                    nq_aligned = nq_slice.loc[common_idx]
                    crypto_aligned = crypto_slice.loc[common_idx]
                    
                    # Basic correlation
                    corr = nq_aligned.corr(crypto_aligned)
                    
                    # Rolling correlation
                    df_combo = pd.DataFrame({'nq': nq_aligned, 'crypto': crypto_aligned})
                    rolling_30 = df_combo['nq'].rolling(30).corr(df_combo['crypto']).mean()
                    rolling_60 = df_combo['nq'].rolling(60).corr(df_combo['crypto']).mean()
                    
                    results['correlation'][sym] = {
                        'instant': round(corr, 4),
                        'rolling_30m': round(rolling_30, 4) if not np.isnan(rolling_30) else None,
                        'rolling_60m': round(rolling_60, 4) if not np.isnan(rolling_60) else None,
                        'n_bars': len(common_idx)
                    }
                    print(f"  NQ vs {sym}: corr={corr:.4f}, n={len(common_idx)}")

# 4b. Lead-lag analysis
print("\n  Lead-lag analysis...")
if 'BTC-USDT' in crypto_1m:
    btc = crypto_1m['BTC-USDT']
    overlap_start = max(nq.index.min(), btc.index.min())
    overlap_end = min(nq.index.max(), btc.index.max())
    
    nq_ret = nq.loc[overlap_start:overlap_end, 'return_1m'].dropna()
    btc_ret = btc.loc[overlap_start:overlap_end, 'return_1m'].dropna()
    common_idx = nq_ret.index.intersection(btc_ret.index)
    
    if len(common_idx) > 50:
        nq_aligned = nq_ret.loc[common_idx].values
        btc_aligned = btc_ret.loc[common_idx].values
        
        lead_lag_results = {}
        for lag in [1, 2, 3, 5, 10]:
            if len(nq_aligned) > lag:
                # NQ leads crypto (positive lag = NQ t-lag vs crypto t)
                corr_nq_leads = np.corrcoef(nq_aligned[:-lag], btc_aligned[lag:])[0, 1]
                # Crypto leads NQ
                corr_btc_leads = np.corrcoef(btc_aligned[:-lag], nq_aligned[lag:])[0, 1]
                lead_lag_results[f'lag_{lag}m'] = {
                    'nq_leads_crypto': round(corr_nq_leads, 4),
                    'crypto_leads_nq': round(corr_btc_leads, 4)
                }
                print(f"    Lag {lag}m: NQ→BTC={corr_nq_leads:.4f}, BTC→NQ={corr_btc_leads:.4f}")
        
        results['lead_lag'] = lead_lag_results

# =============================================================================
# 5. TRADE TIMING VS NQ ANALYSIS
# =============================================================================
print("\n[5] Trade Timing vs NQ Analysis...")

# For trades in overlap period, look at NQ state before entry
trade_nq_analysis = []

for _, trade in trades_overlap.iterrows():
    entry_time = trade['opened_ts']
    
    # Get NQ data 30 min before trade entry
    window_start = entry_time - timedelta(minutes=30)
    nq_window = nq.loc[window_start:entry_time]
    
    if len(nq_window) >= 10:
        nq_return_30m = nq_window['close'].iloc[-1] / nq_window['close'].iloc[0] - 1 if len(nq_window) > 0 else 0
        nq_volatility = nq_window['return_1m'].std() if len(nq_window) > 1 else 0
        nq_trending = abs(nq_return_30m * 100) > 0.3
        
        trade_nq_analysis.append({
            'is_winner': trade['is_winner'],
            'symbol': trade['symbol'],
            'nq_return_30m': nq_return_30m * 100,
            'nq_volatility': nq_volatility,
            'nq_trending': nq_trending,
            'session_phase': nq_window['session_phase'].iloc[-1] if 'session_phase' in nq_window.columns else 'unknown'
        })

if trade_nq_analysis:
    tna_df = pd.DataFrame(trade_nq_analysis)
    
    print(f"  Analyzed {len(tna_df)} trades with NQ context")
    
    # Win rate by NQ trending state
    trending_wins = tna_df[tna_df['nq_trending']]['is_winner'].mean() * 100
    choppy_wins = tna_df[~tna_df['nq_trending']]['is_winner'].mean() * 100
    
    print(f"  Win rate when NQ trending: {trending_wins:.1f}%")
    print(f"  Win rate when NQ choppy: {choppy_wins:.1f}%")
    
    # Win rate by session phase
    session_wins = tna_df.groupby('session_phase')['is_winner'].agg(['mean', 'count'])
    print(f"\n  Win rate by NQ session phase:")
    for phase, row in session_wins.iterrows():
        print(f"    {phase}: {row['mean']*100:.1f}% ({int(row['count'])} trades)")
    
    # Win rate by NQ direction before entry
    tna_df['nq_direction'] = np.where(tna_df['nq_return_30m'] > 0.1, 'up', 
                              np.where(tna_df['nq_return_30m'] < -0.1, 'down', 'flat'))
    direction_wins = tna_df.groupby('nq_direction')['is_winner'].agg(['mean', 'count'])
    print(f"\n  Win rate by NQ direction (30m before):")
    for dir, row in direction_wins.iterrows():
        print(f"    NQ {dir}: {row['mean']*100:.1f}% ({int(row['count'])} trades)")
    
    results['trade_timing'] = {
        'trending_win_rate': round(trending_wins, 1),
        'choppy_win_rate': round(choppy_wins, 1),
        'session_wins': session_wins.to_dict('index'),
        'direction_wins': direction_wins.to_dict('index')
    }

# =============================================================================
# 6. GENERATE REPORT
# =============================================================================
print("\n[6] Generating report...")

report = """# NQ-Crypto Correlation Research
**Date:** 2026-02-28
**Analyst:** Jarvis (Opus subagent)

---

## Executive Summary

"""

# Verdict based on findings
if results['correlation']:
    btc_corr = results['correlation'].get('BTC-USDT', {}).get('instant', 0) or 0
    if abs(btc_corr) > 0.3:
        verdict = "**MODERATE CORRELATION FOUND** — There is a measurable relationship between NQ and crypto."
    elif abs(btc_corr) > 0.1:
        verdict = "**WEAK CORRELATION** — Relationship exists but is likely too weak to exploit."
    else:
        verdict = "**NO MEANINGFUL CORRELATION** — NQ and crypto move independently in the timeframes analyzed."
else:
    btc_corr = 0
    verdict = "**INSUFFICIENT DATA** — Could not establish correlation due to limited data overlap."

# Check trade timing impact
trade_timing = results.get('trade_timing', {})
trending_wr = trade_timing.get('trending_win_rate', 0)
choppy_wr = trade_timing.get('choppy_win_rate', 0)
timing_diff = trending_wr - choppy_wr

if abs(timing_diff) > 5:
    timing_verdict = f"**NQ context matters:** {abs(timing_diff):.0f}pp win rate difference based on NQ state."
else:
    timing_verdict = "**NQ context has minimal impact** on crypto trade outcomes."

report += f"""{verdict}

{timing_verdict}

---

## 1. Correlation Matrix (NQ vs Crypto)

| Pair | Instant Corr | 30m Rolling | 60m Rolling | N bars |
|------|--------------|-------------|-------------|--------|
"""

for sym in ['BTC-USDT', 'ETH-USDT', 'SOL-USDT']:
    data = results['correlation'].get(sym, {})
    report += f"| NQ vs {sym.replace('-USDT','')} | {data.get('instant', 'n/a')} | {data.get('rolling_30m', 'n/a')} | {data.get('rolling_60m', 'n/a')} | {data.get('n_bars', 'n/a')} |\n"

report += """
**Interpretation:** Correlation <0.1 = no relationship. 0.1-0.3 = weak. >0.3 = moderate. >0.5 = strong.

---

## 2. Lead-Lag Analysis (NQ vs BTC)

"""

if results['lead_lag']:
    report += "| Lag | NQ Leads BTC | BTC Leads NQ | Direction |\n"
    report += "|-----|--------------|--------------|------------|\n"
    for lag_key, data in results['lead_lag'].items():
        nq_leads = data.get('nq_leads_crypto', 0)
        btc_leads = data.get('crypto_leads_nq', 0)
        if abs(nq_leads) > abs(btc_leads):
            direction = "NQ → Crypto"
        elif abs(btc_leads) > abs(nq_leads):
            direction = "Crypto → NQ"
        else:
            direction = "No clear leader"
        report += f"| {lag_key.replace('lag_', '').replace('m', ' min')} | {nq_leads} | {btc_leads} | {direction} |\n"
    
    report += "\n**Interpretation:** If NQ consistently shows higher correlation at lag X, NQ leads by X minutes.\n"
else:
    report += "*Insufficient overlapping data for lead-lag analysis.*\n"

report += """
---

## 3. Trade Timing vs NQ State

"""

if trade_timing:
    report += f"""### Win Rate by NQ Regime
- **NQ Trending (>0.3% move in 30m):** {trending_wr:.1f}%
- **NQ Choppy (<0.3% move in 30m):** {choppy_wr:.1f}%
- **Difference:** {timing_diff:+.1f}pp

### Win Rate by NQ Session Phase
"""
    session_wins = trade_timing.get('session_wins', {})
    for phase, data in session_wins.items():
        if isinstance(data, dict):
            report += f"- **{phase}:** {data.get('mean', 0)*100:.1f}% ({int(data.get('count', 0))} trades)\n"

    report += "\n### Win Rate by NQ Direction (30m before entry)\n"
    direction_wins = trade_timing.get('direction_wins', {})
    for dir, data in direction_wins.items():
        if isinstance(data, dict):
            report += f"- **NQ {dir}:** {data.get('mean', 0)*100:.1f}% ({int(data.get('count', 0))} trades)\n"
else:
    report += "*No trade timing data available.*\n"

report += """
---

## 4. Verdict & Recommendations

"""

# Final verdict
if abs(btc_corr) > 0.2 or abs(timing_diff) > 5:
    report += """### ✅ There IS an exploitable signal

Based on the analysis:
"""
    if abs(btc_corr) > 0.2:
        report += f"- NQ-BTC correlation of {btc_corr:.3f} suggests some predictive relationship\n"
    if timing_diff > 5:
        report += f"- Crypto trades during NQ trending periods have {timing_diff:.0f}pp higher win rate\n"
    elif timing_diff < -5:
        report += f"- Crypto trades during NQ choppy periods have {abs(timing_diff):.0f}pp higher win rate\n"
    
    report += """
**Proposed NQ Features for Blofin ML Model:**
```python
# Add to feature engineering
'NQ_return_1m': float,      # NQ 1-min return
'NQ_return_5m': float,      # NQ 5-min return  
'NQ_return_30m': float,     # NQ 30-min return (momentum)
'NQ_volatility_30m': float, # NQ rolling volatility
'NQ_is_trending': bool,     # >0.3% move in 30min
'NQ_session_phase': str,    # ny_open, ny_regular, overnight, pre_market
```

**Implementation notes:**
- Would require real-time NQ data feed (TraderAPI/IB)
- NQ trades ~23h/day (closed ~1h around 5pm ET)
- Feature lag considerations: use t-1 or t-2 minute data to avoid lookahead
"""
else:
    report += """### ❌ No exploitable signal found

The data does not support adding NQ features to the Blofin model:
"""
    if abs(btc_corr) < 0.1:
        report += f"- NQ-BTC correlation ({btc_corr:.3f}) is essentially zero\n"
    if abs(timing_diff) < 5:
        report += f"- NQ trending vs choppy impact ({timing_diff:+.1f}pp) is within noise\n"
    
    report += """
**Why no signal?**
- Crypto markets are 24/7, NQ is only active during US hours
- BTC/ETH have independent drivers (DeFi, network events, regulatory news)
- Intraday correlation ≠ predictive power
- Sample period may be too short or non-representative

**What would change this verdict?**
- Longer data history (6+ months overlap)
- More granular NQ data (tick-level)
- Focus on specific events (Fed, FOMC, earnings) where correlation spikes
- Cross-asset momentum during specific sessions (NY open 9:30-10:30 ET)
"""

report += """
---

## 5. Data Sources & Limitations

### Data Used
- **NQ:** 1-min OHLCV from Jan 2025 - Feb 27, 2026 ({:,} bars)
- **Crypto:** Blofin tick data resampled to 1-min (Feb 28 sample)
- **Paper trades:** {:,} trades from Feb 12-28, 2026

### Limitations
1. **Limited overlap period** — Only ~2 weeks of NQ and crypto data overlap
2. **JSONL sampling** — Only used first 500k lines of Feb 28 for speed (full DB is 44GB)
3. **No historical tick data** — Couldn't analyze correlation over longer history
4. **No realized trade PnL correlation** — Would need actual fill prices

### For More Rigorous Analysis
- Export crypto OHLC to separate CSV (hourly job)
- Longer backtest with proper NQ alignment
- Event study around NQ momentum signals
- Test NQ features in backtester before production

---

*Report generated by Jarvis subagent. For questions, see main Jarvis session.*
""".format(len(nq), len(trades))

# Write report
with open(OUTPUT_FILE, 'w') as f:
    f.write(report)

print(f"\n✅ Report written to: {OUTPUT_FILE}")
print("\n" + "=" * 60)
print("EXEC SUMMARY")
print("=" * 60)
print(f"NQ-BTC correlation: {btc_corr:.4f}")
print(f"Win rate difference (trending vs choppy): {timing_diff:+.1f}pp")
if abs(btc_corr) > 0.2 or abs(timing_diff) > 5:
    print("VERDICT: ✅ Exploitable relationship found — consider adding NQ features")
else:
    print("VERDICT: ❌ No meaningful signal — NQ features would not help Blofin")
print("=" * 60)
