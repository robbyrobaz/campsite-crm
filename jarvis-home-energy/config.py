"""
Jarvis Home Energy OS — Device Configuration
Edit credentials here after initial setup.
"""

# ─── SPAN Panel ───────────────────────────────────────────────────────────────
# Device: span-nj-2307-006gl.local | 192.168.68.93
# Auth: Bearer token (one-time registration — open door, press button 3x)
SPAN_HOST = "192.168.68.93"
SPAN_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJqYXJ2aXMtaG9tZS1vcyIsImlhdCI6MTc3MTg5MzkyNH0.4LO1WESRaJSRb9sgtlGjP1ZPnLl9zZ0qLrsVQyKwBec"

# ─── Enphase IQ Gateway (Envoy) ───────────────────────────────────────────────
# Device: envoy.local | 192.168.68.63  Serial: 202324023651  FW: D8.3.5167
# Auth: JWT (generated from Enphase cloud — valid 1 year)
ENPHASE_HOST = "192.168.68.63"
ENPHASE_SERIAL = "202324023651"
ENPHASE_TOKEN = "eyJraWQiOiI3ZDEwMDA1ZC03ODk5LTRkMGQtYmNiNC0yNDRmOThlZTE1NmIiLCJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9.eyJhdWQiOiIyMDIzMjQwMjM2NTEiLCJpc3MiOiJFbnRyZXoiLCJlbnBoYXNlVXNlciI6Im93bmVyIiwiZXhwIjoxODAzNDMxMzYwLCJpYXQiOjE3NzE4OTUzNjAsImp0aSI6IjQ0NDM2NWRmLTllMTQtNDU3YS04MjhlLThiY2NiMGQ2MTUzNiIsInVzZXJuYW1lIjoicm9iLmhhcnR3aWdAZ21haWwuY29tIn0.Sk7aVeDMCf0DsE1NG4ehOb2d_r7gZ5Fc8sUgk8Em5AXbiMY27p5ruzTjoVPfxEEVJWPASW5n6LB3PZL_mSqGjw"  # Expires ~March 2027
ENPHASE_EMAIL = "rob.hartwig@gmail.com"
ENPHASE_PASSWORD = "-pAQRDz?8$!%,25"

# ─── Pentair IntelliCenter ────────────────────────────────────────────────────
# Device: pentair.local | 192.168.68.91  Ports: 6680 (WS), 6681 (TCP)
# Auth: None required
PENTAIR_HOST = "192.168.68.91"
PENTAIR_PORT = 6681  # Use raw TCP; WebSocket on 6680 as fallback

# ─── Tesla Gateway V2 ─────────────────────────────────────────────────────────
# Device: not yet found on 192.168.68.0/22 — set IP when available
# Auth: Bearer token (email + last-5 of serial as password)
TESLA_HOST = ""  # e.g. "192.168.68.XXX"
TESLA_EMAIL = ""
TESLA_PASSWORD = ""  # Last 5 digits of Gateway serial number

# ─── SRP Utility (cloud polling — future) ─────────────────────────────────────
SRP_ACCOUNT = ""
SRP_USERNAME = ""
SRP_PASSWORD = ""

# ─── Dashboard ────────────────────────────────────────────────────────────────
DASHBOARD_PORT = 8793
POLL_INTERVAL_SECONDS = 5
