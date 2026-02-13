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
LOOKBACK_HOURS = int(os.getenv('BACKFILL_LOOKBACK_HOURS', '168'))
BATCH_LIMIT = min(1000, max(1, int(os.getenv('BACKFILL_BATCH_LIMIT', '1000'))))
MAX_GAP_MINUTES = int(os.getenv('BACKFILL_MAX_GAP_MINUTES', '10080'))
LOOP_SECONDS = int(os.getenv('BACKFILL_LOOP_SECONDS', '0'))
REQUEST_SLEEP_MS = max(0, int(os.getenv('BACKFILL_REQUEST_SLEEP_MS', '200')))
SYMBOL_SLEEP_MS = max(0, int(os.getenv('BACKFILL_SYMBOL_SLEEP_MS', '500')))

TF_MS = 60_000 if TIMEFRAME == '1m' else 60_000


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def floor_tf(ms: int) -> int:
    return (ms // TF_MS) * TF_MS


def map_blofin_to_external_symbol(blofin_symbol: str, external_markets: dict) -> str | None:
    """
    Map Blofin-style symbols (BTC-USDT) to external exchange symbols (BTC/USDT).
    
    Returns the external symbol if found, None otherwise.
    """
    # Basic mapping: BTC-USDT -> BTC/USDT
    base_attempt = blofin_symbol.replace('-', '/')
    if base_attempt in external_markets:
        return base_attempt
    
    # Handle special cases like 1000BONK-USDT
    # Some exchanges have it as 1000BONK/USDT or BONK/USDT
    if blofin_symbol.startswith('1000'):
        # Try with the 1000 prefix first
        with_prefix = blofin_symbol.replace('-', '/')
        if with_prefix in external_markets:
            return with_prefix
        # Try without the 1000 prefix
        without_prefix = blofin_symbol[4:].replace('-', '/')
        if without_prefix in external_markets:
            return without_prefix
    
    return None


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
    """Split large gaps into smaller chunks for gradual filling. If max_gap_minutes=0, return all gaps unmodified."""
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


def fetch_ohlcv_external(exchange, external_symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
    """Fetch OHLCV data from external exchange for the given range."""
    fetched: dict[int, float] = {}
    cursor_since = start_ms

    while cursor_since <= end_ms:
        try:
            candles = exchange.fetch_ohlcv(
                external_symbol,
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
        except Exception as e:
            print(f'  External exchange fetch error for {external_symbol}: {e}')
            break

    return sorted(fetched.items())


def fetch_ohlcv_blofin(exchange, blofin_symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
    """Fetch OHLCV data from Blofin for the given range (limited to ~1-2 hours)."""
    fetched: dict[int, float] = {}
    cursor_since = start_ms

    # Map Blofin websocket-style id to CCXT symbol
    market = exchange.markets_by_id.get(blofin_symbol)
    if not market:
        return []
    ccxt_symbol = market[0]['symbol']

    while cursor_since <= end_ms:
        try:
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
        except Exception as e:
            print(f'  Blofin fetch error for {blofin_symbol}: {e}')
            break

    return sorted(fetched.items())


def fetch_ohlcv_multi_exchange(external_ex, blofin_ex, blofin_symbol: str, start_ms: int, end_ms: int, external_name: str) -> tuple[list[tuple[int, float]], str]:
    """
    Fetch OHLCV data using external exchange first, falling back to Blofin if needed.
    Returns (data, source_exchange_name).
    """
    # Skip external exchange if it's the same as Blofin (no external available)
    if external_ex is not blofin_ex:
        # Try external exchange first (OKX, Bybit, etc.)
        external_symbol = map_blofin_to_external_symbol(blofin_symbol, external_ex.markets)
        if external_symbol:
            print(f'  Trying {external_name}: {blofin_symbol} -> {external_symbol}')
            data = fetch_ohlcv_external(external_ex, external_symbol, start_ms, end_ms)
            if data:
                return data, f'historical_fill_{external_name.lower()}'
            print(f'  {external_name} returned no data, falling back to Blofin')
        else:
            print(f'  {blofin_symbol} not found on {external_name}, using Blofin')
    
    # Fall back to Blofin (or use Blofin directly if no external exchange)
    data = fetch_ohlcv_blofin(blofin_ex, blofin_symbol, start_ms, end_ms)
    return data, 'historical_fill_blofin'


def compute_window_bounds(now_ms: int, lookback_hours: int) -> tuple[int, int]:
    """Return inclusive [start,end] bounds for fully closed candles only."""
    window_end_ms = floor_tf(now_ms - TF_MS)
    window_start_ms = floor_tf(window_end_ms - lookback_hours * 60 * 60 * 1000)
    return window_start_ms, window_end_ms


def run_once(con: sqlite3.Connection, external_ex, blofin_ex, external_name: str) -> tuple[int, int]:
    now_ms = int(time.time() * 1000)
    window_start_ms, window_end_ms = compute_window_bounds(now_ms, LOOKBACK_HOURS)
    expected_points = int((window_end_ms - window_start_ms) // TF_MS) + 1

    total_rows = 0
    total_gaps = 0

    print(f'\n=== Historical Backfill ===')
    print(f'Window: {iso(window_start_ms)} to {iso(window_end_ms)}')
    print(f'Lookback: {LOOKBACK_HOURS} hours ({expected_points} expected 1m candles)')
    print(f'Symbols: {len(SYMBOLS)}\n')

    for sym in SYMBOLS:
        try:
            existing = get_existing_minute_set(con, sym, window_start_ms, window_end_ms)
            missing_ranges = build_missing_ranges(existing, window_start_ms, window_end_ms)

            if not missing_ranges:
                coverage_pct = 100.0
                print(f'{sym}: ✓ Complete coverage ({len(existing)}/{expected_points})')
                con.execute(
                    'INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, note) VALUES(?,?,?,?,?,?)',
                    (now_ms, iso(now_ms), sym, 0, 0, f'complete coverage: {coverage_pct}%'),
                )
                con.commit()
                continue

            filtered = split_large_ranges(missing_ranges, MAX_GAP_MINUTES)

            rows_inserted_sym = 0
            first_gap = filtered[0][0] if filtered else None
            last_gap = filtered[-1][1] if filtered else None
            
            coverage_before = len(existing)
            print(f'{sym}: Found {len(filtered)} gap(s), missing {len(existing) - expected_points} of {expected_points} candles')

            for gstart, gend, gmins in filtered:
                print(f'  Filling gap: {iso(gstart)} to {iso(gend)} ({gmins} minutes)')
                candles, source = fetch_ohlcv_multi_exchange(external_ex, blofin_ex, sym, gstart, gend, external_name)
                
                for ts, px in candles:
                    if ts in existing:
                        continue
                    con.execute(
                        'INSERT INTO ticks(ts_ms, ts_iso, symbol, price, source, raw_json) VALUES(?,?,?,?,?,?)',
                        (ts, iso(ts), sym, float(px), source, None),
                    )
                    existing.add(ts)
                    rows_inserted_sym += 1
                
                if candles:
                    print(f'    ✓ Fetched {len(candles)} candles from {source}')

            coverage_pct = round((len(existing) / expected_points) * 100.0, 2) if expected_points > 0 else 0.0
            note = (
                f'tf={TIMEFRAME} window={LOOKBACK_HOURS}h '
                f'points={len(existing)}/{expected_points} ({coverage_pct}%) '
                f'max_gap={MAX_GAP_MINUTES}m'
            )
            con.execute(
                'INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, first_gap_ts_ms, last_gap_ts_ms, note) VALUES(?,?,?,?,?,?,?,?)',
                (now_ms, iso(now_ms), sym, len(filtered), rows_inserted_sym, first_gap, last_gap, note),
            )
            con.commit()

            total_rows += rows_inserted_sym
            total_gaps += len(filtered)
            
            print(f'{sym}: ✓ Inserted {rows_inserted_sym} rows, coverage now {coverage_pct}% ({len(existing)}/{expected_points})\n')
        except Exception as e:
            con.execute(
                'INSERT INTO gap_fill_runs(ts_ms, ts_iso, symbol, gaps_found, rows_inserted, note) VALUES(?,?,?,?,?,?)',
                (now_ms, iso(now_ms), sym, 0, 0, f'error: {type(e).__name__}: {e}'),
            )
            con.commit()
            print(f'{sym}: ✗ Error: {e}\n')
        finally:
            if SYMBOL_SLEEP_MS > 0:
                time.sleep(SYMBOL_SLEEP_MS / 1000.0)

    print(f'\n=== Summary ===')
    print(f'Total gaps found: {total_gaps}')
    print(f'Total rows inserted: {total_rows}')
    return total_gaps, total_rows


def main():
    import ccxt

    con = connect(DB_PATH)
    init_db(con)
    
    print('Initializing exchanges...')
    
    # Try multiple exchanges in order of preference: OKX, Bybit, then fallback to Blofin only
    external_ex = None
    external_name = None
    
    for exchange_name in ['okx', 'bybit']:
        try:
            print(f'Trying {exchange_name.upper()}...')
            if exchange_name == 'okx':
                external_ex = ccxt.okx({'enableRateLimit': True})
            elif exchange_name == 'bybit':
                external_ex = ccxt.bybit({'enableRateLimit': True})
            
            external_ex.load_markets()
            print(f'{exchange_name.upper()}: {len(external_ex.markets)} markets loaded ✓')
            external_name = exchange_name.upper()
            break
        except Exception as e:
            print(f'{exchange_name.upper()} failed: {e}')
            external_ex = None
            continue
    
    if external_ex is None:
        print('\nWARNING: No external exchange available, falling back to Blofin only (limited to ~1-2 hours)')
        external_name = 'BLOFIN'
    
    blofin_ex = ccxt.blofin({'enableRateLimit': True})
    print('Loading Blofin markets...')
    blofin_ex.load_markets()
    print(f'Blofin: {len(blofin_ex.markets)} markets loaded ✓')
    
    # If no external exchange worked, use blofin for both
    if external_ex is None:
        external_ex = blofin_ex

    if LOOP_SECONDS > 0:
        while True:
            run_once(con, external_ex, blofin_ex, external_name)
            time.sleep(max(60, LOOP_SECONDS))
    else:
        run_once(con, external_ex, blofin_ex, external_name)


if __name__ == '__main__':
    main()
