#!/usr/bin/env python3
import json, os, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from dotenv import load_dotenv
from db import connect, init_db, create_kanban_task, list_kanban_tasks, update_kanban_task_status

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
DB_PATH = os.getenv('BLOFIN_DB_PATH', str(ROOT / 'data' / 'blofin_monitor.db'))
HOST = '127.0.0.1'
PORT = int(os.getenv('KANBAN_PORT', '8781'))

con = connect(DB_PATH)
init_db(con)


def now_pair():
    ts_ms = int(time.time() * 1000)
    ts_iso = datetime.now(timezone.utc).isoformat()
    return ts_ms, ts_iso


def board_data():
    tasks = list_kanban_tasks(con)
    cols = {'inbox': [], 'in_progress': [], 'needs_approval': [], 'done': []}
    for t in tasks:
        cols.setdefault(t['status'], []).append(t)
    return {'tasks': tasks, 'columns': cols}

class H(BaseHTTPRequestHandler):
    def sendj(self, obj, code=200):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def sendh(self, html, code=200):
        b = html.encode(); self.send_response(code); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def _json(self):
        n=int(self.headers.get('Content-Length','0')); raw=self.rfile.read(n) if n>0 else b'{}'; return json.loads(raw.decode())

    def do_GET(self):
        if self.path == '/healthz': return self.sendj({'ok': True})
        if self.path == '/api/kanban/tasks': return self.sendj(board_data())
        if self.path == '/':
            html="""<!doctype html><html><head><meta charset='utf-8'><title>Kanban Dashboard</title>
<style>body{font-family:Arial;background:#0b1020;color:#e7ecff;margin:0}.wrap{max-width:1200px;margin:0 auto;padding:20px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.col{background:#121a31;border:1px solid #23325f;border-radius:10px;padding:10px;min-height:220px}.task{background:#0f1730;border:1px solid #2b427a;border-radius:8px;padding:8px;margin-bottom:8px}.small{font-size:12px;color:#9fb0e6}input,textarea,select,button{background:#0e1730;color:#e7ecff;border:1px solid #2b427a;border-radius:8px;padding:6px}button{cursor:pointer}</style>
</head><body><div class='wrap'><h1>Kanban Dashboard</h1><p class='small'>Dedicated task board</p>
<div><input id='t' placeholder='task title' style='width:30%'> <select id='p'><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select><br><textarea id='d' style='width:100%;height:60px;margin-top:6px' placeholder='details'></textarea><br><button onclick='createTask()'>Add Task</button></div>
<div id='board' class='grid' style='margin-top:12px'></div></div>
<script>
const COLS=['inbox','in_progress','needs_approval','done']; const LABEL={inbox:'Inbox',in_progress:'In Progress',needs_approval:'Needs Approval',done:'Done'};
async function post(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}); return r.json();}
function tHtml(t){let c=''; if(t.status==='needs_approval') c+=`<button onclick="approve(${t.id})">Approve</button> <button onclick="reject(${t.id})">Reject</button>`; if(t.status==='inbox') c+=`<button onclick="move(${t.id},'inbox','in_progress')">Start</button>`; c+=` <button onclick="editTask(${t.id},${JSON.stringify(t.title)},${JSON.stringify(t.description||'')},${t.priority})">Edit</button> <button onclick="setSummary(${t.id})">Set summary</button> <button onclick="delTask(${t.id})">Delete</button>`; return `<div class='task'><b>#${t.id} ${t.title}</b><div class='small'>P${t.priority} · ${t.created_by||''}</div><div class='small'>${t.description||''}</div><div class='small'>Summary: ${t.completion_summary||'-'}</div><div class='small'>${t.notes||''}</div>${c}</div>`;}
async function refresh(){const d=await (await fetch('/api/kanban/tasks')).json(); document.getElementById('board').innerHTML=COLS.map(c=>`<div class='col'><h3>${LABEL[c]}</h3>${(d.columns[c]||[]).map(tHtml).join('')||'<div class="small">empty</div>'}</div>`).join('');}
async function createTask(){await post('/api/kanban/tasks',{title:document.getElementById('t').value,description:document.getElementById('d').value,priority:parseInt(document.getElementById('p').value)});document.getElementById('t').value='';document.getElementById('d').value='';refresh();}
async function move(id,from_status,to_status){await post('/api/kanban/move',{task_id:id,from_status,to_status,actor:'dashboard_user'});refresh();}
async function approve(id){const note=prompt('Approval note','approved')||'approved'; await post('/api/kanban/approve',{task_id:id,note,actor:'dashboard_approver'}); refresh();}
async function reject(id){const note=prompt('Rework note','please rework')||'please rework'; await post('/api/kanban/reject',{task_id:id,note,actor:'dashboard_approver'}); refresh();}
async function delTask(id){if(!confirm('Delete this task?')) return; await post('/api/kanban/delete',{task_id:id,actor:'dashboard_user'}); refresh();}
async function setSummary(id){const s=prompt('10 words max: what was done?','')||''; await post('/api/kanban/set-summary',{task_id:id,summary:s,actor:'assistant'}); refresh();}
async function editTask(id,title,description,priority){
  const nt=prompt('Edit title', title)||title;
  const nd=prompt('Edit description', description)||description;
  const np=parseInt(prompt('Edit priority (1-5)', String(priority))||String(priority),10);
  await post('/api/kanban/edit',{task_id:id,title:nt,description:nd,priority:Math.max(1,Math.min(np||3,5)),actor:'dashboard_user'});
  refresh();
}
refresh(); setInterval(refresh,10000);
</script></body></html>"""
            return self.sendh(html)
        return self.sendj({'error':'not found'},404)

    def do_POST(self):
        p = self.path
        d = self._json(); ts_ms, ts_iso = now_pair()
        if p == '/api/kanban/tasks':
            title=(d.get('title') or '').strip(); desc=(d.get('description') or '').strip(); pri=max(1,min(int(d.get('priority',3)),5))
            if not title: return self.sendj({'error':'title required'},400)
            task_id=create_kanban_task(con, ts_ms=ts_ms, ts_iso=ts_iso, title=title, description=desc, priority=pri)
            return self.sendj({'ok':True,'task_id':task_id},201)
        if p == '/api/kanban/move':
            ok=update_kanban_task_status(con, task_id=int(d.get('task_id',0)), from_status=d.get('from_status',''), to_status=d.get('to_status',''), ts_ms=ts_ms, ts_iso=ts_iso, actor=d.get('actor','dashboard_user'), note=d.get('note',''))
            return self.sendj({'ok':ok}, 200 if ok else 409)
        if p == '/api/kanban/approve':
            note=d.get('note','approved')
            ok=update_kanban_task_status(con, task_id=int(d.get('task_id',0)), from_status='needs_approval', to_status='done', ts_ms=ts_ms, ts_iso=ts_iso, actor=d.get('actor','dashboard_approver'), note=note, approval_note=note)
            return self.sendj({'ok':ok}, 200 if ok else 409)
        if p == '/api/kanban/reject':
            note=d.get('note','please rework')
            ok=update_kanban_task_status(con, task_id=int(d.get('task_id',0)), from_status='needs_approval', to_status='in_progress', ts_ms=ts_ms, ts_iso=ts_iso, actor=d.get('actor','dashboard_approver'), note=note, rejection_note=note)
            return self.sendj({'ok':ok}, 200 if ok else 409)
        if p == '/api/kanban/delete':
            task_id = int(d.get('task_id',0))
            actor = d.get('actor','dashboard_user')
            cur = con.execute('DELETE FROM kanban_tasks WHERE id=?', (task_id,))
            con.execute('INSERT INTO kanban_task_events(task_id,ts_ms,ts_iso,action,from_status,to_status,note,actor) VALUES(?,?,?,?,?,?,?,?)',
                        (task_id, ts_ms, ts_iso, 'delete', None, None, 'task deleted', actor))
            con.commit()
            return self.sendj({'ok': cur.rowcount > 0})
        if p == '/api/kanban/edit':
            task_id = int(d.get('task_id',0))
            actor = d.get('actor','dashboard_user')
            title = (d.get('title','') or '').strip()
            desc = (d.get('description','') or '').strip()
            prio = max(1,min(int(d.get('priority',3)),5))
            if not title:
                return self.sendj({'error':'title required'},400)
            cur = con.execute('UPDATE kanban_tasks SET title=?, description=?, priority=?, updated_ts_ms=?, updated_ts_iso=? WHERE id=?',
                              (title, desc, prio, ts_ms, ts_iso, task_id))
            con.execute('INSERT INTO kanban_task_events(task_id,ts_ms,ts_iso,action,from_status,to_status,note,actor) VALUES(?,?,?,?,?,?,?,?)',
                        (task_id, ts_ms, ts_iso, 'edit', None, None, f'edited task fields; priority={prio}', actor))
            con.commit()
            return self.sendj({'ok': cur.rowcount > 0})
        if p == '/api/kanban/set-summary':
            task_id = int(d.get('task_id',0))
            actor = d.get('actor','assistant')
            summary = (d.get('summary','') or '').strip()
            words = [w for w in summary.split() if w]
            if len(words) > 10:
                return self.sendj({'error':'summary must be 10 words or less'},400)
            cur = con.execute('UPDATE kanban_tasks SET completion_summary=?, updated_ts_ms=?, updated_ts_iso=? WHERE id=?', (summary, ts_ms, ts_iso, task_id))
            con.execute('INSERT INTO kanban_task_events(task_id,ts_ms,ts_iso,action,from_status,to_status,note,actor) VALUES(?,?,?,?,?,?,?,?)',
                        (task_id, ts_ms, ts_iso, 'set_summary', None, None, summary, actor))
            con.commit()
            return self.sendj({'ok': cur.rowcount > 0})
        return self.sendj({'error':'not found'},404)

if __name__=='__main__':
    HTTPServer((HOST, PORT), H).serve_forever()
