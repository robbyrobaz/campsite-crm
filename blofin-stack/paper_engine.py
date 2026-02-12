#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from db import connect, init_db, upsert_heartbeat

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

DB_PATH = os.getenv('BLOFIN_DB_PATH', str(ROOT / 'data' / 'blofin_monitor.db'))
CONFIRM_WINDOW_MIN = int(os.getenv('CONFIRM_WINDOW_MINUTES', '30'))
CONFIRM_MIN_STRATEGIES = int(os.getenv('CONFIRM_MIN_STRATEGIES', '2'))
PAPER_TP_PCT = float(os.getenv('PAPER_TP_PCT', '1.5'))
PAPER_SL_PCT = float(os.getenv('PAPER_SL_PCT', '1.0'))
PAPER_MAX_HOLD_MIN = int(os.getenv('PAPER_MAX_HOLD_MINUTES', '180'))
LOOP_SECONDS = int(os.getenv('PAPER_LOOP_SECONDS', '15'))


def now_ms():
    return int(time.time() * 1000)


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def maybe_confirm_signals(con):
    t = now_ms()
    cutoff = t - CONFIRM_WINDOW_MIN * 60_000
    rows = con.execute(
        'SELECT id,ts_ms,ts_iso,symbol,signal,strategy,confidence,price FROM signals WHERE ts_ms >= ? ORDER BY ts_ms DESC',
        (cutoff,),
    ).fetchall()

    grouped = {}
    for r in rows:
        key = (r['symbol'], r['signal'])
        grouped.setdefault(key, []).append(r)

    inserted = 0
    for (symbol, side), arr in grouped.items():
        strategies = {a['strategy'] for a in arr}
        if len(strategies) < CONFIRM_MIN_STRATEGIES:
            continue
        top = arr[0]
        exists = con.execute('SELECT 1 FROM confirmed_signals WHERE signal_id=?', (top['id'],)).fetchone()
        if exists:
            continue
        score = min(0.99, 0.5 + (len(strategies) * 0.15))
        con.execute(
            'INSERT INTO confirmed_signals(signal_id,ts_ms,ts_iso,symbol,signal,score,rationale) VALUES(?,?,?,?,?,?,?)',
            (top['id'], top['ts_ms'], top['ts_iso'], symbol, side, score, f'{len(strategies)} strategies agreed in {CONFIRM_WINDOW_MIN}m'),
        )
        inserted += 1
    return inserted


def latest_price(con, symbol):
    r = con.execute('SELECT price FROM ticks WHERE symbol=? ORDER BY ts_ms DESC LIMIT 1', (symbol,)).fetchone()
    return float(r['price']) if r else None


def open_paper_trades(con):
    c = con.execute(
        "SELECT id,ts_ms,ts_iso,symbol,signal,score FROM confirmed_signals WHERE id NOT IN (SELECT confirmed_signal_id FROM paper_trades)")
    rows = c.fetchall()
    opened = 0
    for r in rows:
        px = latest_price(con, r['symbol'])
        if px is None:
            continue
        con.execute(
            'INSERT INTO paper_trades(confirmed_signal_id,opened_ts_ms,opened_ts_iso,symbol,side,entry_price,qty,status) VALUES(?,?,?,?,?,?,?,?)',
            (r['id'], now_ms(), iso(now_ms()), r['symbol'], r['signal'], px, 1.0, 'OPEN'),
        )
        opened += 1
    return opened


def close_paper_trades(con):
    rows = con.execute('SELECT * FROM paper_trades WHERE status="OPEN"').fetchall()
    closed = 0
    t = now_ms()
    for r in rows:
        px = latest_price(con, r['symbol'])
        if px is None:
            continue
        entry = float(r['entry_price'])
        side = r['side']
        pnl_pct = ((px - entry) / entry) * 100.0
        if side == 'SELL':
            pnl_pct = -pnl_pct

        age_min = (t - int(r['opened_ts_ms'])) / 60000.0
        reason = None
        if pnl_pct >= PAPER_TP_PCT:
            reason = 'TP'
        elif pnl_pct <= -PAPER_SL_PCT:
            reason = 'SL'
        elif age_min >= PAPER_MAX_HOLD_MIN:
            reason = 'TIME'

        if reason:
            con.execute(
                'UPDATE paper_trades SET status="CLOSED",closed_ts_ms=?,closed_ts_iso=?,exit_price=?,pnl_pct=?,reason=? WHERE id=?',
                (t, iso(t), px, pnl_pct, reason, r['id']),
            )
            closed += 1
    return closed


def main():
    con = connect(DB_PATH)
    init_db(con)
    while True:
        confirmed = maybe_confirm_signals(con)
        opened = open_paper_trades(con)
        closed = close_paper_trades(con)
        t = now_ms()
        upsert_heartbeat(con, 'blofin-paper-engine', t, iso(t), json.dumps({'confirmed': confirmed, 'opened': opened, 'closed': closed}))
        con.commit()
        time.sleep(LOOP_SECONDS)


if __name__ == '__main__':
    main()
