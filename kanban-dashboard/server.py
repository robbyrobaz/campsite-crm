#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import html

HOST='127.0.0.1'
PORT=8767
KANBAN = Path('/home/rob/.openclaw/workspace/projects/ops-kanban-board.md')

class H(BaseHTTPRequestHandler):
    def sendb(self,b,ctype='text/html; charset=utf-8',status=200):
        self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == '/healthz':
            return self.sendb(b'ok', 'text/plain')
        text = KANBAN.read_text(encoding='utf-8', errors='ignore') if KANBAN.exists() else 'missing kanban file'
        body = f"""<!doctype html><html><head><meta charset='utf-8'><title>Ops Kanban</title><style>body{{font-family:Arial;padding:20px}}pre{{white-space:pre-wrap;background:#fafafa;border:1px solid #ddd;padding:12px}}</style></head><body><h1>Ops Kanban Board</h1><p>Source: {KANBAN}</p><pre>{html.escape(text)}</pre></body></html>"""
        self.sendb(body.encode())

if __name__=='__main__':
    HTTPServer((HOST, PORT), H).serve_forever()
