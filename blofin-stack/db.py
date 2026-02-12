#!/usr/bin/env python3
import sqlite3
from pathlib import Path
from typing import Dict, Any, List


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL;')
    con.execute('PRAGMA synchronous=NORMAL;')
    con.execute('PRAGMA temp_store=MEMORY;')
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(
        '''
        CREATE TABLE IF NOT EXISTS ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            source TEXT DEFAULT 'blofin_ws',
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            symbol TEXT NOT NULL,
            signal TEXT NOT NULL,
            strategy TEXT NOT NULL,
            confidence REAL,
            price REAL NOT NULL,
            details_json TEXT
        );

        CREATE TABLE IF NOT EXISTS confirmed_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            symbol TEXT NOT NULL,
            signal TEXT NOT NULL,
            score REAL NOT NULL,
            rationale TEXT,
            UNIQUE(signal_id)
        );

        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            confirmed_signal_id INTEGER NOT NULL,
            opened_ts_ms INTEGER NOT NULL,
            opened_ts_iso TEXT NOT NULL,
            closed_ts_ms INTEGER,
            closed_ts_iso TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            qty REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            pnl_pct REAL,
            reason TEXT,
            UNIQUE(confirmed_signal_id)
        );

        CREATE TABLE IF NOT EXISTS service_heartbeats (
            service TEXT PRIMARY KEY,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            details_json TEXT
        );

        CREATE TABLE IF NOT EXISTS gap_fill_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            symbol TEXT NOT NULL,
            gaps_found INTEGER NOT NULL,
            rows_inserted INTEGER NOT NULL,
            first_gap_ts_ms INTEGER,
            last_gap_ts_ms INTEGER,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS dashboard_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            ok INTEGER NOT NULL,
            status_code INTEGER,
            latency_ms INTEGER,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts ON ticks(symbol, ts_ms);
        CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts_ms);
        CREATE INDEX IF NOT EXISTS idx_signals_signal_ts ON signals(signal, ts_ms);
        CREATE INDEX IF NOT EXISTS idx_confirmed_symbol_ts ON confirmed_signals(symbol, ts_ms);
        CREATE INDEX IF NOT EXISTS idx_paper_symbol_status ON paper_trades(symbol, status);
        '''
    )
    con.commit()


def insert_tick(con: sqlite3.Connection, row: Dict[str, Any]) -> None:
    con.execute(
        'INSERT INTO ticks (ts_ms, ts_iso, symbol, price, source, raw_json) VALUES (?, ?, ?, ?, ?, ?)',
        (row['ts_ms'], row['ts_iso'], row['symbol'], row['price'], row.get('source', 'blofin_ws'), row.get('raw_json')),
    )


def insert_signal(con: sqlite3.Connection, row: Dict[str, Any]) -> None:
    con.execute(
        'INSERT INTO signals (ts_ms, ts_iso, symbol, signal, strategy, confidence, price, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (row['ts_ms'], row['ts_iso'], row['symbol'], row['signal'], row['strategy'], row.get('confidence'), row['price'], row.get('details_json')),
    )


def upsert_heartbeat(con: sqlite3.Connection, service: str, ts_ms: int, ts_iso: str, details_json: str = '{}') -> None:
    con.execute(
        '''
        INSERT INTO service_heartbeats (service, ts_ms, ts_iso, details_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(service) DO UPDATE SET
            ts_ms=excluded.ts_ms,
            ts_iso=excluded.ts_iso,
            details_json=excluded.details_json
        ''',
        (service, ts_ms, ts_iso, details_json),
    )


def latest_ticks(con: sqlite3.Connection, limit: int = 100) -> List[Dict[str, Any]]:
    cur = con.execute('SELECT ts_iso, symbol, price, source FROM ticks ORDER BY ts_ms DESC LIMIT ?', (limit,))
    return [dict(r) for r in cur.fetchall()]


def latest_signals(con: sqlite3.Connection, limit: int = 100) -> List[Dict[str, Any]]:
    cur = con.execute('SELECT ts_iso, symbol, signal, strategy, confidence, price, details_json FROM signals ORDER BY ts_ms DESC LIMIT ?', (limit,))
    return [dict(r) for r in cur.fetchall()]
