#!/usr/bin/env python3
import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DB_PATH = Path('/home/rob/.openclaw/workspace/blofin-research/data/blofin.db')
HOST = '127.0.0.1'
PORT = 8766


def q(sql, args=()):
    if not DB_PATH.exists():
        return []
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(sql, args).fetchall()
    con.close()
    return [dict(r) for r in rows]


def metrics():
    one_hour = int(datetime.now(timezone.utc).timestamp() * 1000) - 3600_000
    total_ticks = q('SELECT COUNT(*) c FROM ticks')
    total_signals = q('SELECT COUNT(*) c FROM signals')
    ticks_1h = q('SELECT COUNT(*) c FROM ticks WHERE ts_ms >= ?', (one_hour,))
    signals_1h = q('SELECT COUNT(*) c FROM signals WHERE ts_ms >= ?', (one_hour,))
    top_symbols = q('SELECT symbol, COUNT(*) c FROM ticks GROUP BY symbol ORDER BY c DESC LIMIT 25')
    top_patterns = q('SELECT pattern, COUNT(*) c FROM signals GROUP BY pattern ORDER BY c DESC LIMIT 20')
    latest_signals = q('SELECT ts_ms,symbol,signal,pattern,score,price FROM signals ORDER BY id DESC LIMIT 50')
    latest_ticks = q('SELECT ts_ms,symbol,price FROM ticks ORDER BY id DESC LIMIT 50')
    return {
        'db_path': str(DB_PATH),
        'total_ticks': (total_ticks[0]['c'] if total_ticks else 0),
        'total_signals': (total_signals[0]['c'] if total_signals else 0),
        'ticks_last_hour': (ticks_1h[0]['c'] if ticks_1h else 0),
        'signals_last_hour': (signals_1h[0]['c'] if signals_1h else 0),
        'top_symbols': top_symbols,
        'top_patterns': top_patterns,
        'latest_signals': latest_signals,
        'latest_ticks': latest_ticks,
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
            return self._send(b'ok', ctype='text/plain')
        m = metrics()
        if self.path == '/api/metrics':
            return self._send(json.dumps(m, default=str).encode(), ctype='application/json')

        html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Blofin Dashboard</title>
<style>body{{font-family:Arial;padding:20px}}pre{{background:#111;color:#0f0;padding:12px;overflow:auto}}.k{{display:inline-block;margin-right:14px;padding:8px 10px;background:#f1f1f1;border-radius:8px}}</style>
</head><body>
<h1>Blofin Pattern Monitor</h1>
<div class='k'>Total ticks: <b>{m['total_ticks']}</b></div>
<div class='k'>Total signals: <b>{m['total_signals']}</b></div>
<div class='k'>Ticks 1h: <b>{m['ticks_last_hour']}</b></div>
<div class='k'>Signals 1h: <b>{m['signals_last_hour']}</b></div>
<p><a href='/api/metrics'>/api/metrics</a> · <a href='/healthz'>/healthz</a></p>
<h2>Top Symbols</h2><pre>{json.dumps(m['top_symbols'], indent=2)}</pre>
<h2>Top Patterns</h2><pre>{json.dumps(m['top_patterns'], indent=2)}</pre>
<h2>Latest Signals</h2><pre>{json.dumps(m['latest_signals'], indent=2)}</pre>
</body></html>"""
        self._send(html.encode())


if __name__ == '__main__':
    HTTPServer((HOST, PORT), H).serve_forever()
