#!/usr/bin/env python3
import asyncio
import json
import os
import random
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import websockets
from dotenv import load_dotenv

ROOT = Path('/home/rob/.openclaw/workspace/blofin-research')
load_dotenv(ROOT / '.env')

WS_URL = os.getenv('BLOFIN_WS_URL', 'wss://openapi.blofin.com/ws/public')
TOKENS = [t.strip() for t in os.getenv('BLOFIN_SYMBOLS', 'BTC-USDT,ETH-USDT,SOL-USDT').split(',') if t.strip()]
DB_PATH = Path(os.getenv('BLOFIN_DB_PATH', str(ROOT / 'data' / 'blofin.db')))
RAW_PATH = Path(os.getenv('BLOFIN_RAW_PATH', str(ROOT / 'data' / 'raw.jsonl')))
WINDOW_SECONDS = int(os.getenv('WINDOW_SECONDS', '300'))
MOMENTUM_PCT = float(os.getenv('MOMENTUM_PCT', '1.0'))
REVERSAL_PCT = float(os.getenv('REVERSAL_PCT', '0.7'))
BREAKOUT_LOOKBACK = int(os.getenv('BREAKOUT_LOOKBACK', '30'))
RECONNECT_MIN = int(os.getenv('RECONNECT_MIN_SECONDS', '2'))
RECONNECT_MAX = int(os.getenv('RECONNECT_MAX_SECONDS', '30'))

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
RAW_PATH.parent.mkdir(parents=True, exist_ok=True)

def now_ms() -> int:
    return int(time.time() * 1000)


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute('PRAGMA journal_mode=WAL;')
    con.execute('PRAGMA synchronous=NORMAL;')
    con.execute('''CREATE TABLE IF NOT EXISTS ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        price REAL NOT NULL,
        source TEXT DEFAULT 'blofin_ws'
    )''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts ON ticks(symbol, ts_ms)')
    con.execute('''CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_ms INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        signal TEXT NOT NULL,
        pattern TEXT NOT NULL,
        score REAL,
        price REAL,
        meta_json TEXT
    )''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts_ms)')
    con.commit()
    return con


def parse_tick(msg: dict):
    data = msg.get('data')
    if data is None:
        return None
    rows = data if isinstance(data, list) else [data]
    out = []
    for row in rows:
        sym = row.get('instId') or row.get('symbol') or row.get('s')
        p = row.get('last') or row.get('lastPrice') or row.get('price') or row.get('p')
        if not sym or p is None:
            continue
        try:
            out.append((sym, float(p)))
        except Exception:
            pass
    return out or None


class PatternEngine:
    def __init__(self):
        self.buffers = defaultdict(deque)

    def on_tick(self, symbol: str, ts: int, price: float):
        q = self.buffers[symbol]
        q.append((ts, price))
        cutoff = ts - WINDOW_SECONDS * 1000
        while q and q[0][0] < cutoff:
            q.popleft()

        events = []
        if len(q) < 8:
            return events

        first = q[0][1]
        move_pct = ((price - first) / first) * 100 if first else 0.0
        if move_pct >= MOMENTUM_PCT:
            events.append(("BUY", "momentum_up", move_pct))
        elif move_pct <= -MOMENTUM_PCT:
            events.append(("SELL", "momentum_down", move_pct))

        recent = [p for _, p in list(q)[-BREAKOUT_LOOKBACK:]]
        if len(recent) >= 10:
            hi = max(recent[:-1])
            lo = min(recent[:-1])
            if price > hi:
                events.append(("BUY", "breakout_high", ((price-hi)/hi)*100 if hi else 0.0))
            if price < lo:
                events.append(("SELL", "breakdown_low", ((price-lo)/lo)*100 if lo else 0.0))

            peak = max(recent)
            trough = min(recent)
            if peak and ((peak - price) / peak) * 100 >= REVERSAL_PCT:
                events.append(("SELL", "reversal_from_peak", ((peak-price)/peak)*100))
            if trough and ((price - trough) / trough) * 100 >= REVERSAL_PCT:
                events.append(("BUY", "reversal_from_trough", ((price-trough)/trough)*100))

        dedup = {(s, p): (s, p, score) for s, p, score in events}
        return list(dedup.values())


async def subscribe(ws):
    args = [{'channel': 'tickers', 'instId': s} for s in TOKENS]
    await ws.send(json.dumps({'op': 'subscribe', 'args': args}))


async def run():
    con = db()
    eng = PatternEngine()
    backoff = RECONNECT_MIN
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                await subscribe(ws)
                backoff = RECONNECT_MIN
                async for raw in ws:
                    ts = now_ms()
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    with RAW_PATH.open('a', encoding='utf-8') as f:
                        f.write(json.dumps({'ts_ms': ts, 'payload': msg}, ensure_ascii=False) + '\n')

                    parsed = parse_tick(msg)
                    if not parsed:
                        continue
                    for symbol, price in parsed:
                        con.execute('INSERT INTO ticks(ts_ms,symbol,price) VALUES(?,?,?)', (ts, symbol, price))
                        for signal, pattern, score in eng.on_tick(symbol, ts, price):
                            meta = {'window_seconds': WINDOW_SECONDS}
                            con.execute(
                                'INSERT INTO signals(ts_ms,symbol,signal,pattern,score,price,meta_json) VALUES(?,?,?,?,?,?,?)',
                                (ts, symbol, signal, pattern, float(score), float(price), json.dumps(meta)),
                            )
                    con.commit()
        except Exception as e:
            print(f'[reconnect] {e}')
            await asyncio.sleep(backoff + random.random())
            backoff = min(RECONNECT_MAX, max(RECONNECT_MIN, backoff * 2))


if __name__ == '__main__':
    print(f'Starting blofin stack for {len(TOKENS)} symbols -> {DB_PATH}')
    asyncio.run(run())
