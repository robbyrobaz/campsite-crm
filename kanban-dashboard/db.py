#!/usr/bin/env python3
import sqlite3
from pathlib import Path
from typing import Dict, Any, List


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.Connection(db_path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL;')
    con.execute('PRAGMA synchronous=NORMAL;')
    con.execute('PRAGMA temp_store=MEMORY;')
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(
        '''
        CREATE TABLE IF NOT EXISTS service_heartbeats (
            service TEXT PRIMARY KEY,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            details_json TEXT
        );

        CREATE TABLE IF NOT EXISTS kanban_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts_ms INTEGER NOT NULL,
            created_ts_iso TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inbox',
            priority INTEGER DEFAULT 0,
            title TEXT NOT NULL,
            description TEXT,
            assignee TEXT,
            tags TEXT,
            coding_started_ts_ms INTEGER,
            coding_done_ts_ms INTEGER,
            approved_ts_ms INTEGER,
            result_summary TEXT
        );

        CREATE TABLE IF NOT EXISTS kanban_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            event_type TEXT NOT NULL,
            note TEXT,
            actor TEXT
        );

        CREATE TABLE IF NOT EXISTS kanban_task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            ts_ms INTEGER NOT NULL,
            ts_iso TEXT NOT NULL,
            action TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            note TEXT,
            actor TEXT,
            FOREIGN KEY(task_id) REFERENCES kanban_tasks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_kanban_status_priority ON kanban_tasks(status, priority DESC, created_ts_ms ASC);
        '''
    )
    con.commit()

    # optional schema evolution
    cols = {r['name'] for r in con.execute("PRAGMA table_info(kanban_tasks)").fetchall()}
    missing = {
        'coding_worker': 'TEXT',
        'coding_session_id': 'TEXT',
        'approval_reviewer': 'TEXT',
        'approval_note': 'TEXT',
        'rejected_note': 'TEXT',
        'rejected_ts_ms': 'INTEGER',
    }
    for name, typ in missing.items():
        if name not in cols:
            con.execute(f'ALTER TABLE kanban_tasks ADD COLUMN {name} {typ}')
    con.commit()


def create_kanban_task(
    con: sqlite3.Connection,
    ts_ms: int,
    ts_iso: str,
    title: str,
    description: str = '',
    priority: int = 0,
    tags: str = '',
    actor: str = 'system',
) -> int:
    cur = con.execute(
        '''
        INSERT INTO kanban_tasks
        (created_ts_ms, created_ts_iso, status, priority, title, description, tags)
        VALUES (?, ?, 'inbox', ?, ?, ?, ?)
        ''',
        (ts_ms, ts_iso, priority, title, description, tags),
    )
    task_id = cur.lastrowid
    con.execute(
        'INSERT INTO kanban_task_events (task_id, ts_ms, ts_iso, action, from_status, to_status, note, actor) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (task_id, ts_ms, ts_iso, 'created', None, 'inbox', title, actor),
    )
    con.commit()
    return task_id


def update_kanban_task_status(
    con: sqlite3.Connection,
    task_id: int,
    from_status: str,
    to_status: str,
    ts_ms: int,
    ts_iso: str,
    note: str = '',
    actor: str = 'system',
    **kwargs,
) -> bool:
    row = con.execute('SELECT id FROM kanban_tasks WHERE id=? AND status=?', (task_id, from_status)).fetchone()
    if not row:
        return False

    set_fields = ['status = ?']
    set_args = [to_status]
    for k, v in kwargs.items():
        set_fields.append(f'{k} = ?')
        set_args.append(v)
    set_args.append(task_id)

    con.execute(
        f'UPDATE kanban_tasks SET {", ".join(set_fields)} WHERE id = ?',
        set_args,
    )
    con.execute(
        'INSERT INTO kanban_task_events (task_id, ts_ms, ts_iso, action, from_status, to_status, note, actor) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (task_id, ts_ms, ts_iso, 'status_change', from_status, to_status, note, actor),
    )
    con.commit()
    return True


def list_kanban_tasks(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = con.execute(
        '''
        SELECT id, created_ts_ms, created_ts_iso, status, priority, title, description, assignee, tags,
               coding_started_ts_ms, coding_done_ts_ms, approved_ts_ms, coding_worker, coding_session_id,
               approval_reviewer, approval_note, rejected_note, rejected_ts_ms, result_summary
        FROM kanban_tasks
        ORDER BY CASE status
                   WHEN 'in_progress' THEN 1
                   WHEN 'inbox' THEN 2
                   WHEN 'needs_approval' THEN 3
                   WHEN 'done' THEN 4
                   WHEN 'rejected' THEN 5
                   ELSE 6
                 END,
                 priority DESC,
                 created_ts_ms ASC
        '''
    ).fetchall()
    return [dict(r) for r in rows]


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
    con.commit()


def upsert_heartbeat(con: sqlite3.Connection, service: str, ts_ms: int, ts_iso: str, details_json: str = '{}') -> None:
    """Store a service heartbeat timestamp."""
    # Since we don't have a service_heartbeats table in kanban DB, we can create a simple events table
    con.execute(
        '''
        INSERT INTO kanban_events (ts_ms, ts_iso, event_type, note, actor)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (ts_ms, ts_iso, 'heartbeat', details_json, service),
    )
    con.commit()
