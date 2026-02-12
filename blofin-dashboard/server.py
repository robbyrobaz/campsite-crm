#!/usr/bin/env python3
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from collections import Counter

DATA_DIR = Path('/home/rob/.openclaw/workspace/blofin-research/data')
HOST = '127.0.0.1'
PORT = 8766


def latest_file(prefix: str):
    files = sorted(DATA_DIR.glob(f"{prefix}_*.jsonl"))
    return files[-1] if files else None


def read_tail(path: Path, n=200):
    if not path or not path.exists():
        return []
    lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def metrics():
    events = read_tail(latest_file('events'), 2000)
    c = Counter(e.get('type', 'unknown') for e in events)
    by_sym = Counter(e.get('symbol', 'unknown') for e in events)
    return {
        'events_total': len(events),
        'event_types': c,
        'symbols': by_sym,
        'latest_events': events[-25:],
    }


class H(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status=200, ctype='text/html; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/healthz':
            self._send(b'ok', ctype='text/plain')
            return
        if self.path == '/api/metrics':
            body = json.dumps(metrics(), default=str).encode()
            self._send(body, ctype='application/json')
            return

        m = metrics()
        html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Blofin Dashboard</title>
<style>body{{font-family:Arial;padding:20px}}pre{{background:#111;color:#0f0;padding:12px;overflow:auto}}.kpi{{display:inline-block;margin-right:20px;padding:8px 12px;background:#f2f2f2;border-radius:8px}}</style>
</head><body>
<h1>Blofin Research Dashboard</h1>
<div class='kpi'>Events: <b>{m['events_total']}</b></div>
<div class='kpi'>Types: <b>{dict(m['event_types'])}</b></div>
<div class='kpi'>Symbols: <b>{dict(m['symbols'])}</b></div>
<p><a href='/api/metrics'>/api/metrics</a> · <a href='/healthz'>/healthz</a></p>
<h2>Latest events</h2>
<pre>{json.dumps(m['latest_events'], indent=2, default=str)}</pre>
</body></html>"""
        self._send(html.encode())


if __name__ == '__main__':
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HTTPServer((HOST, PORT), H).serve_forever()
