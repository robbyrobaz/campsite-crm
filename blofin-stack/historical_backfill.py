#!/usr/bin/env python3
import os
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from db import connect, init_db

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

DB_PATH = os.getenv('BLOFIN_DB_PATH', str(ROOT / 'data' / 'blofin_monitor.db'))
SYMBOLS = [s.strip() for s in os.getenv('BLOFIN_SYMBOLS', 'BTC-USDT,ETH-USDT').split(',') if s.strip()]
TIMEFRAME = os.getenv('BACKFILL_TIMEFRAME', '1m')
LOOKBACK_DAYS = int(os.getenv('BACKFILL_LOOKBACK_DAYS', '7'))
BATCH_LIMIT = min(100, max(1, int(os.getenv('BACKFILL_BATCH_LIMIT', '60'))))
MAX_GAP_MINUTES = int(os.getenv('BACKFILL_MAX_GAP_MINUTES', '10080'))
LOOP_SECONDS = int(os.getenv('BACKFILL_LOOP_SECONDS', '0'))
REQUEST_SLEEP_MS = max(0, int(os.getenv('BACKFILL_REQUEST_SLEEP_MS', '400')))
SYMBOL_SLEEP_MS = max(0, int(os.getenv('BACKFILL_SYMBOL_SLEEP_MS', '1000')))

TF_MS = 60_000 if TIMEFRAME == '1m' else 60_000


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def floor_tf(ms: int) -> int:
    return (ms // TF_MS) * TF_MS


def get_existing_minute_set(con: sqlite3.Connection, symbol: str, since_ms: int, until_ms: int) -> set[int]:
    cur = con.execute(
        '''
        SELECT DISTINCT ((ts_ms / ?) * ?) AS minute_ts
        FROM ticks
        WHERE symbol=? AND ts_ms>=? AND ts_ms<=?
        ''',
        (TF_MS, TF_MS, symbol, since_ms, until_ms),
    )
    return {int(r[0]) for r in cur.fetchall() if r[0] is not None}


def build_missing_ranges(existing_minutes: set[int], window_start_ms: int, window_end_ms: int) -> list[tuple[int, int, int]]:
    expected_count = int((window_end_ms - window_start_ms) // TF_MS) + 1
    expected = [window_start_ms + (i * TF_MS) for i in range(expected_count)]
    missing = [ts for ts in expected if ts not in existing_minutes]
    if not missing:
        return []

    ranges = []
    start = prev = missing[0]
    for ts in missing[1:]:
        if ts == prev + TF_MS:
            prev = ts
            continue
        mins = int((prev - start) // TF_MS) + 1
        ranges.append((start, prev, mins))
        start = prev = ts

    mins = int((prev - start) // TF_MS) + 1
    ranges.append((start, prev, mins))
    return ranges


def split_large_ranges(ranges: list[tuple[int, int, int]], max_gap_minutes: int) -> list[tuple[int, int, int]]:
    if max_gap_minutes <= 0:
        return ranges

    chunk_span_ms = max_gap_minutes * TF_MS
    out: list[tuple[int, int, int]] = []
    for start, end, _mins in ranges:
        cur = start
        while cur <= end:
            chunk_end = min(end, cur + chunk_span_ms - TF_MS)
            chunk_mins = int((chunk_end - cur) // TF_MS) + 1
            out.append((cur, chunk_end, chunk_mins))
            cur = chunk_end + TF_MS
    return out


def fetch_ohlcv_fill(exchange, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
    fetched: dict[int, float] = {}
    cursor_since = start_ms

    # Config uses websocket-style ids (e.g. BTC-USDT). CCXT expects unified symbols
    # (e.g. BTC/USDT:USDT), so resolve first and skip unavailable markets.
    market = exchange.markets_by_id.get(symbol)
    if not market:
        return []
    ccxt_symbol = market[0]['symbol']

    while cursor_since <= end_ms:
        candles = exchange.fetch_ohlcv(
            ccxt_symbol,
            timeframe=TIMEFRAME,
            since=cursor_since,
            limit=BATCH_LIMIT,
        )
        if not candles:
            break

        newest_ts = None
        for c in candles:
            ts, _o, _h, _l, close, _vol = c
            ts = floor_tf(int(ts))
            if newest_ts is None or ts > newest_ts:
                newest_ts = ts
            if ts < start_ms or ts > end_ms:
                continue
            fetched[ts] = float(close)

        if newest_ts is None:
            break

        next_cursor = newest_ts + TF_MS
        if next_cursor <= cursor_since:
            break
        cursor_since = next_cursor
        sleep_s = max(exchange.rateLimit / 1000.0, REQUEST_SLEEP_MS / 1000.0)
        time.sleep(sleep_s)

    return sorted(fetched.items())


def run_once(con: sqlite3.Connection, ex) -> tuple[int, int]:
    now_ms = int(time.time() * 1000)
    window_end_ms = floor_tf(now_ms)
    window_start_ms = floor_tf(now_ms - LOOKBACK_DAYS * 24 * 60 * 60 * 1000)
    expected_points = int((window_end_ms - window_start_ms) // TF_MS) + 1

    total_rows = 0
    total_gaps = 0

    for sym in SYMBOLS:
        try:
            if sym not in ex.markets_by_id:
                con.execute(
                    'INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, note) VALUES(?,?,?,?,?,?)',
                    (now_ms, iso(now_ms), sym, 0, 0, 'skipped: symbol unavailable on Blofin'),
                )
                con.commit()
                print(f'{sym}: skipped (unavailable)')
                continue

            existing = get_existing_minute_set(con, sym, window_start_ms, window_end_ms)
            missing_ranges = build_missing_ranges(existing, window_start_ms, window_end_ms)

            filtered = split_large_ranges(missing_ranges, MAX_GAP_MINUTES)

            rows_inserted_sym = 0
            first_gap = filtered[0][0] if filtered else None
            last_gap = filtered[-1][1] if filtered else None

            for gstart, gend, _gmins in filtered:
                candles = fetch_ohlcv_fill(ex, sym, gstart, gend)
                for ts, px in candles:
                    if ts in existing:
                        continue
                    con.execute(
                        'INSERT INTO ticks(ts_ms, ts_iso, symbol, price, source, raw_json) VALUES(?,?,?,?,?,?)',
                        (ts, iso(ts), sym, float(px), 'historical_fill', None),
                    )
                    existing.add(ts)
                    rows_inserted_sym += 1

            note = (
                f'tf={TIMEFRAME} window={LOOKBACK_DAYS}d '
                f'points={len(existing)}/{expected_points} max_gap={MAX_GAP_MINUTES}m'
            )
            con.execute(
                'INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, first_gap_ts_ms, last_gap_ts_ms, note) VALUES(?,?,?,?,?,?,?,?)',
                (now_ms, iso(now_ms), sym, len(filtered), rows_inserted_sym, first_gap, last_gap, note),
            )
            con.commit()

            total_rows += rows_inserted_sym
            total_gaps += len(filtered)
            print(f'{sym}: gaps={len(filtered)} inserted={rows_inserted_sym} points={len(existing)}/{expected_points}')
        except Exception as e:
            con.execute(
                'INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, note) VALUES(?,?,?,?,?,?)',
                (now_ms, iso(now_ms), sym, 0, 0, f'error: {type(e).__name__}: {e}'),
            )
            con.commit()
            print(f'{sym}: error={e}')
        finally:
            if SYMBOL_SLEEP_MS > 0:
                time.sleep(SYMBOL_SLEEP_MS / 1000.0)

    print(f'DONE gaps={total_gaps} rows_inserted={total_rows}')
    return total_gaps, total_rows


def main():
    import ccxt

    con = connect(DB_PATH)
    init_db(con)
    ex = ccxt.blofin({'enableRateLimit': True})
    ex.load_markets()

    if LOOP_SECONDS > 0:
        while True:
            run_once(con, ex)
            time.sleep(max(60, LOOP_SECONDS))
    else:
        run_once(con, ex)


if __name__ == '__main__':
    main()
