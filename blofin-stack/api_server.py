#!/usr/bin/env python3
import json
import os
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from db import connect, init_db, latest_signals, latest_ticks

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DB_PATH = os.getenv("BLOFIN_DB_PATH", str(ROOT / "data" / "blofin_monitor.db"))
HOST = os.getenv("API_HOST", "127.0.0.1")
PORT = int(os.getenv("API_PORT", "8780"))

con = connect(DB_PATH)
init_db(con)


def summary() -> dict:
    sigs = latest_signals(con, 5000)
    ticks = latest_ticks(con, 200)
    by_signal = Counter(s.get("signal", "UNKNOWN") for s in sigs)
    by_strategy = Counter(s.get("strategy", "UNKNOWN") for s in sigs)
    by_symbol = Counter(s.get("symbol", "UNKNOWN") for s in sigs)
    hb = con.execute("SELECT service, ts_iso, details_json FROM service_heartbeats ORDER BY ts_ms DESC").fetchall()
    heartbeats = [dict(r) for r in hb]
    return {
        "signals_total_window": len(sigs),
        "signals_by_type": dict(by_signal),
        "signals_by_strategy": dict(by_strategy),
        "signals_by_symbol": dict(by_symbol.most_common(25)),
        "recent_signals": sigs[:50],
        "recent_ticks": ticks[:50],
        "heartbeats": heartbeats,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status: int = 200, ctype: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        q = parse_qs(parsed.query)

        if path == "/healthz":
            self._send(b"ok", ctype="text/plain")
            return

        if path == "/api/summary":
            self._send(json.dumps(summary(), default=str).encode())
            return

        if path == "/api/signals":
            limit = int(q.get("limit", ["100"])[0])
            self._send(json.dumps(latest_signals(con, max(1, min(limit, 5000))), default=str).encode())
            return

        if path == "/api/ticks/latest":
            limit = int(q.get("limit", ["100"])[0])
            self._send(json.dumps(latest_ticks(con, max(1, min(limit, 5000))), default=str).encode())
            return

        if path == "/":
            s = summary()
            html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Blofin Monitor</title>
<style>
body{{font-family:Arial;padding:18px;background:#111;color:#ddd}}
.card{{display:inline-block;background:#1d1d1d;padding:10px 12px;margin:6px;border-radius:8px}}
a{{color:#9cf}}
pre{{background:#000;padding:12px;overflow:auto;max-height:420px}}
</style></head><body>
<h1>Blofin Monitoring Stack</h1>
<div class='card'>Signals(5k window): <b>{s['signals_total_window']}</b></div>
<div class='card'>By Type: <b>{s['signals_by_type']}</b></div>
<div class='card'>By Strategy: <b>{s['signals_by_strategy']}</b></div>
<p><a href='/healthz'>/healthz</a> · <a href='/api/summary'>/api/summary</a> · <a href='/api/signals?limit=100'>/api/signals</a> · <a href='/api/ticks/latest?limit=100'>/api/ticks/latest</a></p>
<h2>Recent signals</h2>
<pre>{json.dumps(s['recent_signals'], indent=2, default=str)}</pre>
<h2>Heartbeats</h2>
<pre>{json.dumps(s['heartbeats'], indent=2, default=str)}</pre>
</body></html>"""
            self._send(html.encode(), ctype="text/html; charset=utf-8")
            return

        self._send(json.dumps({"error": "not found"}).encode(), status=404)


if __name__ == "__main__":
    HTTPServer((HOST, PORT), Handler).serve_forever()
