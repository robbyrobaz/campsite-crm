"""
Jarvis Home Energy OS — Device Configuration
Edit credentials here after initial setup.
"""
import os

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
# Device: pentair.local | 192.168.68.89  Ports: 6680 (WS), 6681 (TCP)
# Auth: None required
PENTAIR_HOST = "192.168.68.89"
PENTAIR_PORT = 6681  # Use raw TCP; WebSocket on 6680 as fallback

# ─── Tesla Wall Connector Gen 3 ───────────────────────────────────────────────
# Device: TeslaWallConnector_OEB496 | 192.168.68.87 | No auth required
TESLA_WC_HOST = "192.168.68.87"

# ─── Tesla Energy Gateway 3V ──────────────────────────────────────────────────
# Device: Tesla Energy Gateway 3V | 192.168.68.86 | Serial GF2240460002D2 | FW 25.26.0 | Part 1841000-02-B
# Auth: Fleet API OAuth — tokens in tesla_cache.json, auto-refresh via auth.tesla.com (NOT teslapy refresh)
TESLA_HOST = "192.168.68.86"  # Tesla Energy Gateway 3V
TESLA_EMAIL = "rob.hartwig@gmail.com"
TESLA_PASSWORD = ""  # Not needed — using Fleet API OAuth

# ─── SRP Utility (cloud polling — future) ─────────────────────────────────────
SRP_ACCOUNT = ""
SRP_USERNAME = ""
SRP_PASSWORD = ""

# ─── Wyze Cameras ─────────────────────────────────────────────────────────────
WYZE_EMAIL = "rob.hartwig@gmail.com"
WYZE_PASSWORD = "5Acq3ce3#8s$uHS"
WYZE_API_KEY = "Fn1phBRix8ifLx0t5f3ktIyVfz2uRBSWdipswwjAiEJ0Z8SIAmVnaCNZLoOL"
WYZE_KEY_ID = "ec0dd323-1db4-4e81-8cd4-a4feab256bae"

# ─── Ring Doorbell ────────────────────────────────────────────────────────────
RING_EMAIL = "rob.hartwig@gmail.com"
RING_PASSWORD = "L#MzBsX27h&j.r9"

# ─── Nest Thermostat (Google SDM API) ────────────────────────────────────────
# OAuth app: Google Cloud project 574885630755
NEST_CLIENT_ID = "574885630755-q50rqpgonjsr603ccjkgl5ra25mmp97e.apps.googleusercontent.com"
NEST_CLIENT_SECRET = "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"
NEST_REFRESH_TOKEN = "1//06gPKGWopgVBUCgYIARAAGAYSNwF-L9IrCgnJ43ttjwJ9aok18HwaH_QSG1GxA-hDYo1g5JOxjIRcGO3lAcFpDnOfRCnOggM0_RU"
NEST_PROJECT_ID = "edc12ede-0076-42d4-86d8-c87f49aec4b4"
NEST_ACCESS_TOKEN = ""  # Auto-refreshed at runtime — leave blank

# ─── B-Hyve Sprinkler ─────────────────────────────────────────────────────────
# Device: 192.168.68.66 (Orbit B-Hyve controller) — cloud API only via api.orbitbhyve.com
BHYVE_EMAIL = "rob.hartwig@gmail.com"
BHYVE_PASSWORD = "fjyaJAZ8!TRjLLq"

# ─── MyQ Garage Door ──────────────────────────────────────────────────────────
# Chamberlain/LiftMaster MyQ — cloud API via pymyq
# Set MYQ_EMAIL and MYQ_PASSWORD environment variables (do NOT hardcode here)
MYQ_EMAIL    = os.getenv("MYQ_EMAIL", "")
MYQ_PASSWORD = os.getenv("MYQ_PASSWORD", "")

# ─── Dashboard ────────────────────────────────────────────────────────────────
DASHBOARD_PORT = 8793
POLL_INTERVAL_SECONDS = 5

TESLA_ENERGY_SITE_ID = 2252397277512276  # "My Home" energy site (Gateway 3, no Powerwall)

# ─── GE SmartHQ Appliances ────────────────────────────────────────────────────
# Register at https://developers.smarthq.com to obtain client credentials.
# Use OAuth2 Resource Owner Password Credentials grant (client_id + username/password).
GE_CLIENT_ID = "1uBdIDY5Km1pbHIbQIl27mdIZJdxGG3M7W2K77D7FwMOyA0n"
GE_CLIENT_SECRET = "n2roZALTuHPPeyXXWGxBDGsDeNplweaYq6hc320C7PQ6AJRm4bWgIbxkozktuzTg"
GE_REFRESH_TOKEN = "uw2e5ireefyo9vjwh8tkrejct5as71ua"  # obtained 2026-02-26
GE_REDIRECT_URI = "http://127.0.0.1:8484/callback"
