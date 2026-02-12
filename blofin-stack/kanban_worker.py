#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from db import connect, init_db, update_kanban_task_status, upsert_heartbeat

ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, '.env'))

DB_PATH = os.getenv('BLOFIN_DB_PATH', os.path.join(ROOT, 'data', 'blofin_monitor.db'))
LOOP_SECONDS = max(3, int(os.getenv('KANBAN_WORKER_LOOP_SECONDS', '10')))
MAX_IN_PROGRESS = max(1, int(os.getenv('KANBAN_MAX_IN_PROGRESS', '3')))
WORKER_NAME = os.getenv('KANBAN_WORKER_NAME', 'kanban_worker')


def now_pair():
    ts_ms = int(time.time() * 1000)
    ts_iso = datetime.now(timezone.utc).isoformat()
    return ts_ms, ts_iso


def current_in_progress_count(con):
    row = con.execute("SELECT COUNT(*) AS c FROM kanban_tasks WHERE status='in_progress'").fetchone()
    return int(row['c'])


def pick_next_inbox_task(con):
    row = con.execute(
        """
        SELECT id
        FROM kanban_tasks
        WHERE status='inbox'
        ORDER BY priority DESC, created_ts_ms ASC, id ASC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    return int(row['id'])


def loop_once(con):
    picked = []
    cap = MAX_IN_PROGRESS - current_in_progress_count(con)
    for _ in range(max(0, cap)):
        task_id = pick_next_inbox_task(con)
        if task_id is None:
            break
        ts_ms, ts_iso = now_pair()
        ok = update_kanban_task_status(
            con,
            task_id=task_id,
            from_status='inbox',
            to_status='in_progress',
            ts_ms=ts_ms,
            ts_iso=ts_iso,
            actor=WORKER_NAME,
            note='auto-picked by worker',
            assigned_worker=WORKER_NAME,
        )
        if not ok:
            break
        picked.append(task_id)

    ts_ms, ts_iso = now_pair()
    upsert_heartbeat(
        con,
        service='kanban_worker',
        ts_ms=ts_ms,
        ts_iso=ts_iso,
        details_json=json.dumps({'picked': picked, 'loop_seconds': LOOP_SECONDS, 'max_in_progress': MAX_IN_PROGRESS}),
    )
    con.commit()


def main():
    con = connect(DB_PATH)
    init_db(con)
    while True:
        try:
            loop_once(con)
        except Exception as e:
            ts_ms, ts_iso = now_pair()
            upsert_heartbeat(
                con,
                service='kanban_worker',
                ts_ms=ts_ms,
                ts_iso=ts_iso,
                details_json=json.dumps({'error': str(e)}),
            )
            con.commit()
        time.sleep(LOOP_SECONDS)


if __name__ == '__main__':
    main()
