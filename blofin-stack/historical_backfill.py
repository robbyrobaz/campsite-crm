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


def floor_tf(ms: int) -> int:
    return (ms // TF_MS) * TF_MS


def get_recent_ticks(con: sqlite3.Connection, symbol: str, since_ms: int, until_ms: int):
    cur = con.execute(
        'SELECT ts_ms, price FROM ticks WHERE symbol=? AND ts_ms>=? AND ts_ms<=? ORDER BY ts_ms ASC',
        (symbol, since_ms, until_ms),
    )
    return cur.fetchall()


def detect_missing_ranges(rows, window_start_ms: int, window_end_ms: int):
    """Return [(start_ms, end_ms, missing_minutes), ...] within full target window."""
    if window_end_ms <= window_start_ms:
        return []

    ranges = []
    if not rows:
        missing_minutes = int((window_end_ms - window_start_ms) // TF_MS) + 1
        return [(window_start_ms, window_end_ms, missing_minutes)]

    # Leading missing range.
    first_ts = rows[0][0]
    if first_ts > window_start_ms:
        start = window_start_ms
        end = first_ts - TF_MS
        if end >= start:
            missing_minutes = int((end - start) // TF_MS) + 1
            ranges.append((start, end, missing_minutes))

    # Internal gaps.
    prev = first_ts
    for r in rows[1:]:
        cur = r[0]
        if cur - prev > TF_MS:
            start = prev + TF_MS
            end = cur - TF_MS
            missing_minutes = int((end - start) // TF_MS) + 1
            ranges.append((start, end, missing_minutes))
        prev = cur

    # Trailing missing range.
    last_ts = rows[-1][0]
    if last_ts < window_end_ms:
        start = last_ts + TF_MS
        end = window_end_ms
        if end >= start:
            missing_minutes = int((end - start) // TF_MS) + 1
            ranges.append((start, end, missing_minutes))

    return ranges


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
    window_end_ms = floor_tf(now_ms)
    window_start_ms = floor_tf(now_ms - LOOKBACK_DAYS * 24 * 60 * 60 * 1000)

    total_rows = 0
    total_gaps = 0
    for sym in SYMBOLS:
        rows = get_recent_ticks(con, sym, window_start_ms, window_end_ms)
        existing_ts = {int(r[0]) for r in rows}
        gaps = detect_missing_ranges(rows, window_start_ms, window_end_ms)
        if not gaps:
            con.execute(
                'INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, note) VALUES(?,?,?,?,?,?)',
                (now_ms, iso(now_ms), sym, 0, 0, f'window_covered tf={TIMEFRAME}'),
            )
            con.commit()
            continue

        # Keep very large internal outages optional, but always include edge ranges
        # so the 7-day target window can be backfilled from scratch.
        filtered = []
        for gstart, gend, gmins in gaps:
            touches_edge = gstart <= window_start_ms or gend >= window_end_ms
            if touches_edge or gmins <= MAX_GAP_MINUTES:
                filtered.append((gstart, gend, gmins))

        rows_inserted_sym = 0
        first_gap = filtered[0][0] if filtered else None
        last_gap = filtered[-1][1] if filtered else None

        for gstart, gend, gmins in filtered:
            candles = fetch_ohlcv_fill(ex, sym, gstart, gend)
            for ts, px in candles:
                if ts in existing_ts:
                    continue
                con.execute(
                    'INSERT INTO ticks(ts_ms, ts_iso, symbol, price, source, raw_json) VALUES(?,?,?,?,?,?)',
                    (ts, iso(ts), sym, float(px), 'historical_fill', None),
                )
                existing_ts.add(ts)
                rows_inserted_sym += 1

        note = f'tf={TIMEFRAME} window={LOOKBACK_DAYS}d max_gap={MAX_GAP_MINUTES}m'
        con.execute(
            'INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, first_gap_ts_ms, last_gap_ts_ms, note) VALUES(?,?,?,?,?,?,?,?)',
            (now_ms, iso(now_ms), sym, len(filtered), rows_inserted_sym, first_gap, last_gap, note),
        )
        con.commit()
        total_rows += rows_inserted_sym
        total_gaps += len(filtered)
        print(f'{sym}: gaps={len(filtered)} inserted={rows_inserted_sym}')

    print(f'DONE gaps={total_gaps} rows_inserted={total_rows}')


if __name__ == '__main__':
    main()
