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
MAX_IN_PROGRESS = max(1, int(os.getenv('KANBAN_MAX_IN_PROGRESS', '1')))
WORKER_NAME = os.getenv('KANBAN_WORKER_NAME', 'kanban_worker')


def now_pair():
    ts_ms = int(time.time() * 1000)
    ts_iso = datetime.now(timezone.utc).isoformat()
    return ts_ms, ts_iso


def current_in_progress(con):
    return con.execute(
        "SELECT id, priority, created_ts_ms FROM kanban_tasks WHERE status='in_progress' ORDER BY priority DESC, created_ts_ms ASC, id ASC"
    ).fetchall()


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
    return int(row['id']) if row else None


def enforce_single_active(con):
    demoted = []
    inprog = current_in_progress(con)
    if len(inprog) <= MAX_IN_PROGRESS:
        return demoted
    keep = {int(r['id']) for r in inprog[:MAX_IN_PROGRESS]}
    ts_ms, ts_iso = now_pair()
    for r in inprog[MAX_IN_PROGRESS:]:
        tid = int(r['id'])
        if tid in keep:
            continue
        ok = update_kanban_task_status(
            con,
            task_id=tid,
            from_status='in_progress',
            to_status='inbox',
            ts_ms=ts_ms,
            ts_iso=ts_iso,
            actor=WORKER_NAME,
            note='queued: only one active coding task at a time',
            assigned_worker=WORKER_NAME,
        )
        if ok:
            demoted.append(tid)
    return demoted


def loop_once(con):
    picked = []
    demoted = enforce_single_active(con)

    inprog = current_in_progress(con)
    if len(inprog) < MAX_IN_PROGRESS:
        task_id = pick_next_inbox_task(con)
        if task_id is not None:
            ts_ms, ts_iso = now_pair()
            ok = update_kanban_task_status(
                con,
                task_id=task_id,
                from_status='inbox',
                to_status='in_progress',
                ts_ms=ts_ms,
                ts_iso=ts_iso,
                actor=WORKER_NAME,
                note='auto-picked: actively coding now (priority queue, single active slot)',
                assigned_worker=WORKER_NAME,
            )
            if ok:
                picked.append(task_id)

    ts_ms, ts_iso = now_pair()
    upsert_heartbeat(
        con,
        service='kanban_worker',
        ts_ms=ts_ms,
        ts_iso=ts_iso,
        details_json=json.dumps({
            'picked': picked,
            'demoted_to_inbox': demoted,
            'loop_seconds': LOOP_SECONDS,
            'max_in_progress': MAX_IN_PROGRESS,
            'mode': 'single-active-coding'
        }),
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
