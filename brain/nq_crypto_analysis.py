#!/usr/bin/env python3
"""NQ-Crypto Correlation Research"""
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Load NQ data
print("Loading NQ data...")
nq = pd.read_csv('/home/rob/.openclaw/workspace/NQ-Trading-PIPELINE/processed_data/NQ_continuous_1min.csv')
nq['datetime'] = pd.to_datetime(nq['datetime'])
nq = nq.set_index('datetime').sort_index()
nq['return'] = nq['close'].pct_change()
print(f"NQ: {len(nq)} rows, {nq.index.min()} to {nq.index.max()}")

# Load Blofin ticks
print("\nLoading Blofin data...")
db = sqlite3.connect('/home/rob/.openclaw/workspace/blofin-stack/data/blofin_monitor.db')

# Check ticks schema
schema = pd.read_sql("PRAGMA table_info(ticks)", db)
print(f"Ticks schema: {list(schema['name'])}")

# Get sample of ticks
sample = pd.read_sql("SELECT * FROM ticks LIMIT 5", db)
print(f"Sample tick: {sample.to_dict('records')[0] if len(sample) > 0 else 'empty'}")

# Get available symbols
symbols = pd.read_sql("SELECT DISTINCT symbol FROM ticks", db)
print(f"Available symbols: {list(symbols['symbol'])}")

# Load ticks for BTC, ETH, SOL (if available)
ticks = pd.read_sql("""
    SELECT * FROM ticks 
    WHERE symbol IN ('BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BTC', 'ETH', 'SOL', 
                     'BTCUSDT', 'ETHUSDT', 'SOLUSDT')
""", db)
print(f"Loaded {len(ticks)} ticks")

if len(ticks) == 0:
    # Try getting all ticks and see what we have
    all_ticks = pd.read_sql("SELECT symbol, COUNT(*) as cnt FROM ticks GROUP BY symbol ORDER BY cnt DESC LIMIT 20", db)
    print(f"All symbols in ticks:\n{all_ticks}")
    
# Check paper_trades
print("\n--- Paper Trades ---")
trades_schema = pd.read_sql("PRAGMA table_info(paper_trades)", db)
print(f"Paper trades schema: {list(trades_schema['name'])}")
trades = pd.read_sql("SELECT * FROM paper_trades", db)
print(f"Total paper trades: {len(trades)}")
if len(trades) > 0:
    print(f"Sample: {trades.head(2).to_dict('records')}")
    print(f"Symbols traded: {trades['symbol'].unique()[:10]}")
    print(f"Date range: {trades['opened_ts_iso'].min()} to {trades['opened_ts_iso'].max()}" if 'opened_ts_iso' in trades.columns else "no timestamp")

# Check signals table
print("\n--- Signals ---")
signals_schema = pd.read_sql("PRAGMA table_info(signals)", db)
print(f"Signals schema: {list(signals_schema['name'])}")
signals = pd.read_sql("SELECT * FROM signals LIMIT 5", db)
print(f"Sample signals: {signals.to_dict('records')[:2] if len(signals) > 0 else 'empty'}")

db.close()
