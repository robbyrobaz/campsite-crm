"""Enphase Envoy local API client."""

import os
import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

ENPHASE_IP = os.getenv("ENPHASE_IP", "192.168.68.63")
ENPHASE_TOKEN = os.getenv("ENPHASE_TOKEN", "")

HEADERS = {"Authorization": f"Bearer {ENPHASE_TOKEN}"}
BASE = f"https://{ENPHASE_IP}"
TIMEOUT = 5.0


async def get_production() -> dict:
    """Returns wattsNow, wattHoursToday, wattHoursLifetime."""
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
        r = await client.get(f"{BASE}/api/v1/production", headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def get_meters() -> dict | None:
    """Returns meter readings (production/consumption channels)."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            r = await client.get(f"{BASE}/ivp/meters/readings", headers=HEADERS)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None
