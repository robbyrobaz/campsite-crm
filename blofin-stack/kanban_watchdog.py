#!/usr/bin/env python3
import json, os, time
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from db import connect, init_db, update_kanban_task_status, upsert_heartbeat

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
DB_PATH = os.getenv('BLOFIN_DB_PATH', str(ROOT / 'data' / 'blofin_monitor.db'))
WORKER_NAME = os.getenv('KANBAN_WORKER_NAME', 'kanban_worker')


def now_pair():
    ts_ms = int(time.time() * 1000)
    ts_iso = datetime.now(timezone.utc).isoformat()
    return ts_ms, ts_iso


def main():
    con = connect(DB_PATH)
    init_db(con)

    inprog = con.execute("SELECT id FROM kanban_tasks WHERE status='in_progress' ORDER BY priority DESC, created_ts_ms ASC, id ASC").fetchall()
    inbox = con.execute("SELECT id FROM kanban_tasks WHERE status='inbox' ORDER BY priority DESC, created_ts_ms ASC, id ASC").fetchall()

    fixed = False
    action = 'ok'

    if len(inprog) == 0 and len(inbox) > 0:
        task_id = int(inbox[0]['id'])
        ts_ms, ts_iso = now_pair()
        ok = update_kanban_task_status(
            con,
            task_id=task_id,
            from_status='inbox',
            to_status='in_progress',
            ts_ms=ts_ms,
            ts_iso=ts_iso,
            actor='kanban_watchdog',
            note='watchdog auto-started coding task',
            assigned_worker=WORKER_NAME,
        )
        fixed = bool(ok)
        action = 'picked_next' if ok else 'pick_failed'
    elif len(inprog) > 1:
        action = 'multiple_in_progress_detected'
    else:
        action = 'healthy'

    ts_ms, ts_iso = now_pair()
    upsert_heartbeat(con, 'kanban_watchdog', ts_ms, ts_iso, json.dumps({'action': action, 'fixed': fixed, 'in_progress': len(inprog), 'inbox': len(inbox)}))
    con.commit()


if __name__ == '__main__':
    main()
