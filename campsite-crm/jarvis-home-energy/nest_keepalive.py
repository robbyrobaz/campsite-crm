#!/usr/bin/env python3
"""Ping Nest API to keep refresh token alive. Run daily via cron."""
import sys
sys.path.insert(0, '/home/rob/.openclaw/workspace/jarvis-home-energy')

from config import NEST_CLIENT_ID, NEST_CLIENT_SECRET, NEST_REFRESH_TOKEN, NEST_PROJECT_ID
import urllib.request, urllib.parse, json

def refresh_and_ping():
    # Refresh token
    data = urllib.parse.urlencode({
        "client_id": NEST_CLIENT_ID,
        "client_secret": NEST_CLIENT_SECRET,
        "refresh_token": NEST_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read())
    access_token = resp["access_token"]
    
    # Ping SDM API
    url = f"https://smartdevicemanagement.googleapis.com/v1/enterprises/{NEST_PROJECT_ID}/devices"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        devices = json.loads(r.read())
    print(f"OK: {len(devices.get('devices', []))} devices")

if __name__ == "__main__":
    try:
        refresh_and_ping()
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)
