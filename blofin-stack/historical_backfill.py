#!/usr/bin/env python3
import os
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import ccxt
from dotenv import load_dotenv

from db import connect, init_db

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

DB_PATH = os.getenv('BLOFIN_DB_PATH', str(ROOT / 'data' / 'blofin_monitor.db'))
SYMBOLS = [s.strip() for s in os.getenv('BLOFIN_SYMBOLS', 'BTC-USDT,ETH-USDT').split(',') if s.strip()]
TIMEFRAME = os.getenv('BACKFILL_TIMEFRAME', '1m')
LOOKBACK_DAYS = int(os.getenv('BACKFILL_LOOKBACK_DAYS', '7'))
BATCH_LIMIT = int(os.getenv('BACKFILL_BATCH_LIMIT', '1000'))
MAX_GAP_MINUTES = int(os.getenv('BACKFILL_MAX_GAP_MINUTES', '720'))

TF_MS = 60_000 if TIMEFRAME == '1m' else 60_000


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def get_recent_ticks(con: sqlite3.Connection, symbol: str, since_ms: int):
    cur = con.execute(
        'SELECT ts_ms, price FROM ticks WHERE symbol=? AND ts_ms>=? ORDER BY ts_ms ASC',
        (symbol, since_ms),
    )
    return cur.fetchall()


def detect_gaps(rows):
    gaps = []
    if len(rows) < 2:
        return gaps
    prev = rows[0][0]
    for r in rows[1:]:
        cur = r[0]
        d = cur - prev
        if d > TF_MS * 2:
            gap_minutes = d // TF_MS - 1
            gaps.append((prev + TF_MS, cur - TF_MS, int(gap_minutes)))
        prev = cur
    return gaps


def fetch_ohlcv_fill(exchange, symbol: str, start_ms: int, end_ms: int):
    inserted = []
    since = start_ms
    while since <= end_ms:
        candles = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, since=since, limit=BATCH_LIMIT)
        if not candles:
            break
        for c in candles:
            ts, o, h, l, close, vol = c
            if ts < start_ms or ts > end_ms:
                continue
            inserted.append((ts, close))
        last_ts = candles[-1][0]
        if last_ts <= since:
            break
        since = last_ts + TF_MS
        time.sleep(exchange.rateLimit / 1000.0)
    return inserted


def main():
    con = connect(DB_PATH)
    init_db(con)
    ex = ccxt.blofin({'enableRateLimit': True})

    now_ms = int(time.time() * 1000)
    since_ms = now_ms - LOOKBACK_DAYS * 24 * 60 * 60 * 1000

    total_rows = 0
    total_gaps = 0
    for sym in SYMBOLS:
        rows = get_recent_ticks(con, sym, since_ms)
        gaps = detect_gaps(rows)
        if not gaps:
            con.execute('INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, note) VALUES(?,?,?,?,?,?)',
                        (now_ms, iso(now_ms), sym, 0, 0, 'no gaps'))
            con.commit()
            continue

        gaps = [g for g in gaps if g[2] <= MAX_GAP_MINUTES]
        rows_inserted_sym = 0
        first_gap = gaps[0][0] if gaps else None
        last_gap = gaps[-1][1] if gaps else None

        for gstart, gend, gmins in gaps:
            candles = fetch_ohlcv_fill(ex, sym, gstart, gend)
            for ts, px in candles:
                con.execute(
                    'INSERT INTO ticks(ts_ms, ts_iso, symbol, price, source, raw_json) VALUES(?,?,?,?,?,?)',
                    (ts, iso(ts), sym, float(px), 'historical_fill', None),
                )
                rows_inserted_sym += 1

        con.execute('INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, first_gap_ts_ms, last_gap_ts_ms, note) VALUES(?,?,?,?,?,?,?,?)',
                    (now_ms, iso(now_ms), sym, len(gaps), rows_inserted_sym, first_gap, last_gap, f'tf={TIMEFRAME}'))
        con.commit()
        total_rows += rows_inserted_sym
        total_gaps += len(gaps)
        print(f'{sym}: gaps={len(gaps)} inserted={rows_inserted_sym}')

    print(f'DONE gaps={total_gaps} rows_inserted={total_rows}')


if __name__ == '__main__':
    main()
